-- Reverting source metadata is a new event, not reuse of an inactive version.
alter table strategyos_source_registration_versions
    drop constraint if exists strategyos_source_registratio_source_system_id_registratio_key1;
