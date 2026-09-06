-- Written only by the deployment migration job. Runtime roles receive SELECT.
create table if not exists strategyos_runtime_schema_contract (
    singleton boolean primary key default true check (singleton),
    fingerprint text not null,
    prepared_at timestamptz not null default now(),
    prepared_by text not null default current_user
);
