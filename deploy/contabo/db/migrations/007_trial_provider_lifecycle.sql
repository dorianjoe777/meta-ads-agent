-- Trial/licensed provider lifecycle.  Provider credentials are references to a
-- secret manager only: no API key, bearer token, or other secret is stored in
-- this database.
--
-- This migration is forward-only and idempotent.  The existing `plan` column
-- remains the compatibility field; lifecycle_state is the authoritative,
-- more precise state for routing and provisioning.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:007_trial_provider_lifecycle', 0));

ALTER TABLE admira.tenant_entitlements
  ADD COLUMN IF NOT EXISTS lifecycle_state text NOT NULL DEFAULT 'pending_claim',
  ADD COLUMN IF NOT EXISTS licensed_at timestamptz,
  ADD COLUMN IF NOT EXISTS image_sponsorship_ends_at timestamptz;

ALTER TABLE admira.tenant_entitlements
  DROP CONSTRAINT IF EXISTS tenant_entitlements_lifecycle_state_check;
ALTER TABLE admira.tenant_entitlements
  ADD CONSTRAINT tenant_entitlements_lifecycle_state_check
  CHECK (lifecycle_state IN ('pending_claim', 'trial', 'trial_expired', 'grace', 'licensed', 'suspended', 'cancelled'));

-- Existing rows created by migrations 001-006 retain their plan semantics.
UPDATE admira.tenant_entitlements
SET lifecycle_state = CASE
      WHEN plan = 'paid' THEN 'licensed'
      WHEN plan = 'suspended' THEN 'suspended'
      WHEN plan = 'cancelled' THEN 'cancelled'
      WHEN trial_ends_at IS NOT NULL AND trial_ends_at <= now() THEN 'trial_expired'
      WHEN trial_started_at IS NOT NULL THEN 'trial'
      ELSE 'pending_claim'
    END,
    licensed_at = CASE WHEN plan = 'paid' THEN coalesce(licensed_at, paid_through, updated_at) ELSE licensed_at END
WHERE lifecycle_state = 'pending_claim';

-- A tenant that was already bound before this migration has already started
-- using Admira.  Start its five-day clock at migration time; leaving it in
-- pending_claim would grant an unbounded trial because there is no claim left
-- to consume.  Unbound tenants keep their clock stopped.
UPDATE admira.tenant_entitlements AS e
SET plan = 'trial', lifecycle_state = 'trial',
    trial_started_at = now(), trial_ends_at = now() + interval '5 days',
    updated_at = now()
WHERE e.lifecycle_state = 'pending_claim'
  AND EXISTS (
    SELECT 1 FROM admira.tenant_telegram_bindings AS b
    WHERE b.tenant_id = e.tenant_id
  );

-- Every tenant must have a durable entitlement row, including tenants created
-- before this migration.  New tenants are inserted by the overridden
-- _ensure_hosted_tenant below.
INSERT INTO admira.tenant_entitlements
  (tenant_id, plan, lifecycle_state, trial_started_at, trial_ends_at)
SELECT t.id, 'trial',
       CASE WHEN EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings AS b
                         WHERE b.tenant_id = t.id)
         THEN 'trial' ELSE 'pending_claim' END,
       CASE WHEN EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings AS b
                         WHERE b.tenant_id = t.id)
         THEN now() END,
       CASE WHEN EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings AS b
                         WHERE b.tenant_id = t.id)
         THEN now() + interval '5 days' END
FROM admira.tenants AS t
WHERE NOT EXISTS (
  SELECT 1 FROM admira.tenant_entitlements AS e WHERE e.tenant_id = t.id
);
UPDATE admira.tenants AS t
SET status = 'suspended'
WHERE t.status = 'active'
  AND EXISTS (SELECT 1 FROM admira.tenant_entitlements e
              WHERE e.tenant_id = t.id AND e.lifecycle_state = 'trial_expired');

CREATE INDEX IF NOT EXISTS tenant_entitlements_lifecycle_idx
  ON admira.tenant_entitlements (lifecycle_state, trial_ends_at, paid_through);

CREATE TABLE IF NOT EXISTS admira.tenant_provider_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('gemini', 'chatgpt')),
  secret_ref text NOT NULL,
  fingerprint text NOT NULL,
  origin text NOT NULL CHECK (origin IN ('operator_pool', 'customer', 'central_broker')),
  purpose text NOT NULL CHECK (purpose IN ('text', 'image', 'general')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'retired')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE admira.tenant_provider_credentials
  DROP CONSTRAINT IF EXISTS tenant_provider_credentials_secret_ref_check,
  DROP CONSTRAINT IF EXISTS tenant_provider_credentials_fingerprint_check;
