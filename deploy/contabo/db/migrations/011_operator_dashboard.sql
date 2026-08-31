-- Internal operator dashboard boundary. Provider credentials remain only in
-- private host files; the dashboard can register metadata and read a bounded
-- public-safe project status projection, not tenant or recovery records.
BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:011_operator_dashboard', 0));

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_operator') THEN
    CREATE ROLE admira_operator NOLOGIN NOBYPASSRLS;
  END IF;
END;
$$;
ALTER ROLE admira_operator
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

CREATE OR REPLACE FUNCTION admira.operator_gemini_pool_status()
RETURNS TABLE (
  project_ref text, capacity integer, health text, health_checked_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
  SELECT p.project_ref, p.max_trial_assignments, p.health, p.health_checked_at
  FROM admira.gemini_pool_projects AS p
  ORDER BY p.project_ref;
$$;
ALTER FUNCTION admira.operator_gemini_pool_status() OWNER TO admira_control_owner;

-- Keep all existing FORCE ROW LEVEL SECURITY policies untouched. Explicitly
-- strip pre-release direct grants before granting the three intended APIs.
REVOKE ALL ON ALL TABLES IN SCHEMA admira FROM admira_operator;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA admira FROM admira_operator;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA admira FROM admira_operator;
REVOKE admira_provisioner FROM admira_operator;
GRANT USAGE ON SCHEMA admira TO admira_operator;
REVOKE ALL ON FUNCTION admira.operator_gemini_pool_status() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.operator_gemini_pool_status(),
  admira.register_gemini_pool_project(text, integer, text),
  admira.register_gemini_pool_credential(uuid, text, text, text, text)
  TO admira_operator;

-- Upgrade pre-release installations safely. The password is managed only by
-- bootstrap_service_roles.sql, and this migration never reads it.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_operator_login') THEN
    REVOKE admira_provisioner FROM admira_operator_login;
    ALTER ROLE admira_operator_login
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    GRANT admira_operator TO admira_operator_login;
  END IF;
END;
$$;

COMMENT ON FUNCTION admira.operator_gemini_pool_status() IS
  'Operator-only project status; excludes secret references, fingerprints, credentials and tenant identifiers.';
COMMIT;
