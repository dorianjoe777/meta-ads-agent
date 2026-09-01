-- Keep the temporary trial benefit separate from an operator-controlled
-- decision to sponsor a licensed tenant from the shared central Codex pool.
-- A licensed tenant without the explicit opt-in stays on the tenant-local
-- ChatGPT route; this migration never reads, writes, or exposes that OAuth.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:017_licensed_central_image_pool_switch', 0));

DO $$
DECLARE
  existing_type oid;
  existing_not_null boolean;
BEGIN
  SELECT attribute.atttypid, attribute.attnotnull
  INTO existing_type, existing_not_null
  FROM pg_catalog.pg_attribute AS attribute
  JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
  JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
  WHERE namespace.nspname = 'admira'
    AND relation.relname = 'tenant_entitlements'
    AND attribute.attname = 'licensed_central_image_pool_enabled'
    AND attribute.attnum > 0
    AND NOT attribute.attisdropped;

  IF existing_type IS NOT NULL AND existing_type <> 'boolean'::regtype THEN
    RAISE EXCEPTION 'licensed central image pool switch has incompatible type'
      USING ERRCODE = '42804';
  END IF;

  ALTER TABLE admira.tenant_entitlements
    ADD COLUMN IF NOT EXISTS licensed_central_image_pool_enabled boolean NOT NULL DEFAULT false;

  -- The control plane replays forward-safe migrations on every release.  A
  -- false default is therefore the only safe migration default: it cannot
  -- silently re-enable a license an operator deliberately removed from the
  -- shared pool.  Normalize an interrupted/pre-release nullable column once.
  UPDATE admira.tenant_entitlements
  SET licensed_central_image_pool_enabled = false,
      updated_at = now()
  WHERE licensed_central_image_pool_enabled IS NULL;
  ALTER TABLE admira.tenant_entitlements
    ALTER COLUMN licensed_central_image_pool_enabled SET DEFAULT false;
  IF existing_type IS NOT NULL AND NOT existing_not_null THEN
    ALTER TABLE admira.tenant_entitlements
      ALTER COLUMN licensed_central_image_pool_enabled SET NOT NULL;
  END IF;
END;
$$;

COMMENT ON COLUMN admira.tenant_entitlements.licensed_central_image_pool_enabled IS
  'Explicit operator opt-in for a licensed tenant to use the shared central Codex image/campaign pool; never stores or changes tenant OAuth.';

-- A licensed tenant starts outside the shared pool.  Only the narrow,
-- auditable operator switch below can opt it in.

