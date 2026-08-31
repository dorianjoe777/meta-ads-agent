-- Operator-controlled customer lifecycle.
--
-- This migration exposes narrow SECURITY DEFINER procedures to the private
-- operator role.  It deliberately does not grant that role table access or
-- provisioner/provider privileges.  Provider assignment and filesystem
-- provisioning remain host-side operations owned by their existing services.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:013_operator_trial_provisioning', 0));

CREATE OR REPLACE FUNCTION admira.operator_create_trial(
  p_runtime_key text,
  p_display_name text,
  p_actor_id text DEFAULT 'operator-dashboard'
)
RETURNS TABLE (
  runtime_key text,
  display_name text,
  lifecycle_state text,
  trial_started_at timestamptz,
  trial_ends_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  resolved_tenant uuid;
  tenant_created_at timestamptz;
  prior_state text;
  prior_trial_ends_at timestamptz;
  now_value timestamptz := clock_timestamp();
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR btrim(coalesce(p_display_name, '')) = ''
     OR char_length(btrim(p_display_name)) > 200
     OR btrim(coalesce(p_actor_id, '')) = ''
     OR char_length(btrim(p_actor_id)) > 200 THEN
    RAISE EXCEPTION 'invalid operator trial registration' USING ERRCODE = '22023';
  END IF;

  SELECT t.id, t.created_at, e.lifecycle_state, e.trial_ends_at
    INTO resolved_tenant, tenant_created_at, prior_state, prior_trial_ends_at
  FROM admira.tenants AS t
  LEFT JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  WHERE t.external_customer_id = btrim(p_runtime_key)
  FOR UPDATE OF t;

  IF resolved_tenant IS NOT NULL AND prior_state IS DISTINCT FROM 'pending_claim' THEN
    IF prior_state = 'trial' AND prior_trial_ends_at > now_value THEN
      RETURN QUERY
      SELECT l.runtime_key, left(t.display_name, 200), e.lifecycle_state,
             e.trial_started_at, e.trial_ends_at
      FROM admira.tenants AS t
      JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
      JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
      WHERE t.id = resolved_tenant;
      RETURN;
    END IF;
    IF prior_state = 'trial' THEN
      RAISE EXCEPTION 'tenant trial has expired' USING ERRCODE = '55000';
    END IF;
    RAISE EXCEPTION 'tenant already has an active lifecycle' USING ERRCODE = '55000';
  END IF;

  resolved_tenant := coalesce(
    resolved_tenant,
    admira._ensure_hosted_tenant(btrim(p_runtime_key), btrim(p_display_name))
  );

  SELECT t.created_at INTO tenant_created_at
  FROM admira.tenants AS t WHERE t.id = resolved_tenant FOR UPDATE;

  -- The clock is anchored to the tenant creation timestamp, not to Telegram
  -- claim consumption.  A legacy pending row therefore has the same rule.
  INSERT INTO admira.tenant_entitlements
    (tenant_id, plan, lifecycle_state, trial_started_at, trial_ends_at)
  VALUES (resolved_tenant, 'trial', 'trial', tenant_created_at,
          tenant_created_at + interval '5 days')
  ON CONFLICT (tenant_id) DO NOTHING;
  UPDATE admira.tenant_entitlements AS e
  SET plan = 'trial', lifecycle_state = 'trial',
      trial_started_at = coalesce(e.trial_started_at, tenant_created_at),
      trial_ends_at = coalesce(e.trial_ends_at, tenant_created_at + interval '5 days'),
      updated_at = now()
  WHERE e.tenant_id = resolved_tenant AND e.lifecycle_state = 'pending_claim';

  UPDATE admira.tenants SET status = 'active' WHERE id = resolved_tenant;

  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  VALUES (resolved_tenant, 'operator', btrim(p_actor_id), 'trial_created',
          'tenant_entitlement', p_runtime_key,
          jsonb_build_object('trial_started_at', tenant_created_at,
                             'trial_ends_at', tenant_created_at + interval '5 days'));

  RETURN QUERY
  SELECT l.runtime_key, left(t.display_name, 200), e.lifecycle_state,
         e.trial_started_at, e.trial_ends_at
  FROM admira.tenants AS t
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  WHERE t.id = resolved_tenant;
END;
$$;

CREATE OR REPLACE FUNCTION admira.operator_trial_accounts()
RETURNS TABLE (
  runtime_key text,
  display_name text,
  lifecycle_state text,
  tenant_created_at timestamptz,
  trial_started_at timestamptz,
  trial_ends_at timestamptz,
  image_sponsorship_ends_at timestamptz,
  gemini_pool_ready boolean
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = admira, pg_catalog
AS $$
  SELECT l.runtime_key, left(t.display_name, 200),
         CASE WHEN e.lifecycle_state = 'trial' AND e.trial_ends_at <= now()
              THEN 'trial_expired' ELSE e.lifecycle_state END,
         t.created_at, e.trial_started_at, e.trial_ends_at,
         e.image_sponsorship_ends_at,
         EXISTS (
           SELECT 1 FROM admira.gemini_pool_assignments AS assignment
           WHERE assignment.tenant_id = t.id AND assignment.status = 'active'
         )
  FROM admira.tenants AS t
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  WHERE t.status <> 'deleted'
    AND e.lifecycle_state IN ('pending_claim', 'trial', 'trial_expired')
  ORDER BY t.created_at DESC, l.runtime_key
  LIMIT 1000;
$$;

-- A dashboard-created tenant is already in `trial`, so the legacy claim
-- issuer (which intentionally only accepts `pending_claim`) cannot be used
-- to issue its first or a replacement deep link.  This narrow provisioner API
-- creates a one-time claim without restarting or extending the trial clock.
CREATE OR REPLACE FUNCTION admira.issue_trial_telegram_claim(
  p_runtime_key text,
  p_token_hash_hex text,
  p_ttl_seconds integer DEFAULT 1800
)
RETURNS TABLE (tenant_id uuid, expires_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  resolved_tenant uuid;
  resolved_state text;
  resolved_trial_end timestamptz;
  expiry timestamptz;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR coalesce(p_token_hash_hex, '') !~ '^[a-f0-9]{64}$'
     OR p_ttl_seconds NOT BETWEEN 300 AND 86400 THEN
    RAISE EXCEPTION 'invalid trial telegram claim' USING ERRCODE = '22023';
  END IF;
  SELECT t.id, e.lifecycle_state, e.trial_ends_at
    INTO resolved_tenant, resolved_state, resolved_trial_end
  FROM admira.tenants AS t
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  WHERE t.external_customer_id = btrim(p_runtime_key)
    AND t.status = 'active'
  FOR UPDATE OF t;
  IF NOT FOUND OR resolved_state <> 'trial' OR resolved_trial_end IS NULL
     OR resolved_trial_end <= now() THEN
    RAISE EXCEPTION 'tenant is not an active trial' USING ERRCODE = '55000';
  END IF;
  UPDATE admira.tenant_telegram_claims AS c SET used_at = now()
  WHERE c.tenant_id = resolved_tenant AND c.used_at IS NULL;
  expiry := now() + make_interval(secs => p_ttl_seconds);
  INSERT INTO admira.tenant_telegram_claims (tenant_id, token_hash, expires_at)
  VALUES (resolved_tenant, decode(p_token_hash_hex, 'hex'), expiry);
  RETURN QUERY SELECT resolved_tenant, expiry;
END;
$$;

CREATE OR REPLACE FUNCTION admira.operator_licensed_accounts()
RETURNS TABLE (
  runtime_key text,
  display_name text,
  lifecycle_state text,
  license_mask text,
  licensed_at timestamptz,
  paid_through timestamptz,
  image_sponsorship_ends_at timestamptz
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = admira, pg_catalog
AS $$
  SELECT l.runtime_key, left(t.display_name, 200), e.lifecycle_state,
         CASE WHEN e.license_id IS NULL THEN NULL
              WHEN char_length(e.license_id) <= 8 THEN repeat('•', char_length(e.license_id))
              ELSE left(e.license_id, 4) || '••••' || right(e.license_id, 4) END,
         e.licensed_at, e.paid_through,
         e.image_sponsorship_ends_at
  FROM admira.tenants AS t
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  WHERE t.status <> 'deleted' AND e.lifecycle_state = 'licensed'
  ORDER BY e.licensed_at DESC NULLS LAST, t.created_at DESC, l.runtime_key
  LIMIT 1000;
$$;

CREATE OR REPLACE FUNCTION admira.operator_extend_trial(
  p_runtime_key text,
  p_trial_ends_at timestamptz,
  p_actor_id text DEFAULT 'operator-dashboard'
)
RETURNS TABLE (runtime_key text, lifecycle_state text,
               previous_trial_ends_at timestamptz, trial_ends_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  resolved_tenant uuid;
  prior_end timestamptz;
  resolved_state text;
  now_value timestamptz := clock_timestamp();
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_trial_ends_at IS NULL OR p_trial_ends_at <= now_value
     OR p_trial_ends_at > now_value + interval '365 days'
     OR btrim(coalesce(p_actor_id, '')) = '' OR char_length(btrim(p_actor_id)) > 200 THEN
    RAISE EXCEPTION 'invalid trial extension' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant FROM admira.tenants AS t
  WHERE t.external_customer_id = btrim(p_runtime_key) AND t.status <> 'deleted'
  FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023'; END IF;
  SELECT e.lifecycle_state, e.trial_ends_at INTO resolved_state, prior_end
  FROM admira.tenant_entitlements AS e WHERE e.tenant_id = resolved_tenant FOR UPDATE;
  IF resolved_state <> 'trial' OR prior_end IS NULL THEN
    RAISE EXCEPTION 'tenant is not an active trial' USING ERRCODE = '55000';
  END IF;
  IF p_trial_ends_at < prior_end THEN
    RAISE EXCEPTION 'trial extension must be later than current end' USING ERRCODE = '22023';
  END IF;
  -- A retried dashboard request must not create a second audit event or turn
  -- a transient response loss into an error. The same exact end is already
  -- the desired state, while shortening remains forbidden above.
  IF p_trial_ends_at = prior_end THEN
    RETURN QUERY SELECT p_runtime_key, resolved_state, prior_end, prior_end;
    RETURN;
  END IF;
  UPDATE admira.tenant_entitlements
  SET trial_ends_at = p_trial_ends_at, updated_at = now()
  WHERE tenant_id = resolved_tenant;
  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  VALUES (resolved_tenant, 'operator', btrim(p_actor_id), 'trial_extended',
          'tenant_entitlement', p_runtime_key,
          jsonb_build_object('previous_trial_ends_at', prior_end,
                             'trial_ends_at', p_trial_ends_at));
  RETURN QUERY SELECT p_runtime_key, resolved_state, prior_end, p_trial_ends_at;
END;
$$;

CREATE OR REPLACE FUNCTION admira.operator_expire_trial(
  p_runtime_key text,
  p_actor_id text DEFAULT 'operator-dashboard'
)
RETURNS TABLE (runtime_key text, lifecycle_state text, expired_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid; resolved_state text; now_value timestamptz := clock_timestamp();
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR btrim(coalesce(p_actor_id, '')) = '' OR char_length(btrim(p_actor_id)) > 200 THEN
    RAISE EXCEPTION 'invalid trial expiration' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant FROM admira.tenants AS t
  WHERE t.external_customer_id = btrim(p_runtime_key) AND t.status <> 'deleted'
  FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023'; END IF;
  SELECT e.lifecycle_state INTO resolved_state FROM admira.tenant_entitlements AS e
  WHERE e.tenant_id = resolved_tenant FOR UPDATE;
  IF resolved_state = 'trial_expired' THEN
    -- The database transition already blocks the tenant. Retrying the host
    -- action must still be able to stop a stale container after a transient
    -- Docker failure, so expose a safe idempotent success here.
    RETURN QUERY SELECT p_runtime_key, 'trial_expired'::text, now_value;
    RETURN;
  END IF;
  IF resolved_state <> 'trial' THEN
    RAISE EXCEPTION 'tenant is not an active trial' USING ERRCODE = '55000';
  END IF;
  UPDATE admira.tenant_entitlements
  SET lifecycle_state = 'trial_expired', plan = 'suspended', updated_at = now()
  WHERE tenant_id = resolved_tenant;
  UPDATE admira.tenants SET status = 'suspended', updated_at = now()
  WHERE id = resolved_tenant;
  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  VALUES (resolved_tenant, 'operator', btrim(p_actor_id), 'trial_expired_manually',
          'tenant_entitlement', p_runtime_key, '{}'::jsonb);
  RETURN QUERY SELECT p_runtime_key, 'trial_expired'::text, now_value;
END;
$$;

ALTER FUNCTION admira.operator_create_trial(text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_trial_accounts() OWNER TO admira_control_owner;
ALTER FUNCTION admira.issue_trial_telegram_claim(text, text, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_licensed_accounts() OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_extend_trial(text, timestamptz, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_expire_trial(text, text) OWNER TO admira_control_owner;

REVOKE ALL ON FUNCTION admira.operator_create_trial(text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_trial_accounts() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.issue_trial_telegram_claim(text, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_licensed_accounts() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_extend_trial(text, timestamptz, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_expire_trial(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.operator_create_trial(text, text, text),
  admira.operator_extend_trial(text, timestamptz, text),
  admira.operator_expire_trial(text, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.operator_trial_accounts(),
  admira.operator_licensed_accounts() TO admira_operator;
GRANT EXECUTE ON FUNCTION admira.issue_trial_telegram_claim(text, text, integer)
  TO admira_provisioner;

COMMENT ON FUNCTION admira.operator_create_trial(text, text, text) IS
  'Creates or idempotently activates a hosted trial; its five-day clock starts at tenant creation.';
COMMENT ON FUNCTION admira.operator_trial_accounts() IS
  'Operator-safe trial projection; excludes tenant IDs, Telegram bindings, credentials and recovery data.';
COMMENT ON FUNCTION admira.issue_trial_telegram_claim(text, text, integer) IS
  'Issues or replaces a one-time trial claim without restarting or extending the trial clock; raw token is never stored.';
COMMENT ON FUNCTION admira.operator_licensed_accounts() IS
  'Operator-safe licensed projection; license_mask is redacted and Telegram bindings, credentials and recovery data are excluded.';
COMMENT ON FUNCTION admira.operator_extend_trial(text, timestamptz, text) IS
  'Extends an active trial to a later bounded timestamp; an exact retry is a no-op and records no second audit event.';
COMMENT ON FUNCTION admira.operator_expire_trial(text, text) IS
  'Manually expires an active trial, suspends its tenant and records an audit event.';

COMMIT;
