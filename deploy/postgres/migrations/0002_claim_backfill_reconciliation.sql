create table if not exists strategyos_claim_backfill_exceptions (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    ingestion_batch_id uuid not null references strategyos_ingestion_batches(id) on delete cascade,
    evidence_document_id uuid references strategyos_evidence_documents(id) on delete restrict,
    record_type text not null,
    record_key text not null,
    source_locator text,
    reason_code text not null,
    detail text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (ingestion_batch_id, record_type, record_key, reason_code)
);

create table if not exists strategyos_claim_reconciliations (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    run_id uuid not null references strategyos_runs(id) on delete cascade,
    ingestion_batch_id uuid not null references strategyos_ingestion_batches(id) on delete cascade,
    status text not null check (status in ('passed', 'partial', 'failed')),
    source_record_count integer not null check (source_record_count >= 0),
    claim_record_count integer not null check (claim_record_count >= 0),
    exception_count integer not null check (exception_count >= 0),
    source_amount_sar numeric not null default 0,
    claim_amount_sar numeric not null default 0,
    difference_sar numeric not null default 0,
    checks jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (run_id, ingestion_batch_id)
);

create index if not exists idx_strategyos_claim_backfill_exceptions_run
    on strategyos_claim_backfill_exceptions(run_id, reason_code, created_at);

create index if not exists idx_strategyos_claim_reconciliations_run
    on strategyos_claim_reconciliations(run_id, created_at desc);
