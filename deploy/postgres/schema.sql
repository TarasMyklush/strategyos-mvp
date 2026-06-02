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

create index if not exists idx_strategyos_runs_created_at on strategyos_runs(created_at desc);
create index if not exists idx_strategyos_findings_pattern on strategyos_findings(pattern_type);
create index if not exists idx_strategyos_artifacts_run on strategyos_artifacts(run_id);
