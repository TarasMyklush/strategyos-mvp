-- Preserve old policy records and record a new explicit content-rights version.
-- Only existing internal-system policies retain their already operating local
-- storage/indexing behavior. External and unknown origins fail closed until a
-- governed operator explicitly records those rights. No export/model grant.
alter table strategyos_source_access_policies
    drop constraint strategyos_source_access_poli_source_system_id_policy_finge_key,
    drop constraint strategyos_source_access_policies_allowed_roles_check,
    drop constraint strategyos_source_access_policies_allowed_purposes_check,
    add column storage_allowed boolean not null default false,
    add column index_allowed boolean not null default false;

with previous as (
    update strategyos_source_access_policies
    set effective_to = clock_timestamp()
    where effective_to is null
    returning *
)
insert into strategyos_source_access_policies
    (tenant_id, source_system_id, policy_version, policy_fingerprint,
     allowed_roles, allowed_purposes, allowed_business_units,
     export_allowed, external_model_allowed, quote_allowed,
     storage_allowed, index_allowed, recorded_by, rationale)
select p.tenant_id,p.source_system_id,p.policy_version+1,
       p.policy_fingerprint || ':content-rights-v1',
       p.allowed_roles,p.allowed_purposes,p.allowed_business_units,
       p.export_allowed,p.external_model_allowed,p.quote_allowed,
       s.origin_category='internal_system',s.origin_category='internal_system',
       'system:content-rights-migration',
       'Internal-source local storage/indexing parity only. Other origins require explicit rights. Existing export/model/quotation limits are unchanged.'
from previous p join strategyos_source_systems s on s.id=p.source_system_id;
