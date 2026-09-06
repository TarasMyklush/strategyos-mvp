alter table strategyos_source_systems
    add column if not exists source_key text,
    add column if not exists origin_category text not null default 'unknown'
        check (origin_category in ('internal_system', 'public_web', 'licensed_external', 'correspondence', 'unknown')),
    add column if not exists capture_method text not null default 'unknown'
        check (capture_method in ('unknown', 'file_upload', 'folder_import', 'api', 'email', 'chat', 'manual_entry')),
    add column if not exists governed_owner text,
    add column if not exists provider_name text,
    add column if not exists authorization_basis text,
    add column if not exists license_policy_ref text,
    add column if not exists metadata jsonb not null default '{}'::jsonb;

update strategyos_source_systems
set source_key = concat('legacy:', id::text)
where source_key is null;

alter table strategyos_source_systems alter column source_key set not null;

create unique index if not exists uq_strategyos_source_systems_tenant_key
    on strategyos_source_systems(tenant_id, source_key);

create table if not exists strategyos_source_access_policies (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    source_system_id uuid not null references strategyos_source_systems(id) on delete cascade,
    policy_version integer not null check (policy_version > 0),
    policy_fingerprint text not null,
    allowed_roles text[] not null check (cardinality(allowed_roles) > 0),
    allowed_purposes text[] not null check (cardinality(allowed_purposes) > 0),
    allowed_business_units text[] not null default '{}',
    export_allowed boolean not null default false,
    external_model_allowed boolean not null default false,
    quote_allowed boolean not null default false,
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    recorded_by text not null,
    rationale text,
    created_at timestamptz not null default now(),
    unique (source_system_id, policy_version),
    unique (source_system_id, policy_fingerprint),
    check (effective_to is null or effective_to > effective_from)
);

create unique index if not exists uq_strategyos_source_access_policy_current
    on strategyos_source_access_policies(source_system_id)
    where effective_to is null;

create table if not exists strategyos_source_registration_versions (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    source_system_id uuid not null references strategyos_source_systems(id) on delete cascade,
    registration_version integer not null check (registration_version > 0),
    registration_fingerprint text not null,
    display_name text not null,
    origin_category text not null check (origin_category in ('internal_system', 'public_web', 'licensed_external', 'correspondence', 'unknown')),
    capture_method text not null check (capture_method in ('unknown', 'file_upload', 'folder_import', 'api', 'email', 'chat', 'manual_entry')),
    governed_owner text,
    provider_name text,
    authorization_basis text,
    license_policy_ref text,
    retention_class text not null,
    sensitivity_class text not null,
    metadata jsonb not null default '{}'::jsonb,
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    recorded_by text not null,
    rationale text,
    unique (source_system_id, registration_version),
    unique (source_system_id, registration_fingerprint),
    check (effective_to is null or effective_to > effective_from)
);

create unique index if not exists uq_strategyos_source_registration_current
    on strategyos_source_registration_versions(source_system_id)
    where effective_to is null;

create table if not exists strategyos_evidence_occurrences (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    source_system_id uuid not null references strategyos_source_systems(id) on delete restrict,
    evidence_document_id uuid not null references strategyos_evidence_documents(id) on delete restrict,
    ingestion_batch_id uuid references strategyos_ingestion_batches(id) on delete set null,
    occurrence_key text not null,
    source_native_id text not null,
    source_native_version text not null default '1',
    original_uri text,
    author_identity text,
    published_at timestamptz,
    received_at timestamptz not null,
    source_locator text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (tenant_id, occurrence_key),
    unique (tenant_id, source_system_id, source_native_id, source_native_version)
);

create table if not exists strategyos_claim_families (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    family_key text not null,
    assertion_namespace text not null,
    claim_kind_lane text not null check (claim_kind_lane in ('actual', 'plan', 'forecast', 'assumption', 'reported_claim', 'unknown')),
    subject_type text not null,
    subject_key text not null,
    metric_key text not null,
    business_unit text,
    dimensions jsonb not null default '{}'::jsonb,
    period_start date,
    period_end date,
    scenario_key text,
    created_at timestamptz not null default now(),
    unique (tenant_id, family_key),
    check (period_end is null or period_start is null or period_end >= period_start)
);

