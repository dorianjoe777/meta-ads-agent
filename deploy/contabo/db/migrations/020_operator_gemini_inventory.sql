-- Add a secret-free occupancy projection without changing the legacy API.
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('admira:020_operator_gemini_inventory', 0));
CREATE OR REPLACE FUNCTION admira.operator_gemini_pool_inventory()
RETURNS TABLE (
  project_ref text, capacity integer, health text, health_checked_at timestamptz,
  used integer, available integer, clients text[]
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
  SELECT p.project_ref, p.max_trial_assignments, p.health, p.health_checked_at,
    occupancy.used,
    CASE WHEN p.health IN ('healthy', 'degraded') AND EXISTS (
      SELECT 1 FROM admira.gemini_pool_credentials c
      WHERE c.project_id = p.id AND c.active AND c.key_kind = 'auth'
        AND c.health IN ('healthy', 'degraded')
    ) THEN greatest(0, p.max_trial_assignments - occupancy.used) ELSE 0 END,
    occupancy.clients
  FROM admira.gemini_pool_projects p
  CROSS JOIN LATERAL (
    SELECT count(*)::integer AS used,
      coalesce(array_agg(l.runtime_key ORDER BY l.runtime_key)
        FILTER (WHERE l.runtime_key IS NOT NULL), ARRAY[]::text[]) AS clients
    FROM admira.gemini_pool_assignments a
    LEFT JOIN admira.tenant_runtime_leases l ON l.tenant_id = a.tenant_id
    WHERE a.project_id = p.id AND a.status = 'active'
  ) occupancy
  ORDER BY p.project_ref;
$$;
ALTER FUNCTION admira.operator_gemini_pool_inventory() OWNER TO admira_control_owner;
REVOKE ALL ON FUNCTION admira.operator_gemini_pool_inventory() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.operator_gemini_pool_inventory() TO admira_operator;
COMMIT;
