-- Revisions and assessments are append-only business records. A correction or
-- withdrawal is a new attributable record, never an in-place SQL edit.
-- This is defense in depth, not a substitute for non-owner runtime roles/RLS.
-- Retention/erasure is a separately authorized administrative workflow; this
-- migration does not introduce an unreviewed erase endpoint or bypass flag.
create or replace function strategyos_reject_immutable_claim_mutation()
returns trigger language plpgsql as $$
begin
    if TG_OP = 'UPDATE' and NEW is not distinct from OLD then
        return NEW;
    end if;
    raise exception 'Immutable claim record: append a correction or assessment instead'
        using errcode = '23514';
end;
$$;

create trigger strategyos_claim_revision_immutable
before update or delete on strategyos_claim_revisions
for each row execute function strategyos_reject_immutable_claim_mutation();

create trigger strategyos_claim_assessment_immutable
before update or delete on strategyos_claim_assessments
for each row execute function strategyos_reject_immutable_claim_mutation();