ALTER TABLE admira.tenant_provider_credentials
  ADD CONSTRAINT tenant_provider_credentials_secret_ref_check
    CHECK (char_length(secret_ref) BETWEEN 8 AND 512
           AND secret_ref ~ '^[A-Za-z][A-Za-z0-9+.-]*://'
           AND secret_ref !~ '[[:space:][:cntrl:]]'),
  ADD CONSTRAINT tenant_provider_credentials_fingerprint_check
    CHECK (fingerprint ~ '^[a-f0-9]{64}$');

-- Retired metadata is append-only history; only one active credential can
-- exist for a tenant/provider/purpose.
DROP INDEX IF EXISTS admira.tenant_provider_credentials_active_uq;
CREATE UNIQUE INDEX IF NOT EXISTS tenant_provider_credentials_active_uq
  ON admira.tenant_provider_credentials (tenant_id, provider, purpose)
  WHERE status = 'active';
DO $$
DECLARE c record;
BEGIN
  -- Remove only the obsolete four-column uniqueness from an earlier draft.
  -- Replaying this migration after a future release must never drop unrelated
  -- unique constraints that a later migration may add.
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'admira.tenant_provider_credentials'::regclass
             AND contype = 'u'
             AND pg_get_constraintdef(oid)
                 LIKE 'UNIQUE (tenant_id, provider, purpose, status)%'
  LOOP
    EXECUTE format('ALTER TABLE admira.tenant_provider_credentials DROP CONSTRAINT %I', c.conname);
  END LOOP;
END;
$$;
ALTER TABLE admira.tenant_provider_credentials
  DROP CONSTRAINT IF EXISTS tenant_provider_credentials_origin_check;
UPDATE admira.tenant_provider_credentials SET origin = 'operator_pool' WHERE origin = 'platform';
ALTER TABLE admira.tenant_provider_credentials
  ADD CONSTRAINT tenant_provider_credentials_origin_check
  CHECK (origin IN ('operator_pool', 'customer', 'central_broker'));

CREATE INDEX IF NOT EXISTS tenant_provider_credentials_route_idx
  ON admira.tenant_provider_credentials (tenant_id, provider, purpose, status);

