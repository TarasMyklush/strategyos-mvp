create extension if not exists pgcrypto;

create table if not exists strategyos_runs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    run_dir text not null,
    dataset_root text not null,
    finding_count integer not null,
    locked_finding_count integer not null,
    total_recoverable_sar numeric(18, 2) not null,
    summary_json jsonb not null
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
    finding_id text not null,
    reviewer text not null,
    decision text not null check (decision in ('approved', 'rejected', 'needs_more_evidence', 'edited')),
    comment text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

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
create index if not exists idx_strategyos_findings_pattern on strategyos_findings(pattern_type);
create index if not exists idx_strategyos_artifacts_run on strategyos_artifacts(run_id);
create index if not exists idx_strategyos_ingestion_batches_run on strategyos_ingestion_batches(run_id);
create index if not exists idx_strategyos_evidence_documents_hash on strategyos_evidence_documents(source_hash);
create index if not exists idx_strategyos_finance_entities_type on strategyos_finance_entities(entity_type);
create index if not exists idx_strategyos_finance_transactions_type on strategyos_finance_transactions(transaction_type);
create index if not exists idx_strategyos_finding_citations_run on strategyos_finding_citations(run_id);
create index if not exists idx_strategyos_kg_nodes_label on strategyos_kg_nodes(label);
create index if not exists idx_strategyos_kg_edges_label on strategyos_kg_edges(label);
