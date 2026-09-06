create unique index uq_claim_revision_tenant_identity
    on strategyos_claim_revisions(tenant_id,id);
create table strategyos_claim_recalculation_receipts (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    source_claim_revision_id uuid not null,
    effect_key text not null,
    preview_key text not null,
    recorded_by text not null,
    rationale text not null check (length(btrim(rationale)) > 0),
    result jsonb not null,
    created_at timestamptz not null default clock_timestamp(),
    unique (tenant_id, effect_key),
    foreign key (tenant_id,source_claim_revision_id)
        references strategyos_claim_revisions(tenant_id,id) on delete restrict
);
create index idx_claim_recalculation_receipts_tenant
    on strategyos_claim_recalculation_receipts(tenant_id, created_at desc);