ALTER TABLE admira.tenant_provider_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_provider_credentials FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_provider_credentials;
CREATE POLICY tenant_isolation ON admira.tenant_provider_credentials
  USING (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

DROP TRIGGER IF EXISTS tenant_provider_credentials_touch_updated_at ON admira.tenant_provider_credentials;
CREATE TRIGGER tenant_provider_credentials_touch_updated_at
  BEFORE UPDATE ON admira.tenant_provider_credentials
  FOR EACH ROW EXECUTE FUNCTION admira.touch_updated_at();

COMMENT ON TABLE admira.tenant_provider_credentials IS
  'Secret-manager metadata only. secret_ref identifies an external secret; raw provider credentials are forbidden here.';
COMMENT ON COLUMN admira.tenant_provider_credentials.secret_ref IS
  'Opaque reference resolved by the runtime secret provider; never the provider secret itself.';
GRANT SELECT, INSERT, UPDATE, DELETE ON admira.tenant_provider_credentials
  TO admira_control_owner;

CREATE OR REPLACE FUNCTION admira._start_trial_once(p_tenant_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer := 0;
BEGIN
  IF p_tenant_id IS NULL THEN RETURN false; END IF;
  INSERT INTO admira.tenant_entitlements
    (tenant_id, plan, lifecycle_state, trial_started_at, trial_ends_at)
  VALUES (p_tenant_id, 'trial', 'trial', now(), now() + interval '5 days')
  ON CONFLICT (tenant_id) DO NOTHING;
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed > 0 THEN RETURN true; END IF;
  UPDATE admira.tenant_entitlements
  SET plan = 'trial', lifecycle_state = 'trial',
      trial_started_at = now(), trial_ends_at = now() + interval '5 days',
      updated_at = now()
  WHERE tenant_id = p_tenant_id AND lifecycle_state = 'pending_claim';
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed > 0;
END;
$$;

-- Extend hosted creation so every new tenant receives an entitlement row while
-- keeping the five-day clock stopped until the first claim/registration.
CREATE OR REPLACE FUNCTION admira._ensure_hosted_tenant(p_runtime_key text, p_display_name text)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid; existing_runtime text; existing_status text;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR btrim(coalesce(p_display_name, '')) = ''
     OR char_length(btrim(p_display_name)) > 200 THEN
    RAISE EXCEPTION 'invalid hosted tenant registration' USING ERRCODE = '22023';
  END IF;
  SELECT t.id, t.status INTO resolved_tenant, existing_status FROM admira.tenants AS t
  WHERE t.external_customer_id = p_runtime_key FOR UPDATE;
  IF resolved_tenant IS NULL THEN
    INSERT INTO admira.tenants (external_customer_id, display_name, status)
    VALUES (p_runtime_key, btrim(p_display_name), 'active') RETURNING id INTO resolved_tenant;
  ELSE
    IF existing_status = 'deleted' THEN
      RAISE EXCEPTION 'deleted tenant cannot be reactivated' USING ERRCODE = '55000';
    END IF;
    IF existing_status <> 'active' THEN
      RAISE EXCEPTION 'suspended tenant requires an explicit lifecycle transition' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
      SELECT 1 FROM admira.tenant_entitlements AS e
      WHERE e.tenant_id = resolved_tenant AND e.lifecycle_state <> 'pending_claim'
    ) THEN
      RAISE EXCEPTION 'tenant has already been activated' USING ERRCODE = '55000';
    END IF;
    UPDATE admira.tenants SET display_name = btrim(p_display_name)
    WHERE id = resolved_tenant;
  END IF;
  SELECT l.runtime_key INTO existing_runtime FROM admira.tenant_runtime_leases AS l
  WHERE l.tenant_id = resolved_tenant FOR UPDATE;
  IF existing_runtime IS NOT NULL AND existing_runtime <> p_runtime_key THEN
    RAISE EXCEPTION 'tenant runtime key mismatch' USING ERRCODE = '23505';
  END IF;
  IF EXISTS (SELECT 1 FROM admira.tenant_runtime_leases AS l
             WHERE l.runtime_key = p_runtime_key AND l.tenant_id <> resolved_tenant) THEN
    RAISE EXCEPTION 'runtime key already belongs to another tenant' USING ERRCODE = '23505';
  END IF;
  INSERT INTO admira.tenant_runtime_leases (tenant_id, runtime_key, state)
  VALUES (resolved_tenant, p_runtime_key, 'stopped') ON CONFLICT (tenant_id) DO NOTHING;
  INSERT INTO admira.tenant_entitlements (tenant_id, plan, lifecycle_state)
  VALUES (resolved_tenant, 'trial', 'pending_claim') ON CONFLICT (tenant_id) DO NOTHING;
  RETURN resolved_tenant;
END;
$$;

CREATE OR REPLACE FUNCTION admira.register_hosted_tenant(
  p_runtime_key text, p_display_name text, p_bot_id text, p_chat_id text, p_user_id text
)
RETURNS TABLE (tenant_id uuid, runtime_key text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid; conflicting_tenant uuid;
BEGIN
  IF coalesce(p_bot_id, '') !~ '^[0-9]{1,32}$'
     OR coalesce(p_chat_id, '') !~ '^-?[0-9]{1,32}$'
     OR coalesce(p_user_id, '') !~ '^[0-9]{1,32}$' THEN
    RAISE EXCEPTION 'invalid telegram binding' USING ERRCODE = '22023';
  END IF;
  resolved_tenant := admira._ensure_hosted_tenant(p_runtime_key, p_display_name);
  SELECT b.tenant_id INTO conflicting_tenant FROM admira.tenant_telegram_bindings AS b
  WHERE b.bot_id = p_bot_id AND b.telegram_chat_id = p_chat_id FOR UPDATE;
  IF conflicting_tenant IS NOT NULL AND conflicting_tenant <> resolved_tenant THEN
    RAISE EXCEPTION 'telegram chat already belongs to another tenant' USING ERRCODE = '23505';
  END IF;
  INSERT INTO admira.tenant_telegram_bindings
    (tenant_id, telegram_user_id, telegram_chat_id, bot_id, is_primary)
  VALUES (resolved_tenant, p_user_id, p_chat_id, p_bot_id, true)
  ON CONFLICT (bot_id, telegram_chat_id) DO UPDATE
    SET telegram_user_id = EXCLUDED.telegram_user_id, is_primary = true, updated_at = now();
  PERFORM admira._start_trial_once(resolved_tenant);
  RETURN QUERY SELECT resolved_tenant, p_runtime_key;
END;
$$;

-- Idempotent claim consumption: a replayed Telegram claim can never restart
-- or extend an existing trial.
CREATE OR REPLACE FUNCTION admira.claim_telegram_tenant(
  p_bot_id text, p_chat_id text, p_user_id text, p_raw_token text
)
RETURNS TABLE (tenant_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE claim admira.tenant_telegram_claims%ROWTYPE; conflicting_tenant uuid;
BEGIN
  IF coalesce(p_bot_id, '') !~ '^[0-9]{1,32}$'
     OR coalesce(p_chat_id, '') !~ '^-?[0-9]{1,32}$'
     OR coalesce(p_user_id, '') !~ '^[0-9]{1,32}$'
     OR coalesce(p_raw_token, '') !~ '^[A-Za-z0-9_-]{20,128}$' THEN RETURN; END IF;
  SELECT c.* INTO claim FROM admira.tenant_telegram_claims AS c
  JOIN admira.tenants AS t ON t.id = c.tenant_id
  WHERE c.token_hash = public.digest(convert_to(p_raw_token, 'UTF8'), 'sha256')
    AND c.used_at IS NULL AND c.expires_at > now() AND t.status = 'active'
  FOR UPDATE OF c;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT b.tenant_id INTO conflicting_tenant FROM admira.tenant_telegram_bindings AS b
  WHERE b.bot_id = p_bot_id AND b.telegram_chat_id = p_chat_id FOR UPDATE;
  IF conflicting_tenant IS NOT NULL AND conflicting_tenant <> claim.tenant_id THEN RETURN; END IF;
  IF EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings AS b
             WHERE b.tenant_id = claim.tenant_id
               AND (b.bot_id <> p_bot_id OR b.telegram_chat_id <> p_chat_id)) THEN RETURN; END IF;
  INSERT INTO admira.tenant_telegram_bindings
    (tenant_id, telegram_user_id, telegram_chat_id, bot_id, is_primary)
  VALUES (claim.tenant_id, p_user_id, p_chat_id, p_bot_id, true)
  ON CONFLICT (bot_id, telegram_chat_id) DO UPDATE
    SET telegram_user_id = EXCLUDED.telegram_user_id, is_primary = true, updated_at = now();
  UPDATE admira.tenant_telegram_claims SET used_at = now() WHERE id = claim.id;
  PERFORM admira._start_trial_once(claim.tenant_id);
  INSERT INTO admira.tenant_telegram_outbox
    (tenant_id, bot_id, telegram_chat_id, sequence_no, kind, body)
  VALUES (claim.tenant_id, p_bot_id, p_chat_id, 0, 'text',
          '✅ Tu espacio privado de Admira IA quedó conectado. Escríbeme hola para comenzar.');
  RETURN QUERY SELECT claim.tenant_id;
END;
$$;

-- Store only a secret-manager reference and a one-way fingerprint. Repeating
-- the same metadata is a no-op; a new key retires the old active version.
CREATE OR REPLACE FUNCTION admira.record_tenant_provider_credential(
  p_tenant_id uuid, p_provider text, p_purpose text, p_secret_ref text,
  p_fingerprint text, p_origin text DEFAULT 'customer'
)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
BEGIN
  IF p_tenant_id IS NULL OR p_provider NOT IN ('gemini', 'chatgpt')
     OR p_purpose NOT IN ('text', 'image', 'general')
     OR p_origin NOT IN ('operator_pool', 'customer', 'central_broker')
     OR char_length(coalesce(p_secret_ref, '')) NOT BETWEEN 8 AND 512
     OR coalesce(p_secret_ref, '') !~ '^[A-Za-z][A-Za-z0-9+.-]*://'
     OR coalesce(p_secret_ref, '') ~ '[[:space:][:cntrl:]]'
     OR coalesce(p_fingerprint, '') !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'invalid provider credential metadata' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenants WHERE id = p_tenant_id) THEN
    RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (SELECT 1 FROM admira.tenant_provider_credentials
             WHERE tenant_id = p_tenant_id AND provider = p_provider AND purpose = p_purpose
               AND status = 'active' AND secret_ref = p_secret_ref
               AND fingerprint = p_fingerprint AND origin = p_origin) THEN
    RETURN false;
  END IF;
  UPDATE admira.tenant_provider_credentials SET status = 'retired', updated_at = now()
  WHERE tenant_id = p_tenant_id AND provider = p_provider AND purpose = p_purpose AND status = 'active';
  INSERT INTO admira.tenant_provider_credentials
    (tenant_id, provider, purpose, secret_ref, fingerprint, origin, status)
  VALUES (p_tenant_id, p_provider, p_purpose, p_secret_ref, p_fingerprint, p_origin, 'active');
  RETURN true;
END;
$$;

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
           WHEN e.lifecycle_state = 'licensed'
             THEN 'personal_chatgpt'
           ELSE 'blocked'
         END,
         e.image_sponsorship_ends_at, e.trial_ends_at
  FROM admira.tenant_entitlements e
  JOIN admira.tenants t ON t.id = e.tenant_id
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
        -- Buying never restarts the sponsored-image clock.  The default benefit
        -- is the same five-day period that started with the initial claim; an
        -- explicit operator extension, if already present, is preserved.
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

CREATE OR REPLACE FUNCTION admira.transition_hosted_tenant_to_licensed(
  p_runtime_key text, p_license_id text, p_gemini_secret_ref text,
  p_gemini_fingerprint text, p_actor_id text DEFAULT 'control-plane'
)
RETURNS TABLE (
  tenant_id uuid, lifecycle_state text, licensed_at timestamptz,
  image_sponsorship_ends_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$' THEN
    RAISE EXCEPTION 'invalid hosted tenant' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant FROM admira.tenants AS t
  WHERE t.external_customer_id = p_runtime_key FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT transition.tenant_id, transition.lifecycle_state,
         transition.licensed_at, transition.image_sponsorship_ends_at
  FROM admira.transition_tenant_to_licensed(
    resolved_tenant, p_license_id, p_gemini_secret_ref,
    p_gemini_fingerprint, p_actor_id
  ) AS transition;
END;
$$;

CREATE OR REPLACE FUNCTION admira.expire_due_trials()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  WITH expired AS (
    UPDATE admira.tenant_entitlements
    SET lifecycle_state = 'trial_expired', plan = 'suspended', updated_at = now()
    WHERE lifecycle_state = 'trial' AND trial_ends_at IS NOT NULL AND trial_ends_at <= now()
    RETURNING tenant_id
  ), suspended AS (
    UPDATE admira.tenants t SET status = 'suspended', updated_at = now()
    WHERE t.id IN (SELECT tenant_id FROM expired) AND t.status = 'active'
    RETURNING t.id
  )
  SELECT count(*)::integer INTO changed FROM expired;
  RETURN changed;
END;
$$;

REVOKE ALL ON TABLE admira.tenant_provider_credentials FROM PUBLIC, admira_ingress, admira_runtime, admira_delivery, admira_scheduler, admira_provisioner;
GRANT USAGE ON SCHEMA admira TO admira_runtime, admira_provisioner;
REVOKE ALL ON FUNCTION admira._start_trial_once(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira._ensure_hosted_tenant(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.register_hosted_tenant(text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_telegram_tenant(text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.resolve_tenant_image_access(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.transition_tenant_to_licensed(uuid, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.transition_hosted_tenant_to_licensed(text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.expire_due_trials() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.record_tenant_provider_credential(uuid, text, text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.claim_telegram_tenant(text, text, text, text) TO admira_ingress;
GRANT EXECUTE ON FUNCTION admira.register_hosted_tenant(text, text, text, text, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.resolve_tenant_image_access(uuid) TO admira_runtime;
GRANT EXECUTE ON FUNCTION admira.transition_tenant_to_licensed(uuid, text, text, text, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.transition_hosted_tenant_to_licensed(text, text, text, text, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.expire_due_trials() TO admira_runtime, admira_scheduler;
GRANT EXECUTE ON FUNCTION admira.record_tenant_provider_credential(uuid, text, text, text, text, text) TO admira_provisioner;
ALTER FUNCTION admira._start_trial_once(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira._ensure_hosted_tenant(text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.register_hosted_tenant(text, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_telegram_tenant(text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.resolve_tenant_image_access(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.transition_tenant_to_licensed(uuid, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.transition_hosted_tenant_to_licensed(text, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.expire_due_trials() OWNER TO admira_control_owner;
ALTER FUNCTION admira.record_tenant_provider_credential(uuid, text, text, text, text, text) OWNER TO admira_control_owner;

COMMIT;
