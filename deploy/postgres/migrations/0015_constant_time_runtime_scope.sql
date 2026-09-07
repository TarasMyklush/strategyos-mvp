-- Resolve a runtime's database-enforced scope through PostgreSQL role
-- membership. pg_has_role is constant-time and avoids evaluating a pg_roles
-- catalogue lookup for every row visited by an RLS policy.
create or replace function strategyos_database_runtime_scope() returns text
language sql stable security definer
set search_path = pg_catalog
as $$
    select case
        when pg_has_role(session_user, 'strategyos_preview_request_scope', 'MEMBER') then 'request'
        when pg_has_role(session_user, 'strategyos_preview_worker_scope', 'MEMBER') then 'worker'
        when pg_has_role(session_user, 'strategyos_preview_projector_scope', 'MEMBER') then 'projector'
        else 'untrusted'
    end
$$;

revoke all on function strategyos_database_runtime_scope() from public;
grant execute on function strategyos_database_runtime_scope() to public;
