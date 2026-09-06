alter table strategyos_claim_projection_outbox
    add column if not exists available_at timestamptz not null default now(),
    add column if not exists locked_at timestamptz,
    add column if not exists locked_by text,
    add column if not exists dead_lettered_at timestamptz;

create table if not exists strategyos_claim_projection_cache (
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    claim_revision_id uuid primary key references strategyos_claim_revisions(id) on delete cascade,
    family_key text not null,
    metric_key text not null,
    claim_kind text not null,
    business_unit text,
    payload jsonb not null,
    projected_at timestamptz not null default now()
);

create index if not exists idx_strategyos_claim_outbox_delivery
    on strategyos_claim_projection_outbox(available_at, created_at)
    where published_at is null and dead_lettered_at is null;

create index if not exists idx_strategyos_claim_projection_cache_lookup
    on strategyos_claim_projection_cache(tenant_id, metric_key, claim_kind, business_unit);
