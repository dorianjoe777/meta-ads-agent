-- Separate tenant-local ChatGPT authentication from Admira-sponsored image
-- access.  The normal sponsored period is the original five-day trial clock;
-- licensing never restarts it.  A private operator may extend only the exact
-- sponsorship end for one active tenant through narrow, audited functions.
BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:012_personal_chatgpt_sponsorship', 0));

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
  SELECT e.lifecycle_state,
         CASE
           WHEN t.status <> 'active' THEN 'blocked'
           WHEN e.lifecycle_state = 'trial'
                AND e.trial_ends_at > now()
                AND coalesce(e.image_sponsorship_ends_at, e.trial_ends_at) > now()
             THEN 'central_sponsored'
           WHEN e.lifecycle_state = 'licensed'
                AND coalesce(e.image_sponsorship_ends_at, e.trial_ends_at) > now()
             THEN 'central_sponsored'
           WHEN e.lifecycle_state = 'licensed' THEN 'personal_chatgpt'
           ELSE 'blocked'
         END,
         e.image_sponsorship_ends_at, e.trial_ends_at
  FROM admira.tenant_entitlements AS e
  JOIN admira.tenants AS t ON t.id = e.tenant_id
  WHERE e.tenant_id = p_tenant_id
$$;

CREATE OR REPLACE FUNCTION admira.transition_tenant_to_licensed(
  p_tenant_id uuid, p_license_id text, p_gemini_secret_ref text,
  p_gemini_fingerprint text, p_actor_id text DEFAULT 'control-plane'
)
RETURNS TABLE (tenant_id uuid, lifecycle_state text, licensed_at timestamptz, image_sponsorship_ends_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE now_value timestamptz := now(); result_state text; existing_license text; tenant_status text;
BEGIN
  IF p_tenant_id IS NULL
     OR coalesce(p_license_id, '') !~ '^[A-Za-z0-9][A-Za-z0-9_-]{7,127}$'
     OR char_length(coalesce(p_gemini_secret_ref, '')) NOT BETWEEN 8 AND 512
     OR coalesce(p_gemini_secret_ref, '') !~ '^[A-Za-z][A-Za-z0-9+.-]*://'
     OR coalesce(p_gemini_secret_ref, '') ~ '[[:space:][:cntrl:]]'
     OR coalesce(p_gemini_fingerprint, '') !~ '^[a-f0-9]{64}$'
     OR btrim(coalesce(p_actor_id, '')) = '' OR char_length(p_actor_id) > 200 THEN
    RAISE EXCEPTION 'invalid license transition' USING ERRCODE = '22023';
  END IF;
  SELECT status INTO tenant_status FROM admira.tenants WHERE id = p_tenant_id FOR UPDATE;
  IF NOT FOUND OR tenant_status = 'deleted' THEN
    RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023';
  END IF;
  INSERT INTO admira.tenant_entitlements (tenant_id) VALUES (p_tenant_id)
    ON CONFLICT ON CONSTRAINT tenant_entitlements_pkey DO NOTHING;
  SELECT e.license_id INTO existing_license FROM admira.tenant_entitlements AS e
  WHERE e.tenant_id = p_tenant_id FOR UPDATE;
  IF existing_license IS NOT NULL AND existing_license <> p_license_id THEN
    RAISE EXCEPTION 'tenant already has a different license' USING ERRCODE = '23505';
  END IF;
  UPDATE admira.tenant_entitlements AS e
  SET plan = 'paid', license_id = btrim(p_license_id), lifecycle_state = 'licensed',
      licensed_at = coalesce(e.licensed_at, now_value),
      paid_through = greatest(coalesce(e.paid_through, now_value), now_value),
      image_sponsorship_ends_at = CASE WHEN e.licensed_at IS NULL
        THEN coalesce(e.image_sponsorship_ends_at, e.trial_ends_at, now_value)
        ELSE e.image_sponsorship_ends_at END,
      updated_at = now_value
  WHERE e.tenant_id = p_tenant_id
  RETURNING e.lifecycle_state INTO result_state;
  IF NOT FOUND THEN RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023'; END IF;
  UPDATE admira.tenants SET status = 'active' WHERE id = p_tenant_id AND status = 'suspended';
  PERFORM admira.record_tenant_provider_credential(
    p_tenant_id, 'gemini', 'text', p_gemini_secret_ref,
    p_gemini_fingerprint, 'customer'
  );
  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  SELECT p_tenant_id, 'operator', p_actor_id, 'tenant_licensed', 'tenant_entitlement', p_tenant_id::text,
          jsonb_build_object('image_sponsorship_ends_at',
            (SELECT e.image_sponsorship_ends_at FROM admira.tenant_entitlements AS e
             WHERE e.tenant_id = p_tenant_id))
  WHERE NOT EXISTS (SELECT 1 FROM admira.tenant_audit_events
                    WHERE admira.tenant_audit_events.tenant_id = p_tenant_id
                      AND event_type = 'tenant_licensed');
  RETURN QUERY SELECT p_tenant_id, result_state,
    (SELECT e.licensed_at FROM admira.tenant_entitlements AS e WHERE e.tenant_id = p_tenant_id),
    (SELECT e.image_sponsorship_ends_at FROM admira.tenant_entitlements AS e WHERE e.tenant_id = p_tenant_id);
END;
$$;

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
  SELECT l.runtime_key, left(t.display_name, 200), e.lifecycle_state,
         e.trial_ends_at, e.image_sponsorship_ends_at,
         coalesce(e.image_sponsorship_ends_at, e.trial_ends_at), access.route
  FROM admira.tenants AS t
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
  LEFT JOIN LATERAL admira.resolve_tenant_image_access(t.id) AS access ON true
  WHERE t.status <> 'deleted'
  ORDER BY t.created_at DESC, l.runtime_key
  LIMIT 1000
$$;

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
  prior_end timestamptz;
  changed integer := 0;
  resolved_route text;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_ends_at IS NULL OR p_ends_at <= now_value
     OR p_ends_at > now_value + interval '365 days' THEN
    RAISE EXCEPTION 'invalid sponsorship extension' USING ERRCODE = '22023';
  END IF;

  SELECT t.id, t.status INTO resolved_tenant, tenant_status
  FROM admira.tenants AS t
  WHERE t.external_customer_id = p_runtime_key
  FOR UPDATE;
  IF NOT FOUND OR tenant_status <> 'active' THEN
    RAISE EXCEPTION 'tenant is not active' USING ERRCODE = '55000';
  END IF;

  SELECT e.lifecycle_state, coalesce(e.image_sponsorship_ends_at, e.trial_ends_at)
  INTO resolved_state, prior_end
  FROM admira.tenant_entitlements AS e
  WHERE e.tenant_id = resolved_tenant
  FOR UPDATE;
  IF NOT FOUND OR resolved_state NOT IN ('trial', 'licensed') THEN
    RAISE EXCEPTION 'tenant is not eligible for sponsorship' USING ERRCODE = '55000';
  END IF;
  IF prior_end IS NOT NULL AND p_ends_at < prior_end THEN
    RAISE EXCEPTION 'sponsorship cannot be shortened' USING ERRCODE = '22023';
  END IF;

  UPDATE admira.tenant_entitlements AS e
  SET image_sponsorship_ends_at = p_ends_at, updated_at = now_value
  WHERE e.tenant_id = resolved_tenant
    AND (prior_end IS NULL OR p_ends_at > prior_end)
    AND e.image_sponsorship_ends_at IS DISTINCT FROM p_ends_at;
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
      (SELECT e.image_sponsorship_ends_at FROM admira.tenant_entitlements AS e
       WHERE e.tenant_id = resolved_tenant),
      prior_end
    ), resolved_route;
END;
$$;

ALTER FUNCTION admira.resolve_tenant_image_access(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.transition_tenant_to_licensed(uuid, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_tenant_sponsorship_status() OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_set_image_sponsorship_end(text, timestamptz) OWNER TO admira_control_owner;

REVOKE ALL ON FUNCTION admira.resolve_tenant_image_access(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.transition_tenant_to_licensed(uuid, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_tenant_sponsorship_status() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.operator_set_image_sponsorship_end(text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.resolve_tenant_image_access(uuid) TO admira_runtime;
GRANT EXECUTE ON FUNCTION admira.transition_tenant_to_licensed(uuid, text, text, text, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.operator_tenant_sponsorship_status(),
  admira.operator_set_image_sponsorship_end(text, timestamptz)
  TO admira_operator;

COMMENT ON FUNCTION admira.operator_tenant_sponsorship_status() IS
  'Private operator projection for image sponsorship; excludes credentials, license IDs and recovery contacts.';
COMMENT ON FUNCTION admira.operator_set_image_sponsorship_end(text, timestamptz) IS
  'Idempotently extends one active tenant image-sponsorship end; never shortens it and writes an audit event.';

COMMIT;
