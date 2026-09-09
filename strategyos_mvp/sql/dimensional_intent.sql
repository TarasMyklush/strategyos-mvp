-- Additive, explicit migration. No existing plan/run/board data is modified.
SELECT pg_advisory_xact_lock(71380921);
CREATE TABLE IF NOT EXISTS strategyos_intent_plan_versions (
 tenant_key text NOT NULL, plan_id text NOT NULL, version integer NOT NULL CHECK(version > 0),
 source_pack_id text NOT NULL, payload jsonb NOT NULL, digest text NOT NULL,
 imported_by text NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, plan_id, version)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_actual_versions (
 tenant_key text NOT NULL, revision text NOT NULL, source_pack_id text NOT NULL,
 payload jsonb NOT NULL, digest text NOT NULL,
 imported_by text NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, revision)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_ratifier_events (
 tenant_key text NOT NULL, plan_id text NOT NULL, subject text NOT NULL,
 revision integer NOT NULL CHECK(revision > 0), enabled boolean NOT NULL,
 changed_by text NOT NULL, changed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, plan_id, subject, revision)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_ratifications (
 tenant_key text NOT NULL, plan_id text NOT NULL, version integer NOT NULL,
 plan_digest text NOT NULL, approved_by text NOT NULL, approved_at timestamptz NOT NULL DEFAULT now(),
 grant_revision integer NOT NULL, note text NOT NULL,
 PRIMARY KEY(tenant_key, plan_id, version),
 FOREIGN KEY(tenant_key, plan_id, version) REFERENCES strategyos_intent_plan_versions(tenant_key, plan_id, version),
 FOREIGN KEY(tenant_key, plan_id, approved_by, grant_revision)
 REFERENCES strategyos_intent_ratifier_events(tenant_key, plan_id, subject, revision)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_analyses (
 tenant_key text NOT NULL, analysis_id text NOT NULL,
 plan_id text NOT NULL, plan_version integer NOT NULL, actual_revision text NOT NULL,
 payload jsonb NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, analysis_id),
 FOREIGN KEY(tenant_key, plan_id, plan_version) REFERENCES strategyos_intent_ratifications(tenant_key, plan_id, version),
 FOREIGN KEY(tenant_key, actual_revision) REFERENCES strategyos_intent_actual_versions(tenant_key, revision)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_advisor_configs (
 tenant_key text NOT NULL, config_id text NOT NULL, version integer NOT NULL CHECK(version > 0),
 payload jsonb NOT NULL, digest text NOT NULL,
 created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, config_id, version)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_advisor_approvals (
 tenant_key text NOT NULL, config_id text NOT NULL, version integer NOT NULL,
 config_digest text NOT NULL, approved_by text NOT NULL, note text NOT NULL,
 approved_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, config_id, version),
 FOREIGN KEY(tenant_key, config_id, version)
 REFERENCES strategyos_intent_advisor_configs(tenant_key, config_id, version)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_advisor_publications (
 tenant_key text NOT NULL, config_id text NOT NULL, version integer NOT NULL,
 config_digest text NOT NULL, plan_id text NOT NULL, plan_version integer NOT NULL,
 plan_digest text NOT NULL, published_by text NOT NULL, published_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, config_id, version),
 FOREIGN KEY(tenant_key, config_id, version)
 REFERENCES strategyos_intent_advisor_approvals(tenant_key, config_id, version),
 FOREIGN KEY(tenant_key, plan_id, plan_version)
 REFERENCES strategyos_intent_plan_versions(tenant_key, plan_id, version)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_board_templates (
 tenant_key text NOT NULL, template_id text NOT NULL, version integer NOT NULL CHECK(version > 0),
 payload jsonb NOT NULL, digest text NOT NULL, origin jsonb NOT NULL,
 created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, template_id, version)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_board_packs (
 tenant_key text NOT NULL, pack_id text NOT NULL, analysis_id text NOT NULL,
 template_id text NOT NULL, template_version integer NOT NULL, language text NOT NULL,
 payload jsonb NOT NULL, digest text NOT NULL,
 created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, pack_id),
 FOREIGN KEY(tenant_key, analysis_id)
 REFERENCES strategyos_intent_analyses(tenant_key, analysis_id),
 FOREIGN KEY(tenant_key, template_id, template_version)
 REFERENCES strategyos_intent_board_templates(tenant_key, template_id, version),
 CHECK(language IN ('en', 'ar', 'bilingual'))
);
CREATE TABLE IF NOT EXISTS strategyos_intent_structure_configs (
 tenant_key text NOT NULL, config_id text NOT NULL, version integer NOT NULL CHECK(version > 0),
 payload jsonb NOT NULL, digest text NOT NULL,
 created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, config_id, version)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_structure_approvals (
 tenant_key text NOT NULL, config_id text NOT NULL, version integer NOT NULL,
 config_digest text NOT NULL, approved_by text NOT NULL, note text NOT NULL,
 approved_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, config_id, version),
 FOREIGN KEY(tenant_key, config_id, version)
 REFERENCES strategyos_intent_structure_configs(tenant_key, config_id, version)
);
CREATE TABLE IF NOT EXISTS strategyos_intent_outreach_requests (
 tenant_key text NOT NULL, request_id text NOT NULL,
 payload jsonb NOT NULL, created_by text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_key, request_id)
);
CREATE OR REPLACE FUNCTION strategyos_intent_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Intent history is immutable; append a new version or event'; END $$;
DO $$ DECLARE table_name text; BEGIN
 FOREACH table_name IN ARRAY ARRAY['strategyos_intent_plan_versions', 'strategyos_intent_actual_versions',
   'strategyos_intent_ratifier_events', 'strategyos_intent_ratifications', 'strategyos_intent_analyses',
   'strategyos_intent_advisor_configs', 'strategyos_intent_advisor_approvals',
   'strategyos_intent_advisor_publications', 'strategyos_intent_board_templates',
   'strategyos_intent_board_packs', 'strategyos_intent_structure_configs',
   'strategyos_intent_structure_approvals', 'strategyos_intent_outreach_requests'] LOOP
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = table_name || '_immutable'
      AND tgrelid = to_regclass(table_name)) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION strategyos_intent_reject_change()',
     table_name || '_immutable', table_name);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = table_name || '_no_truncate'
      AND tgrelid = to_regclass(table_name)) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION strategyos_intent_reject_change()',
     table_name || '_no_truncate', table_name);
  END IF;
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename=table_name AND policyname=table_name || '_tenant') THEN
   EXECUTE format($policy$CREATE POLICY %I ON %I USING (tenant_key = nullif(current_setting('strategyos.tenant_key', true), '')) WITH CHECK (tenant_key = nullif(current_setting('strategyos.tenant_key', true), ''))$policy$, table_name || '_tenant', table_name);
  END IF;
 END LOOP;
END $$;
