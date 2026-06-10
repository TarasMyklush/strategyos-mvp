create extension if not exists pgcrypto;

create table if not exists strategyos_runs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    run_dir text not null,
    dataset_root text not null,
    finding_count integer not null,
    locked_finding_count integer not null,
    total_recoverable_sar numeric(18, 2) not null,
    status text not null default 'running',
    current_stage text,
    requires_human_review boolean not null default true,
    review_claimed_by text,
    review_claimed_at timestamptz,
    approved_at timestamptz,
    approved_by text,
    summary_json jsonb not null
);

alter table if exists strategyos_runs add column if not exists status text not null default 'running';
alter table if exists strategyos_runs add column if not exists current_stage text;
alter table if exists strategyos_runs add column if not exists requires_human_review boolean not null default true;
alter table if exists strategyos_runs add column if not exists review_claimed_by text;
alter table if exists strategyos_runs add column if not exists review_claimed_at timestamptz;
alter table if exists strategyos_runs add column if not exists approved_at timestamptz;
alter table if exists strategyos_runs add column if not exists approved_by text;

create table if not exists strategyos_run_checkpoints (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    stage text not null,
    status text not null,
    state_json jsonb not null,
    summary_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists strategyos_findings (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    finding_id text not null,
    pattern_type text not null,
    vendor_id text,
    vendor_name text,
    status text not null,
    confidence text not null,
    leakage_sar numeric(18, 2) not null,
    recoverable_sar numeric(18, 2) not null,
    finding_json jsonb not null,
    unique (run_id, finding_id)
);

create table if not exists strategyos_approvals (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    checkpoint_id uuid references strategyos_run_checkpoints(id) on delete set null,
    finding_id text,
    reviewer text not null,
    reviewer_subject text,
    reviewer_role text,
    decision text not null check (decision in ('approved', 'rejected', 'needs_more_evidence', 'edited')),
    comment text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

alter table if exists strategyos_approvals add column if not exists checkpoint_id uuid references strategyos_run_checkpoints(id) on delete set null;
alter table if exists strategyos_approvals alter column finding_id drop not null;
alter table if exists strategyos_approvals add column if not exists reviewer_subject text;
alter table if exists strategyos_approvals add column if not exists reviewer_role text;

create table if not exists strategyos_artifacts (
    id uuid primary key default gen_random_uuid(),
    run_id uuid references strategyos_runs(id) on delete cascade,
    artifact_name text not null,
    local_path text,
    object_uri text,
    sha256 text,
    created_at timestamptz not null default now()
);

create table if not exists strategyos_tenants (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    display_name text not null,
    data_residency text not null default 'client-controlled',
    created_at timestamptz not null default now()
);

create table if not exists strategyos_source_systems (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    name text not null,
    system_type text not null,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    unique (tenant_id, name, system_type)
);

create table if not exists strategyos_ingestion_batches (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    source_system_id uuid not null references strategyos_source_systems(id) on delete restrict,
    run_id uuid references strategyos_runs(id) on delete cascade,
    batch_label text not null,
    dataset_root text not null,
    status text not null default 'completed',
    manifest_json jsonb not null default '{}'::jsonb,
    started_at timestamptz not null default now(),
    completed_at timestamptz not null default now()
);

create table if not exists strategyos_evidence_documents (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    source_system_id uuid not null references strategyos_source_systems(id) on delete restrict,
    source_path text not null,
    source_group text not null,
    file_name text not null,
    media_type text not null,
    size_bytes bigint not null,
    source_hash text not null,
    source_uri text,
    object_uri text,
    sensitivity_class text not null default 'client-confidential',
    retention_class text not null default 'client-policy',
    ocr_status jsonb not null default '{}'::jsonb,
    manifest_json jsonb not null default '{}'::jsonb,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    unique (tenant_id, source_hash)
);

create table if not exists strategyos_ingestion_batch_documents (
    batch_id uuid not null references strategyos_ingestion_batches(id) on delete cascade,
    evidence_document_id uuid not null references strategyos_evidence_documents(id) on delete restrict,
    primary key (batch_id, evidence_document_id)
);

create table if not exists strategyos_finance_entities (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    batch_id uuid not null references strategyos_ingestion_batches(id) on delete cascade,
    entity_type text not null,
    natural_key text not null,
    display_name text,
    source_document_id uuid references strategyos_evidence_documents(id) on delete restrict,
    source_locator text,
    attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (batch_id, entity_type, natural_key)
);

create table if not exists strategyos_finance_transactions (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    batch_id uuid not null references strategyos_ingestion_batches(id) on delete cascade,
    transaction_type text not null,
    natural_key text not null,
    counterparty_key text,
    event_date date,
    due_date date,
    settled_date date,
    amount_sar numeric(18, 2),
    currency text,
    status text,
    source_document_id uuid references strategyos_evidence_documents(id) on delete restrict,
    source_locator text,
    attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (batch_id, transaction_type, natural_key)
);

create table if not exists strategyos_finance_balances (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    batch_id uuid not null references strategyos_ingestion_batches(id) on delete cascade,
    balance_type text not null,
    natural_key text not null,
    account text,
    account_description text,
    amount_sar numeric(18, 2),
    source_document_id uuid references strategyos_evidence_documents(id) on delete restrict,
    source_locator text,
    attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (batch_id, balance_type, natural_key)
);

create table if not exists strategyos_tenant_profiles (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    profile_id text not null,
    document_type text not null,
    profile_scope text not null default 'tenant',
    description text,
    created_at timestamptz not null default now(),
    unique (tenant_id, profile_id)
);

create table if not exists strategyos_tenant_profile_versions (
    id uuid primary key default gen_random_uuid(),
    tenant_profile_id uuid not null references strategyos_tenant_profiles(id) on delete cascade,
    version integer not null,
    lifecycle_status text not null check (lifecycle_status in ('draft', 'candidate', 'active', 'deprecated', 'retired')),
    base_version_id uuid references strategyos_tenant_profile_versions(id) on delete set null,
    parser_preferences jsonb not null default '[]'::jsonb,
    field_aliases jsonb not null default '{}'::jsonb,
    required_fields jsonb not null default '[]'::jsonb,
    validation_rules jsonb not null default '{}'::jsonb,
    sample_validation_summary jsonb not null default '{}'::jsonb,
    approver text,
    approver_subject text,
    activated_at timestamptz,
    deprecated_at timestamptz,
    retired_at timestamptz,
    created_at timestamptz not null default now(),
    unique (tenant_profile_id, version)
);

create table if not exists strategyos_canonical_finance_entities (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    entity_type text not null check (entity_type in ('supplier_account', 'buyer_entity', 'payment', 'purchase_order', 'purchase_order_line', 'goods_receipt', 'contract_term', 'credit_note', 'fx_rate', 'tax_registration')),
    canonical_key text not null,
    display_name text,
    entity_status text not null default 'active',
    version integer not null default 1,
    effective_from date,
    effective_to date,
    source_document_id uuid references strategyos_evidence_documents(id) on delete restrict,
    source_locator text,
    lineage_json jsonb not null default '{}'::jsonb,
    attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (tenant_id, entity_type, canonical_key, version)
);

create table if not exists strategyos_canonical_finance_entity_links (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    parent_entity_id uuid not null references strategyos_canonical_finance_entities(id) on delete cascade,
    child_entity_id uuid not null references strategyos_canonical_finance_entities(id) on delete cascade,
    relationship_type text not null,
    attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (parent_entity_id, child_entity_id, relationship_type)
);

create table if not exists strategyos_fx_rates (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    source_currency text not null,
    reporting_currency text not null,
    rate_source text not null,
    rate_date date not null,
    rate_value numeric(18, 8) not null,
    rate_status text not null default 'approved' check (rate_status in ('draft', 'approved', 'deprecated', 'retired')),
    fallback_allowed boolean not null default false,
    attributes jsonb not null default '{}'::jsonb,
    published_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    unique (tenant_id, source_currency, reporting_currency, rate_source, rate_date)
);

create table if not exists strategyos_backfill_runs (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    batch_id uuid references strategyos_ingestion_batches(id) on delete set null,
    legacy_run_id uuid references strategyos_runs(id) on delete set null,
    profile_version_id uuid references strategyos_tenant_profile_versions(id) on delete set null,
    parser_name text,
    parser_version text,
    canonicalization_version text,
    status text not null check (status in ('draft', 'queued', 'running', 'completed', 'failed', 'cancelled')),
    scope_json jsonb not null default '{}'::jsonb,
    result_json jsonb not null default '{}'::jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists strategyos_cutover_metrics (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    backfill_run_id uuid references strategyos_backfill_runs(id) on delete set null,
    legacy_run_id uuid references strategyos_runs(id) on delete set null,
    metric_key text not null,
    metric_scope text not null default 'tenant',
    sample_window_label text not null,
    legacy_value numeric(20, 4),
    canonical_value numeric(20, 4),
    delta_value numeric(20, 4),
    delta_ratio numeric(12, 6),
    status text not null default 'pending' check (status in ('pending', 'within_threshold', 'outside_threshold', 'investigate')),
    threshold_json jsonb not null default '{}'::jsonb,
    exclusion_breakdown jsonb not null default '{}'::jsonb,
    notes text,
    measured_at timestamptz not null default now(),
    unique (tenant_id, metric_key, sample_window_label, backfill_run_id)
);

create table if not exists strategyos_finding_citations (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    finding_id text not null,
    evidence_document_id uuid references strategyos_evidence_documents(id) on delete restrict,
    source_path text not null,
    source_hash text,
    locator text not null,
    excerpt text,
    resolved boolean not null default false,
    hash_match boolean not null default false,
    resolved_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists strategyos_agent_events (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    round_no integer not null,
    actor text not null,
    finding_id text,
    action text not null,
    detail text not null,
    event_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists strategyos_kg_nodes (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    node_key text not null,
    label text not null,
    properties jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (run_id, node_key)
);

create table if not exists strategyos_kg_edges (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    source_node_key text not null,
    target_node_key text not null,
    label text not null,
    properties jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_strategyos_runs_created_at on strategyos_runs(created_at desc);
create index if not exists idx_strategyos_runs_status on strategyos_runs(status);
create index if not exists idx_strategyos_runs_current_stage on strategyos_runs(current_stage);
create index if not exists idx_strategyos_findings_pattern on strategyos_findings(pattern_type);
create index if not exists idx_strategyos_run_checkpoints_run_created_at on strategyos_run_checkpoints(run_id, created_at desc);
create index if not exists idx_strategyos_approvals_run_created_at on strategyos_approvals(run_id, created_at desc);
create index if not exists idx_strategyos_artifacts_run on strategyos_artifacts(run_id);
create index if not exists idx_strategyos_ingestion_batches_run on strategyos_ingestion_batches(run_id);
create index if not exists idx_strategyos_evidence_documents_hash on strategyos_evidence_documents(source_hash);
create index if not exists idx_strategyos_finance_entities_type on strategyos_finance_entities(entity_type);
create index if not exists idx_strategyos_finance_transactions_type on strategyos_finance_transactions(transaction_type);
create index if not exists idx_strategyos_tenant_profiles_tenant on strategyos_tenant_profiles(tenant_id);
create index if not exists idx_strategyos_tenant_profile_versions_profile_status on strategyos_tenant_profile_versions(tenant_profile_id, lifecycle_status);
create index if not exists idx_strategyos_canonical_finance_entities_tenant_type on strategyos_canonical_finance_entities(tenant_id, entity_type);
create index if not exists idx_strategyos_canonical_finance_entity_links_parent on strategyos_canonical_finance_entity_links(parent_entity_id);
create index if not exists idx_strategyos_fx_rates_pair_date on strategyos_fx_rates(tenant_id, source_currency, reporting_currency, rate_date desc);
create index if not exists idx_strategyos_backfill_runs_tenant_status on strategyos_backfill_runs(tenant_id, status);
create index if not exists idx_strategyos_cutover_metrics_tenant_metric on strategyos_cutover_metrics(tenant_id, metric_key, measured_at desc);
create index if not exists idx_strategyos_finding_citations_run on strategyos_finding_citations(run_id);
create index if not exists idx_strategyos_kg_nodes_label on strategyos_kg_nodes(label);
create index if not exists idx_strategyos_kg_edges_label on strategyos_kg_edges(label);
