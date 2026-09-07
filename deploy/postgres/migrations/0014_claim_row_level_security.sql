-- Database-enforced tenant isolation for the governed source-and-claim ledger.
-- The schema owner remains the migration authority. Application logins are
-- non-owners and therefore cannot bypass these policies.

create function strategyos_request_tenant_uuid() returns uuid
language plpgsql stable as $$
declare
    value text;
begin
    value := nullif(current_setting('strategyos.tenant_uuid', true), '');
    if value is null then return null; end if;
    return value::uuid;
exception when invalid_text_representation then
    return null;
end;
$$;

create function strategyos_database_runtime_scope() returns text
language sql stable security definer
set search_path = pg_catalog
as $$
    select case shobj_description(r.oid, 'pg_authid')
        when 'strategyos-preview-runtime:1' then 'request'
        when 'strategyos-preview-worker:1' then 'worker'
        when 'strategyos-preview-projector:1' then 'projector'
        else 'untrusted'
    end
    from pg_roles r where r.rolname = session_user
$$;

revoke all on function strategyos_database_runtime_scope() from public;
grant execute on function strategyos_database_runtime_scope() to public;

alter table strategyos_tenants enable row level security;
create policy strategyos_tenant_isolation on strategyos_tenants
    using (
        id = strategyos_request_tenant_uuid()
        or slug = current_setting('strategyos.tenant_key', true)
        or id::text = current_setting('strategyos.tenant_key', true)
        or strategyos_database_runtime_scope() in ('worker', 'projector')
    )
    with check (
        id = strategyos_request_tenant_uuid()
        or strategyos_database_runtime_scope() = 'worker'
    );

-- Projectors need source lineage to enforce current indexing rights. Workers
-- may ingest/reconcile all queued tenants. Request connections see one tenant.
alter table strategyos_source_systems enable row level security;
create policy strategyos_source_systems_isolation on strategyos_source_systems
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_ingestion_batches enable row level security;
create policy strategyos_ingestion_batches_isolation on strategyos_ingestion_batches
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_evidence_documents enable row level security;
create policy strategyos_evidence_documents_isolation on strategyos_evidence_documents
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_ingestion_batch_documents enable row level security;
create policy strategyos_ingestion_batch_documents_isolation
    on strategyos_ingestion_batch_documents
    using (exists (
        select 1 from strategyos_ingestion_batches b
        where b.id = strategyos_ingestion_batch_documents.batch_id
          and (b.tenant_id = strategyos_request_tenant_uuid()
               or strategyos_database_runtime_scope() = 'worker')
    ))
    with check (exists (
        select 1 from strategyos_ingestion_batches b
        where b.id = strategyos_ingestion_batch_documents.batch_id
          and (b.tenant_id = strategyos_request_tenant_uuid()
               or strategyos_database_runtime_scope() = 'worker')
    ));

alter table strategyos_source_access_policies enable row level security;
create policy strategyos_source_access_policies_isolation on strategyos_source_access_policies
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_source_registration_versions enable row level security;
create policy strategyos_source_registration_versions_isolation on strategyos_source_registration_versions
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_evidence_occurrences enable row level security;
create policy strategyos_evidence_occurrences_isolation on strategyos_evidence_occurrences
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_families enable row level security;
create policy strategyos_claim_families_isolation on strategyos_claim_families
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_revisions enable row level security;
create policy strategyos_claim_revisions_isolation on strategyos_claim_revisions
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_evidence_links enable row level security;
create policy strategyos_claim_evidence_links_isolation on strategyos_claim_evidence_links
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_assessments enable row level security;
create policy strategyos_claim_assessments_isolation on strategyos_claim_assessments
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_dependencies enable row level security;
create policy strategyos_claim_dependencies_isolation on strategyos_claim_dependencies
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_analysis_snapshots enable row level security;
create policy strategyos_analysis_snapshots_isolation on strategyos_analysis_snapshots
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_analysis_snapshot_claims enable row level security;
create policy strategyos_analysis_snapshot_claims_isolation on strategyos_analysis_snapshot_claims
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_projection_outbox enable row level security;
create policy strategyos_claim_projection_outbox_isolation on strategyos_claim_projection_outbox
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() in ('worker', 'projector'));

alter table strategyos_claim_projection_cache enable row level security;
create policy strategyos_claim_projection_cache_isolation on strategyos_claim_projection_cache
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() in ('worker', 'projector'))
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() in ('worker', 'projector'));

-- Operational receipts are tenant-readable and worker-writable. Projectors do
-- not need them, so their role has no RLS path or table grant.
alter table strategyos_claim_intake_receipts enable row level security;
create policy strategyos_claim_intake_receipts_isolation on strategyos_claim_intake_receipts
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_backfill_exceptions enable row level security;
create policy strategyos_claim_backfill_exceptions_isolation on strategyos_claim_backfill_exceptions
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_reconciliations enable row level security;
create policy strategyos_claim_reconciliations_isolation on strategyos_claim_reconciliations
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_recalculation_receipts enable row level security;
create policy strategyos_claim_recalculation_receipts_isolation on strategyos_claim_recalculation_receipts
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');

alter table strategyos_claim_priority_policies enable row level security;
create policy strategyos_claim_priority_policies_isolation on strategyos_claim_priority_policies
    using (tenant_id = strategyos_request_tenant_uuid()
           or strategyos_database_runtime_scope() = 'worker')
    with check (tenant_id = strategyos_request_tenant_uuid()
                or strategyos_database_runtime_scope() = 'worker');
