-- Fail migration on inconsistent existing rows; never repair ownership by guess.
create unique index uq_claim_source_tenant_identity on strategyos_source_systems(tenant_id,id);
create unique index uq_claim_family_tenant_lane on strategyos_claim_families(tenant_id,id,claim_kind_lane);
create unique index uq_claim_revision_tenant_family on strategyos_claim_revisions(tenant_id,claim_family_id,id);
create unique index uq_claim_occurrence_tenant_identity on strategyos_evidence_occurrences(tenant_id,id);
create unique index uq_claim_snapshot_tenant_identity on strategyos_analysis_snapshots(tenant_id,id);

alter table strategyos_source_access_policies add constraint fk_policy_source_tenant
    foreign key (tenant_id,source_system_id) references strategyos_source_systems(tenant_id,id) on delete cascade;
alter table strategyos_source_registration_versions add constraint fk_registration_source_tenant
    foreign key (tenant_id,source_system_id) references strategyos_source_systems(tenant_id,id) on delete cascade;
alter table strategyos_evidence_occurrences add constraint fk_occurrence_source_tenant
    foreign key (tenant_id,source_system_id) references strategyos_source_systems(tenant_id,id) on delete restrict;
alter table strategyos_claim_revisions add constraint fk_revision_family_tenant_lane
    foreign key (tenant_id,claim_family_id,claim_kind) references strategyos_claim_families(tenant_id,id,claim_kind_lane) on delete cascade;
alter table strategyos_claim_revisions add constraint fk_revision_predecessor_family
    foreign key (tenant_id,claim_family_id,supersedes_revision_id) references strategyos_claim_revisions(tenant_id,claim_family_id,id) on delete restrict;
alter table strategyos_claim_assessments add constraint fk_assessment_revision_tenant
    foreign key (tenant_id,claim_revision_id) references strategyos_claim_revisions(tenant_id,id) on delete cascade;
alter table strategyos_claim_projection_outbox add constraint fk_outbox_revision_tenant
    foreign key (tenant_id,claim_revision_id) references strategyos_claim_revisions(tenant_id,id) on delete cascade;
alter table strategyos_claim_projection_cache add constraint fk_cache_revision_tenant
    foreign key (tenant_id,claim_revision_id) references strategyos_claim_revisions(tenant_id,id) on delete cascade;
alter table strategyos_claim_intake_receipts add constraint fk_intake_occurrence_tenant
    foreign key (tenant_id,evidence_occurrence_id) references strategyos_evidence_occurrences(tenant_id,id) on delete restrict;

alter table strategyos_claim_evidence_links add column tenant_id uuid;
update strategyos_claim_evidence_links l set tenant_id=r.tenant_id
    from strategyos_claim_revisions r where r.id=l.claim_revision_id;
alter table strategyos_claim_evidence_links alter column tenant_id set not null;
alter table strategyos_claim_evidence_links add constraint fk_evidence_link_claim_tenant
    foreign key (tenant_id,claim_revision_id) references strategyos_claim_revisions(tenant_id,id) on delete cascade;
alter table strategyos_claim_evidence_links add constraint fk_evidence_link_occurrence_tenant
    foreign key (tenant_id,evidence_occurrence_id) references strategyos_evidence_occurrences(tenant_id,id) on delete restrict;

alter table strategyos_claim_dependencies add column tenant_id uuid;
update strategyos_claim_dependencies d set tenant_id=r.tenant_id
    from strategyos_claim_revisions r where r.id=d.derived_claim_revision_id;
alter table strategyos_claim_dependencies alter column tenant_id set not null;
alter table strategyos_claim_dependencies add constraint fk_dependency_derived_tenant
    foreign key (tenant_id,derived_claim_revision_id) references strategyos_claim_revisions(tenant_id,id) on delete cascade;
alter table strategyos_claim_dependencies add constraint fk_dependency_input_tenant
    foreign key (tenant_id,input_claim_revision_id) references strategyos_claim_revisions(tenant_id,id) on delete restrict;
create index idx_claim_dependency_input_tenant on strategyos_claim_dependencies(tenant_id,input_claim_revision_id);

alter table strategyos_analysis_snapshot_claims add column tenant_id uuid;
update strategyos_analysis_snapshot_claims c set tenant_id=s.tenant_id
    from strategyos_analysis_snapshots s where s.id=c.snapshot_id;
alter table strategyos_analysis_snapshot_claims alter column tenant_id set not null;
alter table strategyos_analysis_snapshot_claims add constraint fk_snapshot_member_snapshot_tenant
    foreign key (tenant_id,snapshot_id) references strategyos_analysis_snapshots(tenant_id,id) on delete cascade;
alter table strategyos_analysis_snapshot_claims add constraint fk_snapshot_member_revision_family
    foreign key (tenant_id,claim_family_id,claim_revision_id) references strategyos_claim_revisions(tenant_id,claim_family_id,id) on delete restrict;

-- Existing application writers omit the redundant tenant column. Derive it
-- only from the canonical left-hand parent; composite FKs validate both ends.
-- Explicitly supplied tenant values are never replaced to make a bad link fit.
create function strategyos_claim_link_tenant() returns trigger language plpgsql as $$
begin
    if new.tenant_id is null then
        if tg_table_name='strategyos_claim_evidence_links' then
            select tenant_id into new.tenant_id from strategyos_claim_revisions where id=new.claim_revision_id;
        elsif tg_table_name='strategyos_claim_dependencies' then
            select tenant_id into new.tenant_id from strategyos_claim_revisions where id=new.derived_claim_revision_id;
        elsif tg_table_name='strategyos_analysis_snapshot_claims' then
            select tenant_id into new.tenant_id from strategyos_analysis_snapshots where id=new.snapshot_id;
        end if;
    end if;
    return new;
end;
$$;
create trigger claim_evidence_tenant before insert or update on strategyos_claim_evidence_links
    for each row execute function strategyos_claim_link_tenant();
create trigger claim_dependency_tenant before insert or update on strategyos_claim_dependencies
    for each row execute function strategyos_claim_link_tenant();
create trigger claim_snapshot_tenant before insert or update on strategyos_analysis_snapshot_claims
    for each row execute function strategyos_claim_link_tenant();
