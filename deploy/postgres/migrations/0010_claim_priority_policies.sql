create table strategyos_claim_priority_policies (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    reference_revision_id uuid not null,
    metric_key text not null,
    scope_key text not null,
    policy_version integer not null check (policy_version > 0),
    ranked_source_keys jsonb not null check (jsonb_typeof(ranked_source_keys)='array' and jsonb_array_length(ranked_source_keys) between 1 and 100),
    required_assessment jsonb check (required_assessment is null or jsonb_typeof(required_assessment)='object'),
    rationale text not null check (length(btrim(rationale))>0),
    recorded_by text not null,
    fingerprint text not null,
    effective_from timestamptz not null default clock_timestamp(),
    effective_to timestamptz,
    foreign key (tenant_id,reference_revision_id)
        references strategyos_claim_revisions(tenant_id,id) on delete restrict,
    unique (tenant_id,scope_key,policy_version),
    check (effective_to is null or effective_to > effective_from)
);
create unique index uq_claim_priority_current on strategyos_claim_priority_policies(tenant_id,scope_key)
    where effective_to is null;
create index idx_claim_priority_lookup on strategyos_claim_priority_policies(tenant_id,metric_key,effective_from);
