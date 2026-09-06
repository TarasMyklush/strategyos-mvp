from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Mapping

from .source_claims import (
    ClaimAssessment,
    ClaimDraft,
    ClaimKind,
    ClaimQuery,
    ClaimRevision,
    EvidenceOccurrence,
    PolicyContext,
    SourceAccessPolicy,
    SourceRegistration,
    TraceabilityState,
    UsePurpose,
    claim_is_eligible,
    policy_allows,
    provenance_view,
)


ConnectionFactory = Callable[[], tuple[Any | None, dict[str, Any] | None]]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _record(cur: Any, row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    columns = [str(item.name if hasattr(item, "name") else item[0]) for item in cur.description]
    return dict(zip(columns, row))


class ClaimRepository:
    """Transactional repository for the canonical source and claim ledger."""

    def __init__(self, connection_factory: ConnectionFactory | None = None) -> None:
        if connection_factory is None:
            from .state_store import database_connection

            connection_factory = database_connection
        self._connection_factory = connection_factory
        self._schema_ready = False

    def register_source(
        self,
        source: SourceRegistration,
        *,
        policy: SourceAccessPolicy,
        recorded_by: str,
        rationale: str,
    ) -> dict[str, Any]:
        if policy.source_key != source.source_key:
            raise ValueError("Source policy and registration keys must match.")
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                tenant_id = self._tenant_uuid(cur, source.tenant_id)
                cur.execute(
                    """
                    insert into strategyos_source_systems
                        (tenant_id, name, system_type, source_key, origin_category, capture_method,
                         governed_owner, provider_name, authorization_basis, license_policy_ref, metadata)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (tenant_id, source_key) do update set
                        name = excluded.name,
                        origin_category = excluded.origin_category,
                        capture_method = excluded.capture_method,
                        governed_owner = excluded.governed_owner,
                        provider_name = excluded.provider_name,
                        authorization_basis = excluded.authorization_basis,
                        license_policy_ref = excluded.license_policy_ref,
                        metadata = excluded.metadata,
                        status = 'active'
                    returning id
                    """,
                    (
                        tenant_id,
                        source.display_name,
                        f"canonical_source:{source.source_key}",
                        source.source_key,
                        source.origin_category,
                        source.capture_method,
                        source.governed_owner,
                        source.provider_name,
                        source.authorization_basis,
                        source.license_policy_ref,
                        _json(dict(source.metadata)),
                    ),
                )
                source_id = cur.fetchone()[0]
                registration_version, registration_created = self._record_source_registration_version(
                    cur,
                    tenant_id=tenant_id,
                    source_system_id=source_id,
                    source=source,
                    recorded_by=recorded_by,
                    rationale=rationale,
                )
                cur.execute(
                    """
                    select id, policy_version
                    from strategyos_source_access_policies
                    where source_system_id = %s and policy_fingerprint = %s
                    """,
                    (source_id, policy.fingerprint),
                )
                existing_policy = cur.fetchone()
                if existing_policy is not None:
                    conn.commit()
                    return {
                        "source_system_id": str(source_id),
                        "policy_id": str(existing_policy[0]),
                        "policy_version": int(existing_policy[1]),
                        "registration_version": registration_version,
                        "registration_created": registration_created,
                        "policy_created": False,
                    }
                cur.execute(
                    "select coalesce(max(policy_version), 0) from strategyos_source_access_policies where source_system_id = %s",
                    (source_id,),
                )
                version = int(cur.fetchone()[0]) + 1
                cur.execute(
                    "update strategyos_source_access_policies set effective_to = now() where source_system_id = %s and effective_to is null",
                    (source_id,),
                )
                cur.execute(
                    """
                    insert into strategyos_source_access_policies
                        (tenant_id, source_system_id, policy_version, policy_fingerprint,
                         allowed_roles, allowed_purposes,
                         allowed_business_units, export_allowed, external_model_allowed, quote_allowed,
                         recorded_by, rationale)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning id
                    """,
                    (
                        tenant_id,
                        source_id,
                        version,
                        policy.fingerprint,
                        sorted(policy.allowed_roles),
                        sorted(str(item) for item in policy.allowed_purposes),
                        sorted(policy.allowed_business_units),
                        policy.export_allowed,
                        policy.external_model_allowed,
                        policy.quote_allowed,
                        recorded_by,
                        rationale,
                    ),
                )
                policy_id = cur.fetchone()[0]
            conn.commit()
        return {
            "source_system_id": str(source_id),
            "policy_id": str(policy_id),
            "policy_version": version,
            "registration_version": registration_version,
            "registration_created": registration_created,
            "policy_created": True,
        }

    def record_occurrence(
        self,
        occurrence: EvidenceOccurrence,
        *,
        evidence_document_id: str,
        ingestion_batch_id: str | None = None,
    ) -> dict[str, Any]:
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                tenant_id = self._tenant_uuid(cur, occurrence.tenant_id)
                occurrence = replace(occurrence, tenant_id=str(tenant_id))
                source_id = self._source_uuid(cur, tenant_id, occurrence.source_key)
                cur.execute(
                    "select source_hash from strategyos_evidence_documents where id = %s and tenant_id = %s",
                    (evidence_document_id, tenant_id),
                )
                artifact = cur.fetchone()
                if artifact is None or artifact[0] != occurrence.artifact_hash:
                    raise ValueError("Evidence artifact must belong to the tenant and match the occurrence hash.")
                if ingestion_batch_id is not None:
                    cur.execute(
                        "select id from strategyos_ingestion_batches where id = %s and tenant_id = %s",
                        (ingestion_batch_id, tenant_id),
                    )
                    if cur.fetchone() is None:
                        raise ValueError("Ingestion batch must belong to the occurrence tenant.")
                cur.execute(
                    """
                    insert into strategyos_evidence_occurrences
                        (tenant_id, source_system_id, evidence_document_id, ingestion_batch_id,
                         occurrence_key, source_native_id, source_native_version, original_uri,
                         author_identity, published_at, received_at, source_locator, metadata)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (tenant_id, occurrence_key) do nothing
                    returning id, occurrence_key, evidence_document_id, source_system_id
                    """,
                    (
                        tenant_id,
                        source_id,
                        evidence_document_id,
                        ingestion_batch_id,
                        occurrence.occurrence_key,
                        occurrence.source_native_id,
                        occurrence.source_native_version,
                        occurrence.original_uri,
                        occurrence.author_identity,
                        occurrence.published_at,
                        occurrence.received_at,
                        occurrence.locator,
                        _json(dict(occurrence.occurrence_metadata)),
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        """
                        select id, occurrence_key, evidence_document_id, source_system_id
                        from strategyos_evidence_occurrences
                        where tenant_id = %s and occurrence_key = %s
                        """,
                        (tenant_id, occurrence.occurrence_key),
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError("Evidence occurrence conflict could not be resolved.")
                    if str(row[2]) != str(evidence_document_id) or str(row[3]) != str(source_id):
                        raise ValueError(
                            "An evidence occurrence identity cannot be reused for different content or source."
                        )
            conn.commit()
        return {"evidence_occurrence_id": str(row[0]), "occurrence_key": row[1]}

    def record_claim(
        self,
        draft: ClaimDraft,
        *,
        traceability: TraceabilityState | str,
        evidence_relationship: str = "supports",
        context: PolicyContext | None = None,
    ) -> dict[str, Any]:
        traceability = TraceabilityState(str(traceability))
        if evidence_relationship not in {"supports", "contradicts", "reported_in"}:
            raise ValueError("Unsupported evidence relationship.")
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                tenant_id = self._tenant_uuid(cur, draft.tenant_id)
                draft = replace(draft, tenant_id=str(tenant_id))
                if context is not None:
                    resolved = self._tenant_uuid(cur, context.tenant_id)
                    if str(resolved) != str(tenant_id) or context.purpose != UsePurpose.OPERATIONS:
                        raise ValueError("Claim intake requires the authenticated tenant and operations purpose.")
                    context = replace(context, tenant_id=str(resolved))
                cur.execute(
                    """
                    insert into strategyos_claim_families
                        (tenant_id, family_key, assertion_namespace, claim_kind_lane,
                         subject_type, subject_key, metric_key, business_unit,
                         dimensions, period_start, period_end, scenario_key)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    on conflict (tenant_id, family_key) do nothing
                    """,
                    (
                        tenant_id,
                        draft.family_key,
                        draft.assertion_namespace,
                        draft.claim_kind,
                        draft.subject_type,
                        draft.subject_key,
                        draft.metric_key,
                        draft.business_unit,
                        _json(dict(draft.dimensions)),
                        draft.period_start,
                        draft.period_end,
                        draft.scenario_key,
                    ),
                )
                cur.execute(
                    "select id from strategyos_claim_families where tenant_id = %s and family_key = %s for update",
                    (tenant_id, draft.family_key),
                )
                family_id = cur.fetchone()[0]
                cur.execute(
                    "select id, revision_number from strategyos_claim_revisions where claim_family_id = %s and fingerprint = %s",
                    (family_id, draft.fingerprint),
                )
                existing = cur.fetchone()
                if existing is not None:
                    if context is not None:
                        self._authorize_intake(cur, draft, str(existing[0]), context)
                    conn.commit()
                    return {"claim_revision_id": str(existing[0]), "revision_number": existing[1], "created": False}
                cur.execute(
                    "select id, revision_number from strategyos_claim_revisions where claim_family_id = %s order by revision_number desc limit 1",
                    (family_id,),
                )
                previous = cur.fetchone()
                revision_number = int(previous[1]) + 1 if previous else 1
                supersedes_id = previous[0] if previous else None
                cur.execute(
                    """
                    insert into strategyos_claim_revisions
                        (tenant_id, claim_family_id, revision_number, fingerprint, claim_kind,
                         production_method, value_numeric, value_text, unit, scale, currency, as_of_at,
                         fiscal_calendar, timezone, author_identity, valid_until, assumptions,
                         formula_key, formula_version, traceability_state, supersedes_revision_id, metadata)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s::jsonb, %s, %s, %s, %s, %s::jsonb)
                    returning id, recorded_at
                    """,
                    (
                        tenant_id,
                        family_id,
                        revision_number,
                        draft.fingerprint,
                        draft.claim_kind,
                        draft.production_method,
                        draft.value_numeric,
                        draft.value_text,
                        draft.unit,
                        draft.scale,
                        draft.currency.upper() if draft.currency else None,
                        draft.as_of_at,
                        draft.fiscal_calendar,
                        draft.timezone,
                        draft.author_identity,
                        draft.valid_until,
                        _json(list(draft.assumptions)),
                        draft.formula_key,
                        draft.formula_version,
                        traceability,
                        supersedes_id,
                        _json(dict(draft.metadata)),
                    ),
                )
                revision_id, recorded_at = cur.fetchone()
                occurrence_ids = self._occurrence_ids(cur, tenant_id, draft.source_occurrence_keys)
                if len(occurrence_ids) != len(draft.source_occurrence_keys):
                    raise ValueError("Every evidence occurrence must exist in the same tenant before recording a claim.")
                for occurrence_id in occurrence_ids:
                    cur.execute(
                        """
                        insert into strategyos_claim_evidence_links
                            (claim_revision_id, evidence_occurrence_id, relationship_type)
                        values (%s, %s, %s)
                        on conflict do nothing
                        """,
                        (revision_id, occurrence_id, evidence_relationship),
                    )
                for input_id in draft.input_revision_ids:
                    cur.execute(
                        "select claim_kind from strategyos_claim_revisions where id = %s and tenant_id = %s",
                        (input_id, tenant_id),
                    )
                    input_row = cur.fetchone()
                    if input_row is None:
                        raise ValueError("Derived inputs must be existing claim revisions in the same tenant.")
                    if draft.claim_kind == ClaimKind.ACTUAL and input_row[0] != ClaimKind.ACTUAL:
                        raise ValueError("Calculated actuals cannot contain forecast, plan or unclassified inputs.")
                    cur.execute(
                        """
                        insert into strategyos_claim_dependencies
                            (derived_claim_revision_id, input_claim_revision_id, input_role)
                        values (%s, %s, 'input')
                        """,
                        (revision_id, input_id),
                    )
                if context is not None:
                    self._authorize_intake(cur, draft, str(revision_id), context)
                for projection in ("graph", "vector", "cache"):
                    cur.execute(
                        """
                        insert into strategyos_claim_projection_outbox
                            (tenant_id, claim_revision_id, projection_type, operation, payload, idempotency_key)
                        values (%s, %s, %s, 'upsert', %s::jsonb, %s)
                        on conflict do nothing
                        """,
                        (
                            tenant_id,
                            revision_id,
                            projection,
                            _json({"claim_revision_id": str(revision_id), "family_key": draft.family_key}),
                            f"claim:{revision_id}:upsert",
                        ),
                    )
            conn.commit()
        return {
            "claim_revision_id": str(revision_id),
            "revision_number": revision_number,
            "recorded_at": recorded_at.isoformat(),
            "created": True,
        }

    def _authorize_intake(self, cur: Any, draft: ClaimDraft, revision_id: str, context: PolicyContext) -> None:
        policies, missing = self._policies_for_revision(cur, draft.tenant_id, revision_id)
        claim = ClaimRevision(revision_id=revision_id, revision_number=1,
                              recorded_at=datetime.now(UTC), draft=draft, traceability="present")
        if missing or not policy_allows(context=context, claim=claim, source_policies=policies).eligible:
            raise ValueError("Source policy does not authorize this claim intake.")

    def assess_claim(self, assessment: ClaimAssessment, *, effect_key: str) -> dict[str, Any]:
        if not effect_key.strip():
            raise ValueError("effect_key is required for idempotent assessment writes.")
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "select tenant_id from strategyos_claim_revisions where id = %s",
                    (assessment.claim_revision_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError("Claim revision not found.")
                tenant_id = row[0]
                cur.execute(
                    """
                    select id, payload_fingerprint
                    from strategyos_claim_assessments
                    where tenant_id = %s and effect_key = %s
                    """,
                    (tenant_id, effect_key),
                )
                existing = cur.fetchone()
                if existing is not None:
                    if str(existing[1]) != assessment.fingerprint:
                        raise ValueError(
                            "Idempotency effect_key cannot be reused for a different assessment."
                        )
                    conn.commit()
                    return {
                        "assessment_id": str(existing[0]),
                        "effect_key": effect_key,
                        "created": False,
                    }
                cur.execute(
                    """
                    insert into strategyos_claim_assessments
                        (tenant_id, claim_revision_id, assessment_type, result, rule_version,
                         assessed_by, assessed_at, scope_key, reasons, payload_fingerprint, effect_key)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    returning id
                    """,
                    (
                        tenant_id,
                        assessment.claim_revision_id,
                        assessment.assessment_type,
                        assessment.result,
                        assessment.rule_version,
                        assessment.assessed_by,
                        assessment.assessed_at,
                        assessment.scope_key,
                        _json(list(assessment.reasons)),
                        assessment.fingerprint,
                        effect_key,
                    ),
                )
                assessment_id = cur.fetchone()[0]
            conn.commit()
        return {
            "assessment_id": str(assessment_id),
            "effect_key": effect_key,
            "created": True,
        }

    @staticmethod
    def _record_source_registration_version(
        cur: Any,
        *,
        tenant_id: Any,
        source_system_id: Any,
        source: SourceRegistration,
        recorded_by: str,
        rationale: str,
    ) -> tuple[int, bool]:
        cur.execute(
            """
            select registration_version
            from strategyos_source_registration_versions
            where source_system_id = %s and registration_fingerprint = %s
            """,
            (source_system_id, source.fingerprint),
        )
        existing = cur.fetchone()
        if existing is not None:
            return int(existing[0]), False
        cur.execute(
            "select coalesce(max(registration_version), 0) from strategyos_source_registration_versions where source_system_id = %s",
            (source_system_id,),
        )
        version = int(cur.fetchone()[0]) + 1
        cur.execute(
            "update strategyos_source_registration_versions set effective_to = now() where source_system_id = %s and effective_to is null",
            (source_system_id,),
        )
        cur.execute(
            """
            insert into strategyos_source_registration_versions
                (tenant_id, source_system_id, registration_version, registration_fingerprint,
                 display_name, origin_category, capture_method, governed_owner, provider_name,
                 authorization_basis, license_policy_ref, retention_class, sensitivity_class,
                 metadata, recorded_by, rationale)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                tenant_id,
                source_system_id,
                version,
                source.fingerprint,
                source.display_name,
                source.origin_category,
                source.capture_method,
                source.governed_owner,
                source.provider_name,
                source.authorization_basis,
                source.license_policy_ref,
                source.retention_class,
                source.sensitivity_class,
                _json(dict(source.metadata)),
                recorded_by,
                rationale,
            ),
        )
        return version, True

    def run_source_access(self, run_id: str, *, context: PolicyContext) -> dict[str, Any]:
        """Authorize a whole-run projection before legacy prose or tables are read.

        Bulk projections cannot safely honor row-level BU restrictions. They are
        denied rather than guessing which parts of the prose are restricted.
        Granular callers should use query()/snapshot() instead.
        """
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                tenant_id = self._tenant_uuid(cur, context.tenant_id)
                cur.execute(
                    """
                    with recursive run_roots(id) as (
                        select sc.claim_revision_id
                        from strategyos_analysis_snapshots s
                        join strategyos_analysis_snapshot_claims sc on sc.snapshot_id = s.id
                        where s.tenant_id = %s and s.snapshot_key = 'run:' || %s
                        union
                        select cel.claim_revision_id
                        from strategyos_ingestion_batches b
                        join strategyos_evidence_occurrences eo on eo.ingestion_batch_id = b.id
                        join strategyos_claim_evidence_links cel on cel.evidence_occurrence_id = eo.id
                        where b.tenant_id = %s and b.run_id::text = %s
                    ), run_lineage(id) as (
                        select id from run_roots
                        union
                        select d.input_claim_revision_id
                        from strategyos_claim_dependencies d
                        join run_lineage l on d.derived_claim_revision_id = l.id
                    ), run_sources as (
                        select b.source_system_id from strategyos_ingestion_batches b
                        where b.tenant_id = %s and b.run_id::text = %s
                        union
                        select d.source_system_id from strategyos_ingestion_batches b
                        join strategyos_ingestion_batch_documents bd on bd.batch_id = b.id
                        join strategyos_evidence_documents d on d.id = bd.evidence_document_id
                        where b.tenant_id = %s and b.run_id::text = %s
                        union
                        select eo.source_system_id from strategyos_ingestion_batches b
                        join strategyos_evidence_occurrences eo on eo.ingestion_batch_id = b.id
                        where b.tenant_id = %s and b.run_id::text = %s
                        union
                        select eo.source_system_id
                        from run_lineage l
                        join strategyos_claim_evidence_links cel on cel.claim_revision_id = l.id
                        join strategyos_evidence_occurrences eo on eo.id = cel.evidence_occurrence_id
                    )
                    select ss.source_key, p.allowed_roles, p.allowed_purposes,
                           p.allowed_business_units, p.export_allowed,
                           p.external_model_allowed, p.quote_allowed,
                           exists (
                               select 1 from run_lineage l
                               join strategyos_claim_assessments a on a.claim_revision_id = l.id
                               where a.assessment_type = 'lifecycle'
                                 and a.result in ('retracted', 'rejected', 'superseded')
                                 and a.assessed_at <= now()
                           ) as withdrawn_evidence
                    from run_sources r
                    join strategyos_source_systems ss on ss.id = r.source_system_id
                    left join strategyos_source_access_policies p
                      on p.source_system_id = ss.id and p.effective_to is null
                    """,
                    (tenant_id, run_id, tenant_id, run_id, tenant_id, run_id,
                     tenant_id, run_id, tenant_id, run_id),
                )
                sources = [_record(cur, row) for row in cur.fetchall()]
        reasons: set[str] = set()
        if not sources:
            reasons.add("source_policy_missing")
        if context.business_units:
            reasons.add("bulk_business_unit_scope_denied")
        for source in sources:
            if source.get("withdrawn_evidence"):
                reasons.add("bulk_withdrawn_evidence")
            if not context.roles.intersection(source.get("allowed_roles") or ()):
                reasons.add("source_role_denied")
            if context.purpose not in (source.get("allowed_purposes") or ()):
                reasons.add("source_purpose_denied")
            if source.get("allowed_business_units"):
                reasons.add("bulk_business_unit_scope_denied")
            for purpose, field in (
                (UsePurpose.EXPORT, "export_allowed"),
                (UsePurpose.EXTERNAL_MODEL, "external_model_allowed"),
                (UsePurpose.QUOTATION, "quote_allowed"),
            ):
                if context.purpose == purpose and not source.get(field):
                    reasons.add(f"{field}_denied")
        return {"allowed": not reasons, "source_count": len(sources), "reasons": sorted(reasons)}

    def resolve_context(self, context: PolicyContext) -> PolicyContext:
        """Resolve an authenticated tenant slug without accepting a target tenant."""
        with self._require_connection() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                return replace(context, tenant_id=str(self._tenant_uuid(cur, context.tenant_id)))

    def query(self, query: ClaimQuery, *, context: PolicyContext,
              revision_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
        candidates = None if revision_ids is None else sorted(set(str(x) for x in revision_ids))
        if candidates == []:
            return []
        if candidates is not None and len(candidates) > 200:
            raise ValueError("At most 200 candidate revisions may be authorized at once.")
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                tenant_id = self._tenant_uuid(cur, query.tenant_id)
                principal_tenant_id = self._tenant_uuid(cur, context.tenant_id)
                if str(tenant_id) != str(principal_tenant_id):
                    raise ValueError("Query tenant must match the authenticated tenant.")
                query = replace(query, tenant_id=str(tenant_id))
                context = replace(context, tenant_id=str(principal_tenant_id))
                cur.execute(
                    """
                    select r.*, f.family_key, f.assertion_namespace, f.subject_type, f.subject_key, f.metric_key,
                           f.business_unit, f.dimensions, f.period_start, f.period_end, f.scenario_key
                    from strategyos_claim_revisions r
                    join strategyos_claim_families f on f.id = r.claim_family_id
                    where r.tenant_id = %s and f.metric_key = %s
                      and r.recorded_at <= %s
                      and (%s::text[] is null or r.id::text = any(%s::text[]))
                      and r.revision_number = (
                          select max(r2.revision_number)
                          from strategyos_claim_revisions r2
                          where r2.claim_family_id = r.claim_family_id and r2.recorded_at <= %s
                      )
                    order by f.period_end desc nulls last, r.recorded_at desc
                    """,
                    (tenant_id, query.metric_key, query.as_of_at, candidates, candidates, query.as_of_at),
                )
                rows = [_record(cur, row) for row in cur.fetchall()]
                results: list[dict[str, Any]] = []
                for row in rows:
                    row["source_occurrence_keys"] = self._occurrence_keys(cur, row["id"])
                    row["input_revision_ids"] = self._input_revision_ids(cur, row["id"])
                    claim = self._hydrate_claim(row)
                    assessments = self._assessments(
                        cur, claim.revision_id, as_of_at=query.as_of_at
                    )
                    source_details = self._source_details(cur, claim.revision_id)
                    policies, missing_policy_sources = self._policies_for_revision(
                        cur, tenant_id, claim.revision_id
                    )
                    if missing_policy_sources or not self._lineage_eligible(cur, claim, query, context):
                        continue
                    eligibility = claim_is_eligible(
                        claim,
                        query=query,
                        context=context,
                        source_policies=policies,
                        assessments=assessments,
                    )
                    if eligibility.eligible:
                        results.append(
                            provenance_view(
                                claim,
                                source_details=source_details,
                                assessments=assessments,
                            )
                        )
            conn.commit()
        return results

    def snapshot(
        self,
        snapshot_key: str,
        *,
        context: PolicyContext,
        metric_keys: Iterable[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return one immutable analysis snapshot after current policy checks."""
        if limit is not None and limit < 1:
            raise ValueError("Snapshot limit must be greater than zero.")
        if offset < 0:
            raise ValueError("Snapshot offset cannot be negative.")
        selected_metric_keys = sorted(
            {str(value).strip() for value in (metric_keys or ()) if str(value).strip()}
        )
        fetch_limit = limit + 1 if limit is not None else None
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                tenant_id = self._tenant_uuid(cur, context.tenant_id)
                context = replace(context, tenant_id=str(tenant_id))
                cur.execute(
                    """
                    select id, snapshot_key, as_of_at, policy_version, metadata
                    from strategyos_analysis_snapshots
                    where tenant_id = %s and snapshot_key = %s
                    """,
                    (tenant_id, snapshot_key),
                )
                snapshot_row = cur.fetchone()
                if snapshot_row is None:
                    raise KeyError("Analysis snapshot not found.")
                snapshot = _record(cur, snapshot_row)
                cur.execute(
                    """
                    select r.*, f.family_key, f.assertion_namespace, f.subject_type,
                           f.subject_key, f.metric_key, f.business_unit, f.dimensions,
                           f.period_start, f.period_end, f.scenario_key,
                           sc.selection_reason
                    from strategyos_analysis_snapshot_claims sc
                    join strategyos_claim_revisions r on r.id = sc.claim_revision_id
                    join strategyos_claim_families f on f.id = sc.claim_family_id
                    where sc.snapshot_id = %s
                      and (
                          cardinality(%s::text[]) = 0
                          or f.metric_key = any(%s::text[])
                      )
                    order by f.metric_key, f.claim_kind_lane, f.subject_key
                    limit %s offset %s
                    """,
                    (
                        snapshot["id"],
                        selected_metric_keys,
                        selected_metric_keys,
                        fetch_limit,
                        offset,
                    ),
                )
                rows = [_record(cur, row) for row in cur.fetchall()]
                has_more = limit is not None and len(rows) > limit
                if has_more:
                    rows = rows[:limit]
                records: list[dict[str, Any]] = []
                denied_count = 0
                for row in rows:
                    row["source_occurrence_keys"] = self._occurrence_keys(cur, row["id"])
                    row["input_revision_ids"] = self._input_revision_ids(cur, row["id"])
                    claim = self._hydrate_claim(row)
                    assessments = self._assessments(
                        cur, claim.revision_id, as_of_at=snapshot["as_of_at"]
                    )
                    source_details = self._source_details(cur, claim.revision_id)
                    policies, missing_policy_sources = self._policies_for_revision(
                        cur, tenant_id, claim.revision_id
                    )
                    query = ClaimQuery(
                        tenant_id=str(tenant_id),
                        metric_key=claim.draft.metric_key,
                        purpose=context.purpose,
                        as_of_at=snapshot["as_of_at"],
                        allowed_claim_kinds=frozenset({claim.draft.claim_kind}),
                        business_unit=claim.draft.business_unit,
                        scenario_key=claim.draft.scenario_key,
                    )
                    eligibility = claim_is_eligible(
                        claim,
                        query=query,
                        context=context,
                        source_policies=policies,
                        assessments=assessments,
                    )
                    if (missing_policy_sources or not eligibility.eligible
                            or not self._lineage_eligible(cur, claim, query, context)):
                        denied_count += 1
                        continue
                    record = provenance_view(
                        claim,
                        source_details=source_details,
                        assessments=assessments,
                    )
                    record["selection_reason"] = row["selection_reason"]
                    records.append(record)
            conn.commit()
        return {
            "snapshot_id": str(snapshot["id"]),
            "snapshot_key": snapshot["snapshot_key"],
            "analysis_as_of": snapshot["as_of_at"].isoformat(),
            "policy_version": snapshot["policy_version"],
            "metadata": snapshot.get("metadata") or {},
            "records": records,
            "denied_count": denied_count,
            "page": {
                "limit": limit,
                "offset": offset,
                "returned_count": len(records),
                "evaluated_count": len(rows),
                "has_more": has_more,
                "next_offset": offset + len(rows) if has_more else None,
            },
        }

    def reconciliation(self, run_id: str, *, tenant_id: str) -> dict[str, Any]:
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                resolved_tenant_id = self._tenant_uuid(cur, tenant_id)
                cur.execute(
                    """
                    select r.status, r.source_record_count, r.claim_record_count,
                           r.exception_count, r.source_amount_sar, r.claim_amount_sar,
                           r.difference_sar, r.checks, r.created_at,
                           b.id as batch_id
                    from strategyos_claim_reconciliations r
                    join strategyos_ingestion_batches b on b.id = r.ingestion_batch_id
                    where r.tenant_id = %s and r.run_id::text = %s
                    order by r.created_at desc
                    limit 1
                    """,
                    (resolved_tenant_id, run_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError("Claim reconciliation not found.")
                result = _record(cur, row)
                cur.execute(
                    """
                    select record_type, record_key, source_locator, reason_code, detail, metadata
                    from strategyos_claim_backfill_exceptions
                    where tenant_id = %s and run_id::text = %s
                    order by record_type, record_key, reason_code
                    """,
                    (resolved_tenant_id, run_id),
                )
                exceptions = [_record(cur, item) for item in cur.fetchall()]
            conn.commit()
        return {
            **{
                key: (str(value) if key in {"source_amount_sar", "claim_amount_sar", "difference_sar"} else value)
                for key, value in result.items()
                if key != "created_at"
            },
            "created_at": result["created_at"].isoformat(),
            "batch_id": str(result["batch_id"]),
            "exceptions": exceptions,
        }

    def lease_projection_batch(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lease_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        """Lease projection work without holding a database lock during I/O."""
        worker_id = worker_id.strip()
        if not worker_id:
            raise ValueError("worker_id is required.")
        limit = max(1, min(int(limit), 500))
        lease_seconds = max(30, min(int(lease_seconds), 3600))
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    with candidates as (
                        select id
                        from strategyos_claim_projection_outbox
                        where published_at is null
                          and dead_lettered_at is null
                          and available_at <= now()
                          and (
                              locked_at is null
                              or locked_at < now() - (%s * interval '1 second')
                          )
                        order by available_at, created_at, id
                        for update skip locked
                        limit %s
                    )
                    update strategyos_claim_projection_outbox o
                    set locked_at = now(), locked_by = %s,
                        publish_attempts = publish_attempts + 1,
                        last_error = null
                    from candidates c
                    where o.id = c.id
                    returning o.id, o.tenant_id, o.claim_revision_id,
                              o.projection_type, o.operation, o.payload,
                              o.idempotency_key, o.publish_attempts, o.locked_at
                    """,
                    (lease_seconds, limit, worker_id),
                )
                rows = [_record(cur, row) for row in cur.fetchall()]
            conn.commit()
        return [
            {
                **row,
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "claim_revision_id": (
                    str(row["claim_revision_id"])
                    if row.get("claim_revision_id")
                    else None
                ),
                "locked_at": row["locked_at"].isoformat(),
            }
            for row in rows
        ]

    def mark_projection_published(self, event_id: str, *, worker_id: str) -> None:
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update strategyos_claim_projection_outbox
                    set published_at = now(), locked_at = null, locked_by = null,
                        last_error = null
                    where id::text = %s and locked_by = %s
                      and published_at is null and dead_lettered_at is null
                    returning id
                    """,
                    (event_id, worker_id),
                )
                if cur.fetchone() is None:
                    raise RuntimeError("Projection lease is missing, expired or already completed.")
            conn.commit()

    def mark_projection_failed(
        self,
        event_id: str,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int,
        max_attempts: int,
    ) -> dict[str, Any]:
        error = error.strip()[:4000] or "Projection failed without an error message."
        retry_delay_seconds = max(1, min(int(retry_delay_seconds), 86400))
        max_attempts = max(1, min(int(max_attempts), 100))
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update strategyos_claim_projection_outbox
                    set last_error = %s,
                        locked_at = null,
                        locked_by = null,
                        available_at = now() + (%s * interval '1 second'),
                        dead_lettered_at = case
                            when publish_attempts >= %s then now()
                            else dead_lettered_at
                        end
                    where id::text = %s and locked_by = %s
                      and published_at is null and dead_lettered_at is null
                    returning publish_attempts, dead_lettered_at
                    """,
                    (
                        error,
                        retry_delay_seconds,
                        max_attempts,
                        event_id,
                        worker_id,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("Projection lease is missing, expired or already completed.")
            conn.commit()
        return {
            "attempts": int(row[0]),
            "dead_lettered": row[1] is not None,
        }

    def projection_record(self, claim_revision_id: str, *, tenant_id: str) -> dict[str, Any]:
        """Hydrate a claim for internal projections; PostgreSQL remains authority."""
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                resolved_tenant_id = self._tenant_uuid(cur, tenant_id)
                cur.execute(
                    """
                    select r.*, f.family_key, f.assertion_namespace, f.subject_type,
                           f.subject_key, f.metric_key, f.business_unit, f.dimensions,
                           f.period_start, f.period_end, f.scenario_key
                    from strategyos_claim_revisions r
                    join strategyos_claim_families f on f.id = r.claim_family_id
                    where r.id::text = %s and r.tenant_id = %s
                    """,
                    (claim_revision_id, resolved_tenant_id),
                )
                raw = cur.fetchone()
                if raw is None:
                    raise KeyError("Claim revision not found.")
                row = _record(cur, raw)
                row["source_occurrence_keys"] = self._occurrence_keys(cur, row["id"])
                row["input_revision_ids"] = self._input_revision_ids(cur, row["id"])
                claim = self._hydrate_claim(row)
                record = provenance_view(
                    claim,
                    source_details=self._source_details(cur, claim.revision_id),
                    assessments=self._assessments(cur, claim.revision_id),
                )
            conn.commit()
        record["tenant_id"] = str(resolved_tenant_id)
        return record

    def upsert_projection_cache(self, record: Mapping[str, Any]) -> None:
        tenant_id = str(record.get("tenant_id") or "")
        revision_id = str(record.get("claim_revision_id") or "")
        if not tenant_id or not revision_id:
            raise ValueError("Projection cache records require tenant and revision IDs.")
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                resolved_tenant_id = self._tenant_uuid(cur, tenant_id)
                cur.execute(
                    """
                    insert into strategyos_claim_projection_cache
                        (tenant_id, claim_revision_id, family_key, metric_key,
                         claim_kind, business_unit, payload)
                    values (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (claim_revision_id) do update set
                        family_key = excluded.family_key,
                        metric_key = excluded.metric_key,
                        claim_kind = excluded.claim_kind,
                        business_unit = excluded.business_unit,
                        payload = excluded.payload,
                        projected_at = now()
                    """,
                    (
                        resolved_tenant_id,
                        revision_id,
                        record.get("family_key"),
                        record.get("metric_key"),
                        str(record.get("claim_kind") or ""),
                        record.get("business_unit"),
                        _json(dict(record)),
                    ),
                )
            conn.commit()

    def delete_projection_cache(self, claim_revision_id: str, *, tenant_id: str) -> None:
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                resolved_tenant_id = self._tenant_uuid(cur, tenant_id)
                cur.execute(
                    """
                    delete from strategyos_claim_projection_cache
                    where tenant_id = %s and claim_revision_id::text = %s
                    """,
                    (resolved_tenant_id, claim_revision_id),
                )
            conn.commit()

    def projection_health(self) -> dict[str, Any]:
        connection = self._require_connection()
        with connection as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        count(*) filter (where published_at is null and dead_lettered_at is null),
                        count(*) filter (where published_at is null and locked_at is not null),
                        count(*) filter (
                            where published_at is null and locked_at < now() - interval '5 minutes'
                        ),
                        count(*) filter (where dead_lettered_at is not null),
                        extract(
                            epoch from (
                                now() - (
                                    min(created_at) filter (
                                        where published_at is null
                                          and dead_lettered_at is null
                                    )
                                )
                            )
                        )
                    from strategyos_claim_projection_outbox
                    """
                )
                pending, leased, stale_leases, dead_lettered, oldest_age = cur.fetchone()
            conn.commit()
        status = "failed" if dead_lettered or stale_leases else "ready"
        return {
            "status": status,
            "pending": int(pending),
            "leased": int(leased),
            "stale_leases": int(stale_leases),
            "dead_lettered": int(dead_lettered),
            "oldest_pending_seconds": (
                round(float(oldest_age), 3) if oldest_age is not None else None
            ),
        }

    def _require_connection(self) -> Any:
        connection, skipped = self._connection_factory()
        if connection is None:
            reason = str((skipped or {}).get("reason") or "Database is unavailable.")
            raise RuntimeError(reason)
        return connection

    def _ensure_schema(self, conn: Any) -> None:
        if self._schema_ready:
            return
        from .state_store import ensure_data_schema

        ensure_data_schema(conn)
        self._schema_ready = True

    @staticmethod
    def _tenant_uuid(cur: Any, tenant: str) -> Any:
        cur.execute("select id from strategyos_tenants where id::text = %s or slug = %s", (tenant, tenant))
        row = cur.fetchone()
        if row is None:
            raise KeyError("Tenant not found.")
        return row[0]

    @staticmethod
    def _source_uuid(cur: Any, tenant_id: Any, source_key: str) -> Any:
        cur.execute(
            "select id from strategyos_source_systems where tenant_id = %s and source_key = %s and status = 'active'",
            (tenant_id, source_key),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError("Registered source not found.")
        return row[0]

    @staticmethod
    def _occurrence_ids(cur: Any, tenant_id: Any, keys: Iterable[str]) -> list[Any]:
        values = list(keys)
        if not values:
            return []
        cur.execute(
            "select id from strategyos_evidence_occurrences where tenant_id = %s and occurrence_key = any(%s)",
            (tenant_id, values),
        )
        return [row[0] for row in cur.fetchall()]

    @staticmethod
    def _lineage_eligible(cur: Any, claim: ClaimRevision, query: ClaimQuery, context: PolicyContext) -> bool:
        """Exact input revisions retain their own lifecycle, time and BU scope.

        A permitted derived label must not launder a withdrawn, expired,
        untraceable or out-of-scope input. Newer input revisions do not rewrite
        historical calculations; explicit lifecycle withdrawals do invalidate them.
        """
        if not claim.draft.input_revision_ids:
            return True
        cur.execute(
            """
            with recursive inputs(id) as (
                select input_claim_revision_id from strategyos_claim_dependencies
                where derived_claim_revision_id = %s
                union
                select d.input_claim_revision_id from strategyos_claim_dependencies d
                join inputs i on d.derived_claim_revision_id = i.id
            )
            select not exists (
                select 1 from inputs i
                join strategyos_claim_revisions r on r.id = i.id
                join strategyos_claim_families f on f.id = r.claim_family_id
                where r.tenant_id::text <> %s or r.recorded_at > %s
                  or r.as_of_at > %s or r.valid_until < %s
                  or r.traceability_state <> 'present'
                  or (%s::text[] <> '{}'::text[] and
                      (f.business_unit is null or not f.business_unit = any(%s::text[])))
                  or exists (select 1 from strategyos_claim_assessments a
                      where a.claim_revision_id = r.id and a.assessment_type = 'lifecycle'
                        and a.result in ('retracted','rejected','superseded') and a.assessed_at <= now())
                  or (not exists (select 1 from strategyos_claim_evidence_links e where e.claim_revision_id = r.id)
                      and not exists (select 1 from strategyos_claim_dependencies d where d.derived_claim_revision_id = r.id))
            )
            """,
            (claim.revision_id, context.tenant_id, query.as_of_at, query.as_of_at,
             query.as_of_at, sorted(context.business_units), sorted(context.business_units)),
        )
        return bool(cur.fetchone()[0])

    @staticmethod
    def _assessments(
        cur: Any,
        revision_id: str,
        *,
        as_of_at: datetime | None = None,
    ) -> list[ClaimAssessment]:
        cur.execute(
            """
            select claim_revision_id, assessment_type, result, rule_version,
                   assessed_by, assessed_at, reasons, scope_key
            from strategyos_claim_assessments
            where claim_revision_id = %s
              and (%s::timestamptz is null or assessed_at <= %s
                   or (assessment_type = 'lifecycle' and assessed_at <= now()))
            order by assessed_at
            """,
            (revision_id, as_of_at, as_of_at),
        )
        out: list[ClaimAssessment] = []
        for row in cur.fetchall():
            item = _record(cur, row)
            out.append(
                ClaimAssessment(
                    claim_revision_id=str(item["claim_revision_id"]),
                    assessment_type=item["assessment_type"],
                    result=item["result"],
                    rule_version=item["rule_version"],
                    assessed_by=item["assessed_by"],
                    assessed_at=item["assessed_at"],
                    reasons=tuple(item.get("reasons") or []),
                    scope_key=item.get("scope_key"),
                )
            )
        return out

    @staticmethod
    def _occurrence_keys(cur: Any, revision_id: str) -> list[str]:
        cur.execute(
            """
            select eo.occurrence_key
            from strategyos_claim_evidence_links cel
            join strategyos_evidence_occurrences eo on eo.id = cel.evidence_occurrence_id
            where cel.claim_revision_id = %s
            order by eo.occurrence_key
            """,
            (revision_id,),
        )
        return [str(row[0]) for row in cur.fetchall()]

    @staticmethod
    def _input_revision_ids(cur: Any, revision_id: str) -> list[str]:
        cur.execute(
            """
            select input_claim_revision_id
            from strategyos_claim_dependencies
            where derived_claim_revision_id = %s
            order by input_role, input_claim_revision_id
            """,
            (revision_id,),
        )
        return [str(row[0]) for row in cur.fetchall()]

    @staticmethod
    def _source_details(cur: Any, revision_id: str) -> dict[str, dict[str, Any]]:
        cur.execute(
            """
            with recursive lineage(id) as (
                select %s::uuid
                union
                select d.input_claim_revision_id
                from strategyos_claim_dependencies d
                join lineage l on d.derived_claim_revision_id = l.id
            )
            select eo.occurrence_key, ss.source_key, ss.name as display_name,
                   ss.origin_category, ss.capture_method, ss.provider_name,
                   ss.license_policy_ref, ed.sensitivity_class, ed.retention_class,
                   eo.author_identity, eo.published_at, eo.received_at,
                   eo.original_uri, eo.source_native_id, eo.source_native_version,
                   coalesce(cel.source_locator, eo.source_locator) as source_locator
            from lineage l
            join strategyos_claim_evidence_links cel on cel.claim_revision_id = l.id
            join strategyos_evidence_occurrences eo on eo.id = cel.evidence_occurrence_id
            join strategyos_source_systems ss on ss.id = eo.source_system_id
            join strategyos_evidence_documents ed on ed.id = eo.evidence_document_id
            order by ss.source_key, eo.occurrence_key
            """,
            (revision_id,),
        )
        result: dict[str, dict[str, Any]] = {}
        for row in cur.fetchall():
            item = _record(cur, row)
            result[str(item["occurrence_key"])] = {
                "source_key": item["source_key"],
                "display_name": item["display_name"],
                "origin_category": item["origin_category"],
                "capture_method": item["capture_method"],
                "provider_name": item.get("provider_name"),
                "license_policy_ref": item.get("license_policy_ref"),
                "sensitivity_class": item.get("sensitivity_class"),
                "retention_class": item.get("retention_class"),
                "author_identity": item.get("author_identity"),
                "original_uri": item.get("original_uri"),
                "source_native_id": item.get("source_native_id"),
                "source_native_version": item.get("source_native_version"),
                "published_at": item["published_at"].isoformat()
                if item.get("published_at")
                else None,
                "received_at": item["received_at"].isoformat(),
                "locator": item.get("source_locator"),
            }
        return result

    @staticmethod
    def _policies_for_revision(
        cur: Any, tenant_id: Any, revision_id: str
    ) -> tuple[list[SourceAccessPolicy], list[str]]:
        cur.execute(
            """
            with recursive lineage(id) as (
                select %s::uuid
                union
                select d.input_claim_revision_id
                from strategyos_claim_dependencies d join lineage l on d.derived_claim_revision_id = l.id
            )
            select distinct ss.source_key, p.allowed_roles, p.allowed_purposes,
                   p.allowed_business_units, p.export_allowed, p.external_model_allowed, p.quote_allowed
            from lineage l
            join strategyos_claim_evidence_links cel on cel.claim_revision_id = l.id
            join strategyos_evidence_occurrences eo on eo.id = cel.evidence_occurrence_id
            join strategyos_source_systems ss on ss.id = eo.source_system_id
            left join strategyos_source_access_policies p
              on p.source_system_id = ss.id and p.effective_to is null
            where ss.tenant_id = %s
            """,
            (revision_id, tenant_id),
        )
        out: list[SourceAccessPolicy] = []
        missing: list[str] = []
        for row in cur.fetchall():
            item = _record(cur, row)
            if not item.get("allowed_roles") or not item.get("allowed_purposes"):
                missing.append(str(item.get("source_key") or "unknown"))
                continue
            out.append(
                SourceAccessPolicy(
                    source_key=item["source_key"],
                    allowed_roles=frozenset(item["allowed_roles"]),
                    allowed_purposes=frozenset(item["allowed_purposes"]),
                    allowed_business_units=frozenset(item.get("allowed_business_units") or []),
                    export_allowed=bool(item["export_allowed"]),
                    external_model_allowed=bool(item["external_model_allowed"]),
                    quote_allowed=bool(item["quote_allowed"]),
                )
            )
        return out, sorted(set(missing))

    @staticmethod
    def _hydrate_claim(row: dict[str, Any]) -> ClaimRevision:
        draft = ClaimDraft(
            tenant_id=str(row["tenant_id"]),
            assertion_namespace=row["assertion_namespace"],
            subject_type=row["subject_type"],
            subject_key=row["subject_key"],
            metric_key=row["metric_key"],
            claim_kind=row["claim_kind"],
            production_method=row["production_method"],
            value_numeric=row.get("value_numeric"),
            value_text=row.get("value_text"),
            unit=row.get("unit"),
            scale=row.get("scale") or 1,
            currency=row.get("currency"),
            business_unit=row.get("business_unit"),
            dimensions=row.get("dimensions") or {},
            period_start=row.get("period_start"),
            period_end=row.get("period_end"),
            as_of_at=row.get("as_of_at"),
            fiscal_calendar=row.get("fiscal_calendar"),
            timezone=row.get("timezone"),
            author_identity=row.get("author_identity"),
            scenario_key=row.get("scenario_key"),
            valid_until=row.get("valid_until"),
            assumptions=tuple(row.get("assumptions") or []),
            source_occurrence_keys=tuple(row.get("source_occurrence_keys") or []),
            formula_key=row.get("formula_key"),
            formula_version=row.get("formula_version"),
            input_revision_ids=tuple(row.get("input_revision_ids") or []),
            metadata=row.get("metadata") or {},
        )
        return ClaimRevision(
            revision_id=str(row["id"]),
            revision_number=int(row["revision_number"]),
            recorded_at=row.get("recorded_at") or datetime.now(UTC),
            draft=draft,
            traceability=row["traceability_state"],
            supersedes_revision_id=str(row["supersedes_revision_id"]) if row.get("supersedes_revision_id") else None,
        )
