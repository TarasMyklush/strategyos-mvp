-- A recalculation may wait for input-family locks. Transaction-start time could
-- otherwise place its new revision before the input it actually consumed.
-- Preserve historical timestamps; only future inserts use the recording clock.
alter table strategyos_claim_revisions
    alter column recorded_at set default clock_timestamp();
