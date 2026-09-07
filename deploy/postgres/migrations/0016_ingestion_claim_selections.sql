-- Record the exact immutable claim revisions selected by each ingestion batch.
-- Evidence documents and occurrences are deliberately deduplicated across
-- reruns, so they cannot safely be used to infer run membership.

create unique index uq_strategyos_ingestion_batch_tenant_identity
    on strategyos_ingestion_batches(tenant_id, id);

create table strategyos_ingestion_batch_claims (
    tenant_id uuid not null references strategyos_tenants(id) on delete cascade,
    ingestion_batch_id uuid not null,
    claim_revision_id uuid not null,
    selection_reason text not null,
    recorded_at timestamptz not null default now(),
    primary key (ingestion_batch_id, claim_revision_id),
    foreign key (tenant_id, ingestion_batch_id)
        references strategyos_ingestion_batches(tenant_id, id) on delete cascade,
    foreign key (tenant_id, claim_revision_id)
        references strategyos_claim_revisions(tenant_id, id) on delete restrict
);

create index idx_strategyos_ingestion_batch_claims_revision
    on strategyos_ingestion_batch_claims(tenant_id, claim_revision_id);

alter table strategyos_ingestion_batch_claims enable row level security;
create policy strategyos_ingestion_batch_claims_isolation
    on strategyos_ingestion_batch_claims
    using (
        tenant_id = strategyos_request_tenant_uuid()
        or strategyos_database_runtime_scope() = 'worker'
    )
    with check (
        tenant_id = strategyos_request_tenant_uuid()
        or strategyos_database_runtime_scope() = 'worker'
    );

create trigger strategyos_ingestion_batch_claim_immutable
before update or delete on strategyos_ingestion_batch_claims
for each row execute function strategyos_reject_immutable_claim_mutation();
