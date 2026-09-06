alter table strategyos_claim_assessments
    add column if not exists valid_until timestamptz;
alter table strategyos_claim_assessments
    add constraint ck_claim_assessment_review_expiry
    check (valid_until is null or valid_until > assessed_at);
