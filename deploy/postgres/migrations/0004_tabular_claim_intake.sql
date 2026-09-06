create table if not exists strategyos_claim_intake_receipts (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    evidence_occurrence_id uuid not null references strategyos_evidence_occurrences(id) on delete restrict,
    effect_key text not null,
    mapping_key text not null,
    mapping_version text not null,
    mapping_contract jsonb not null,
    source_hash text not null,
    recorded_by text not null,
    result jsonb not null,
    created_at timestamptz not null default now(),
    unique (tenant_id, effect_key)
);
create index if not exists idx_claim_intake_receipts_tenant
    on strategyos_claim_intake_receipts(tenant_id, created_at desc);