CREATE OR REPLACE FUNCTION admira.resolve_tenant_image_access(p_tenant_id uuid)
RETURNS TABLE (
  lifecycle_state text, route text,
  image_sponsorship_ends_at timestamptz, trial_ends_at timestamptz
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = admira, pg_catalog
AS $$
  SELECT entitlement.lifecycle_state,
         CASE
           WHEN tenant.status <> 'active' THEN 'blocked'
           WHEN entitlement.lifecycle_state = 'trial'
                AND entitlement.trial_ends_at > now()
                AND coalesce(entitlement.image_sponsorship_ends_at, entitlement.trial_ends_at) > now()
             THEN 'central_sponsored'
           WHEN entitlement.lifecycle_state = 'licensed'
                AND entitlement.licensed_central_image_pool_enabled
             THEN 'central_sponsored'
           WHEN entitlement.lifecycle_state = 'licensed' THEN 'personal_chatgpt'
           ELSE 'blocked'
         END,
         entitlement.image_sponsorship_ends_at, entitlement.trial_ends_at
  FROM admira.tenant_entitlements AS entitlement
  JOIN admira.tenants AS tenant ON tenant.id = entitlement.tenant_id
  WHERE entitlement.tenant_id = p_tenant_id
$$;

-- Keep the existing trial-extension control, but make it impossible to use
-- the old timestamp API as a second, hidden way to sponsor a licensed tenant.
CREATE OR REPLACE FUNCTION admira.operator_set_image_sponsorship_end(
  p_runtime_key text, p_ends_at timestamptz
)
RETURNS TABLE (
  runtime_key text, lifecycle_state text, previous_ends_at timestamptz,
  image_sponsorship_ends_at timestamptz, route text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  now_value timestamptz := now();
  resolved_tenant uuid;
  tenant_status text;
  resolved_state text;
  resolved_trial_end timestamptz;
  prior_end timestamptz;
  changed integer := 0;
  resolved_route text;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_ends_at IS NULL OR p_ends_at <= now_value
     OR p_ends_at > now_value + interval '365 days' THEN
    RAISE EXCEPTION 'invalid sponsorship extension' USING ERRCODE = '22023';
  END IF;

  SELECT tenant.id, tenant.status INTO resolved_tenant, tenant_status
  FROM admira.tenants AS tenant
  WHERE tenant.external_customer_id = p_runtime_key
  FOR UPDATE;
  IF NOT FOUND OR tenant_status <> 'active' THEN
    RAISE EXCEPTION 'tenant is not active' USING ERRCODE = '55000';
  END IF;

  SELECT entitlement.lifecycle_state, entitlement.trial_ends_at,
         coalesce(entitlement.image_sponsorship_ends_at, entitlement.trial_ends_at)
  INTO resolved_state, resolved_trial_end, prior_end
  FROM admira.tenant_entitlements AS entitlement
  WHERE entitlement.tenant_id = resolved_tenant
  FOR UPDATE;
  IF NOT FOUND OR resolved_state <> 'trial'
     OR resolved_trial_end IS NULL OR resolved_trial_end <= now_value THEN
    RAISE EXCEPTION 'tenant trial is not eligible for sponsorship' USING ERRCODE = '55000';
  END IF;
  IF prior_end IS NOT NULL AND p_ends_at < prior_end THEN
    RAISE EXCEPTION 'sponsorship cannot be shortened' USING ERRCODE = '22023';
  END IF;

  UPDATE admira.tenant_entitlements AS entitlement
  SET image_sponsorship_ends_at = p_ends_at, updated_at = now_value
  WHERE entitlement.tenant_id = resolved_tenant
    AND (prior_end IS NULL OR p_ends_at > prior_end)
    AND entitlement.image_sponsorship_ends_at IS DISTINCT FROM p_ends_at;
  GET DIAGNOSTICS changed = ROW_COUNT;

  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  SELECT resolved_tenant, 'operator', 'operator-dashboard',
         'image_sponsorship_extended', 'tenant_entitlement', p_runtime_key,
         jsonb_build_object('previous_ends_at', prior_end, 'new_ends_at', p_ends_at)
  WHERE changed = 1;

  SELECT access.route INTO resolved_route
  FROM admira.resolve_tenant_image_access(resolved_tenant) AS access;
  RETURN QUERY SELECT p_runtime_key, resolved_state, prior_end,
    coalesce(
      (SELECT entitlement.image_sponsorship_ends_at
       FROM admira.tenant_entitlements AS entitlement
       WHERE entitlement.tenant_id = resolved_tenant),
      prior_end
    ), resolved_route;
END;
$$;

CREATE OR REPLACE FUNCTION admira.operator_set_licensed_central_image_pool(
  p_runtime_key text, p_enabled boolean
)
RETURNS TABLE (
  runtime_key text, lifecycle_state text,
  central_image_pool_enabled boolean, route text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  now_value timestamptz := now();
  resolved_tenant uuid;
  tenant_status text;
  resolved_state text;
  changed integer := 0;
  resolved_route text;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_enabled IS NULL THEN
    RAISE EXCEPTION 'invalid licensed central image pool setting' USING ERRCODE = '22023';
  END IF;

  SELECT tenant.id, tenant.status, entitlement.lifecycle_state
  INTO resolved_tenant, tenant_status, resolved_state
  FROM admira.tenants AS tenant
  JOIN admira.tenant_entitlements AS entitlement ON entitlement.tenant_id = tenant.id
  WHERE tenant.external_customer_id = p_runtime_key
  FOR UPDATE OF tenant, entitlement;
  IF NOT FOUND OR tenant_status <> 'active' OR resolved_state <> 'licensed' THEN
    RAISE EXCEPTION 'tenant is not an active licensed account' USING ERRCODE = '55000';
  END IF;

  UPDATE admira.tenant_entitlements AS entitlement
  SET licensed_central_image_pool_enabled = p_enabled,
      updated_at = now_value
  WHERE entitlement.tenant_id = resolved_tenant
    AND entitlement.licensed_central_image_pool_enabled IS DISTINCT FROM p_enabled;
  GET DIAGNOSTICS changed = ROW_COUNT;

  SELECT access.route INTO resolved_route
  FROM admira.resolve_tenant_image_access(resolved_tenant) AS access;

  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  SELECT resolved_tenant, 'operator', 'operator-dashboard',
         'licensed_central_image_pool_changed', 'tenant_entitlement', p_runtime_key,
         jsonb_build_object('enabled', p_enabled, 'route', resolved_route)
  WHERE changed = 1;

  RETURN QUERY SELECT p_runtime_key, resolved_state,
    (SELECT entitlement.licensed_central_image_pool_enabled
     FROM admira.tenant_entitlements AS entitlement
     WHERE entitlement.tenant_id = resolved_tenant),
    resolved_route;
END;
$$;

-- Keep the public-safe status projection stable in shape.  The date is only
-- meaningful for a trial; licensed accounts are controlled by the explicit
-- switch above and therefore deliberately expose no synthetic expiry date.
CREATE OR REPLACE FUNCTION admira.operator_tenant_sponsorship_status()
RETURNS TABLE (
  runtime_key text, display_name text, lifecycle_state text,
  trial_ends_at timestamptz, image_sponsorship_ends_at timestamptz,
  effective_sponsorship_ends_at timestamptz, route text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
  SELECT runtime.runtime_key, left(tenant.display_name, 200), entitlement.lifecycle_state,
         entitlement.trial_ends_at, entitlement.image_sponsorship_ends_at,
         CASE WHEN entitlement.lifecycle_state = 'trial'
              THEN coalesce(entitlement.image_sponsorship_ends_at, entitlement.trial_ends_at)
              ELSE NULL::timestamptz END,
         access.route
  FROM admira.tenants AS tenant
  JOIN admira.tenant_entitlements AS entitlement ON entitlement.tenant_id = tenant.id
  JOIN admira.tenant_runtime_leases AS runtime ON runtime.tenant_id = tenant.id
  LEFT JOIN LATERAL admira.resolve_tenant_image_access(tenant.id) AS access ON true
  WHERE tenant.status <> 'deleted'
  ORDER BY tenant.created_at DESC, runtime.runtime_key
  LIMIT 1000
$$;

ALTER FUNCTION admira.resolve_tenant_image_access(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_set_image_sponsorship_end(text, timestamptz)
  OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_set_licensed_central_image_pool(text, boolean)
  OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_tenant_sponsorship_status()
  OWNER TO admira_control_owner;

REVOKE ALL ON FUNCTION admira.resolve_tenant_image_access(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_set_image_sponsorship_end(text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_set_licensed_central_image_pool(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_tenant_sponsorship_status() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.resolve_tenant_image_access(uuid) TO admira_runtime;
GRANT EXECUTE ON FUNCTION admira.operator_tenant_sponsorship_status(),
  admira.operator_set_image_sponsorship_end(text, timestamptz),
  admira.operator_set_licensed_central_image_pool(text, boolean)
  TO admira_operator;

COMMENT ON FUNCTION admira.operator_set_licensed_central_image_pool(text, boolean) IS
  'Audited on/off switch for a licensed tenant to use the central Codex image/campaign pool; tenant-local ChatGPT OAuth is unchanged.';
COMMENT ON FUNCTION admira.operator_tenant_sponsorship_status() IS
  'Private operator projection for trial sponsorship and the effective licensed image route; excludes credentials, license IDs and recovery contacts.';

COMMIT;