create table if not exists strategyos_claim_revisions (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    claim_family_id uuid not null references strategyos_claim_families(id) on delete cascade,
    revision_number integer not null check (revision_number > 0),
    fingerprint text not null,
    claim_kind text not null check (claim_kind in ('actual', 'plan', 'forecast', 'assumption', 'reported_claim', 'unknown')),
    production_method text not null check (production_method in ('imported', 'human_entered', 'extracted', 'calculated')),
    value_numeric numeric,
    value_text text,
    unit text,
    scale numeric not null default 1 check (scale > 0),
    currency char(3),
    as_of_at timestamptz,
    fiscal_calendar text,
    timezone text,
    author_identity text,
    valid_until timestamptz,
    assumptions jsonb not null default '[]'::jsonb,
    formula_key text,
    formula_version text,
    traceability_state text not null check (traceability_state in ('present', 'incomplete', 'missing')),
    supersedes_revision_id uuid references strategyos_claim_revisions(id) on delete restrict,
    metadata jsonb not null default '{}'::jsonb,
    recorded_at timestamptz not null default now(),
    unique (claim_family_id, revision_number),
    unique (claim_family_id, fingerprint),
    check (value_numeric is not null or nullif(btrim(value_text), '') is not null),
    check (value_numeric is null or nullif(btrim(unit), '') is not null),
    check (currency is null or currency = upper(currency)),
    check (claim_kind <> 'forecast' or nullif(btrim(author_identity), '') is not null),
    check (
        (production_method = 'calculated' and formula_key is not null and formula_version is not null)
        or (production_method <> 'calculated' and formula_key is null and formula_version is null)
    )
);

create table if not exists strategyos_claim_evidence_links (
    claim_revision_id uuid not null references strategyos_claim_revisions(id) on delete cascade,
    evidence_occurrence_id uuid not null references strategyos_evidence_occurrences(id) on delete restrict,
    relationship_type text not null check (relationship_type in ('supports', 'contradicts', 'reported_in')),
    source_locator text,
    excerpt_hash text,
    created_at timestamptz not null default now(),
    primary key (claim_revision_id, evidence_occurrence_id, relationship_type)
);

create table if not exists strategyos_claim_assessments (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    claim_revision_id uuid not null references strategyos_claim_revisions(id) on delete cascade,
    assessment_type text not null,
    result text not null,
    rule_version text not null,
    assessed_by text not null,
    assessed_at timestamptz not null,
    scope_key text,
    reasons jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    payload_fingerprint text not null,
    effect_key text not null,
    unique (tenant_id, effect_key)
);

create table if not exists strategyos_claim_dependencies (
    derived_claim_revision_id uuid not null references strategyos_claim_revisions(id) on delete cascade,
    input_claim_revision_id uuid not null references strategyos_claim_revisions(id) on delete restrict,
    input_role text not null,
    created_at timestamptz not null default now(),
    primary key (derived_claim_revision_id, input_claim_revision_id, input_role),
    check (derived_claim_revision_id <> input_claim_revision_id)
);

create table if not exists strategyos_analysis_snapshots (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    snapshot_key text not null,
    as_of_at timestamptz not null,
    policy_version text not null,
    created_by text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (tenant_id, snapshot_key)
);

create table if not exists strategyos_analysis_snapshot_claims (
    snapshot_id uuid not null references strategyos_analysis_snapshots(id) on delete cascade,
    claim_family_id uuid not null references strategyos_claim_families(id) on delete restrict,
    claim_revision_id uuid not null references strategyos_claim_revisions(id) on delete restrict,
    selection_reason text not null,
    primary key (snapshot_id, claim_family_id)
);

create table if not exists strategyos_claim_projection_outbox (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    claim_revision_id uuid references strategyos_claim_revisions(id) on delete cascade,
    projection_type text not null check (projection_type in ('graph', 'vector', 'cache')),
    operation text not null check (operation in ('upsert', 'delete', 'revoke')),
    payload jsonb not null default '{}'::jsonb,
    idempotency_key text not null,
    publish_attempts integer not null default 0,
    published_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    unique (tenant_id, projection_type, idempotency_key)
);

create index if not exists idx_strategyos_occurrences_source_received
    on strategyos_evidence_occurrences(tenant_id, source_system_id, received_at desc);
create index if not exists idx_strategyos_claim_families_lookup
    on strategyos_claim_families(tenant_id, metric_key, claim_kind_lane, subject_key, business_unit, period_end);
create index if not exists idx_strategyos_claim_revisions_family_recorded
    on strategyos_claim_revisions(claim_family_id, recorded_at desc);
create index if not exists idx_strategyos_claim_assessments_revision
    on strategyos_claim_assessments(claim_revision_id, assessed_at desc);
create index if not exists idx_strategyos_claim_outbox_pending
    on strategyos_claim_projection_outbox(created_at)
    where published_at is null;
