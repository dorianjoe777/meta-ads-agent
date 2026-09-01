-- Runtime-keyed entitlement boundary for the central campaign compiler.
--
-- The compiler receives a runtime key, never a tenant id.  This function
-- resolves only an active tenant and delegates the entitlement decision to
-- the canonical image-access resolver.  No prompts, results, or secrets are
-- persisted or exposed by this boundary.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:016_central_campaign_compiler', 0));

CREATE OR REPLACE FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(
  p_runtime_key text
)
RETURNS TABLE (lifecycle_state text, route text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
  SELECT access.lifecycle_state, access.route
  FROM admira.tenant_runtime_leases AS runtime
  JOIN admira.tenants AS tenant ON tenant.id = runtime.tenant_id
  CROSS JOIN LATERAL admira.resolve_tenant_image_access(tenant.id) AS access
  WHERE runtime.runtime_key = btrim(p_runtime_key)
    AND tenant.status = 'active'
$$;

ALTER FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(text)
  OWNER TO admira_control_owner;

REVOKE ALL ON FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(text)
  FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA admira FROM admira_image;
GRANT USAGE ON SCHEMA admira TO admira_image;
GRANT EXECUTE ON FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(text)
  TO admira_image;

COMMENT ON FUNCTION admira.resolve_central_campaign_compiler_access_for_runtime(text) IS
  'Runtime-keyed central campaign compiler entitlement; active tenants only, resolved by resolve_tenant_image_access.';

COMMIT;
