-- Licensed-tenant recovery from a new Telegram identity.
--
-- The application normalizes email and computes both HMACs.  PostgreSQL never
-- receives a raw email, license, OTP, or provider credential.  The delivery
-- payload is an application-encrypted envelope and delivery_ref is opaque.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:009_telegram_license_recovery', 0));
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS admira.tenant_license_contacts (
  tenant_id uuid PRIMARY KEY REFERENCES admira.tenants(id) ON DELETE CASCADE,
  email_hmac bytea NOT NULL CHECK (octet_length(email_hmac) = 32),
  license_hmac bytea NOT NULL CHECK (octet_length(license_hmac) = 32),
  delivery_ref text NOT NULL CHECK (
    char_length(delivery_ref) BETWEEN 8 AND 512
    AND delivery_ref ~ '^[A-Za-z][A-Za-z0-9+.-]*://'
    AND delivery_ref !~ '[[:space:][:cntrl:]]'
  ),
  verified_at timestamptz NOT NULL,
  identity_version bigint NOT NULL DEFAULT 1 CHECK (identity_version > 0),
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS tenant_license_contacts_active_license_uq
  ON admira.tenant_license_contacts(license_hmac) WHERE revoked_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS tenant_license_contacts_active_email_license_uq
  ON admira.tenant_license_contacts(email_hmac, license_hmac) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS admira.tenant_telegram_binding_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  old_binding_id uuid,
  old_bot_id text,
  old_chat_id text,
  old_user_id text,
  new_binding_id uuid,
  new_bot_id text NOT NULL,
  new_chat_id text NOT NULL,
  new_user_id text NOT NULL,
  reason text NOT NULL CHECK (reason IN ('recovery_rebind', 'operator_revoke')),
  actor_id text NOT NULL CHECK (char_length(actor_id) BETWEEN 1 AND 200),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (old_binding_id IS NOT NULL OR reason = 'recovery_rebind')
);

CREATE INDEX IF NOT EXISTS tenant_telegram_binding_history_tenant_idx
  ON admira.tenant_telegram_binding_history(tenant_id, created_at DESC);

CREATE OR REPLACE FUNCTION admira.prevent_recovery_history_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'recovery binding history is immutable' USING ERRCODE = '55000';
END;
$$;
DROP TRIGGER IF EXISTS tenant_telegram_binding_history_immutable
  ON admira.tenant_telegram_binding_history;
CREATE TRIGGER tenant_telegram_binding_history_immutable
  BEFORE UPDATE OR DELETE ON admira.tenant_telegram_binding_history
  FOR EACH ROW EXECUTE FUNCTION admira.prevent_recovery_history_mutation();

CREATE TABLE IF NOT EXISTS admira.tenant_recovery_rate_limits (
  scope text NOT NULL CHECK (scope IN ('chat', 'email', 'license')),
  subject_hash bytea NOT NULL CHECK (octet_length(subject_hash) = 32),
  window_started_at timestamptz NOT NULL,
  request_count integer NOT NULL DEFAULT 0 CHECK (request_count >= 0),
  blocked_until timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope, subject_hash)
);
ALTER TABLE admira.tenant_recovery_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_recovery_rate_limits FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS recovery_owner_only ON admira.tenant_recovery_rate_limits;
CREATE POLICY recovery_owner_only ON admira.tenant_recovery_rate_limits
  USING (false) WITH CHECK (false);

CREATE TABLE IF NOT EXISTS admira.tenant_recovery_challenges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL UNIQUE,
  tenant_id uuid REFERENCES admira.tenants(id) ON DELETE CASCADE,
  requester_bot_id text NOT NULL CHECK (btrim(requester_bot_id) <> ''),
  requester_chat_id text NOT NULL CHECK (btrim(requester_chat_id) <> ''),
  requester_user_id text NOT NULL CHECK (btrim(requester_user_id) <> ''),
  email_hmac bytea NOT NULL CHECK (octet_length(email_hmac) = 32),
  license_hmac bytea NOT NULL CHECK (octet_length(license_hmac) = 32),
  contact_identity_version bigint,
  otp_hash bytea NOT NULL CHECK (octet_length(otp_hash) = 32),
  otp_ciphertext bytea,
  delivery_key_version text,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'consumed', 'expired', 'locked', 'invalidated')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10),
  cooldown_until timestamptz,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  invalidated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > created_at),
  CHECK (otp_ciphertext IS NULL OR octet_length(otp_ciphertext) BETWEEN 32 AND 8192),
  CHECK ((otp_ciphertext IS NULL AND delivery_key_version IS NULL)
      OR (otp_ciphertext IS NOT NULL AND delivery_key_version IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS tenant_recovery_challenges_lookup_idx
  ON admira.tenant_recovery_challenges(email_hmac, license_hmac, created_at DESC);
CREATE INDEX IF NOT EXISTS tenant_recovery_challenges_tenant_idx
  ON admira.tenant_recovery_challenges(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS admira.tenant_recovery_delivery_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  challenge_id uuid NOT NULL UNIQUE
    REFERENCES admira.tenant_recovery_challenges(id) ON DELETE CASCADE,
  delivery_ref text NOT NULL CHECK (
    char_length(delivery_ref) BETWEEN 8 AND 512
    AND delivery_ref ~ '^[A-Za-z][A-Za-z0-9+.-]*://'
    AND delivery_ref !~ '[[:space:][:cntrl:]]'
  ),
  template_code text NOT NULL CHECK (template_code = 'telegram_recovery_otp'),
  encrypted_payload bytea NOT NULL CHECK (octet_length(encrypted_payload) BETWEEN 32 AND 8192),
  delivery_key_version text NOT NULL CHECK (char_length(delivery_key_version) BETWEEN 1 AND 128),
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'sending', 'sent', 'retry', 'failed', 'dead')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  leased_until timestamptz,
  last_error_code text CHECK (last_error_code IS NULL OR last_error_code IN (
    'provider_unavailable', 'provider_rejected', 'timeout', 'internal_error')),
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);

CREATE INDEX IF NOT EXISTS tenant_recovery_delivery_claim_idx
  ON admira.tenant_recovery_delivery_outbox(status, available_at, created_at);

-- Unbound Telegram chats cannot use tenant_telegram_outbox because that table
-- deliberately requires a tenant FK.  This separate queue carries only fixed
-- templates and public Telegram routing fields.
CREATE TABLE IF NOT EXISTS admira.telegram_recovery_chat_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Deliberately no tenant/challenge FK: a structurally valid unknown or
  -- malformed confirmation must still receive the same safe failure reply.
  request_id uuid NOT NULL,
  bot_id text NOT NULL CHECK (btrim(bot_id) <> ''),
  chat_id text NOT NULL CHECK (btrim(chat_id) <> ''),
  user_id text NOT NULL CHECK (btrim(user_id) <> ''),
  template_code text NOT NULL CHECK (template_code IN (
    'recovery_instructions', 'recovery_pending',
    'recovery_completed', 'recovery_failed')),
  body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'sending', 'sent', 'retry', 'failed', 'dead')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  leased_until timestamptz,
  last_error_code text CHECK (last_error_code IS NULL OR last_error_code IN (
    'telegram_unavailable', 'telegram_rate_limited', 'timeout', 'internal_error')),
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  UNIQUE (request_id, template_code)
);
CREATE INDEX IF NOT EXISTS telegram_recovery_chat_outbox_claim_idx
  ON admira.telegram_recovery_chat_outbox(status, available_at, created_at);
ALTER TABLE admira.telegram_recovery_chat_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.telegram_recovery_chat_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS recovery_owner_only ON admira.telegram_recovery_chat_outbox;
CREATE POLICY recovery_owner_only ON admira.telegram_recovery_chat_outbox
  USING (false) WITH CHECK (false);

CREATE TABLE IF NOT EXISTS admira.tenant_recovery_audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL,
  tenant_id uuid REFERENCES admira.tenants(id) ON DELETE SET NULL,
  bot_id text NOT NULL,
  chat_id text NOT NULL,
  user_id text NOT NULL,
  email_hmac bytea NOT NULL CHECK (octet_length(email_hmac) = 32),
  license_hmac bytea NOT NULL CHECK (octet_length(license_hmac) = 32),
  event_type text NOT NULL CHECK (event_type IN (
    'requested', 'delivery_queued', 'otp_failed', 'otp_locked',
    'otp_expired', 'rebind_succeeded', 'rebind_rejected', 'rate_limited',
    'contact_registered', 'contact_revoked')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tenant_recovery_audit_request_idx
  ON admira.tenant_recovery_audit_events(request_id, created_at);

ALTER TABLE admira.tenant_license_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_license_contacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_license_contacts;
CREATE POLICY tenant_isolation ON admira.tenant_license_contacts
  USING (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

ALTER TABLE admira.tenant_telegram_binding_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_telegram_binding_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_telegram_binding_history;
CREATE POLICY tenant_isolation ON admira.tenant_telegram_binding_history
  USING (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

ALTER TABLE admira.tenant_recovery_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_recovery_challenges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_recovery_challenges;
CREATE POLICY tenant_isolation ON admira.tenant_recovery_challenges
  USING (tenant_id IS NOT NULL AND tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id IS NOT NULL AND tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

ALTER TABLE admira.tenant_recovery_delivery_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_recovery_delivery_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_recovery_delivery_outbox;
CREATE POLICY tenant_isolation ON admira.tenant_recovery_delivery_outbox
  USING (EXISTS (SELECT 1 FROM admira.tenant_recovery_challenges c
                 WHERE c.id = challenge_id
                   AND c.tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), '')))
  WITH CHECK (EXISTS (SELECT 1 FROM admira.tenant_recovery_challenges c
                      WHERE c.id = challenge_id
                        AND c.tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), '')));

ALTER TABLE admira.tenant_recovery_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_recovery_audit_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_recovery_audit_events;
CREATE POLICY tenant_isolation ON admira.tenant_recovery_audit_events
  USING (tenant_id IS NOT NULL AND tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id IS NOT NULL AND tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

CREATE OR REPLACE FUNCTION admira._recovery_audit(
  p_request_id uuid, p_tenant_id uuid, p_bot_id text, p_chat_id text,
  p_user_id text, p_email_hmac bytea, p_license_hmac bytea,
  p_event_type text, p_metadata jsonb DEFAULT '{}'::jsonb
)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
BEGIN
  INSERT INTO admira.tenant_recovery_audit_events
    (request_id, tenant_id, bot_id, chat_id, user_id, email_hmac, license_hmac, event_type, metadata)
  VALUES (p_request_id, p_tenant_id, btrim(p_bot_id), btrim(p_chat_id), btrim(p_user_id),
          p_email_hmac, p_license_hmac, p_event_type, coalesce(p_metadata, '{}'::jsonb));
END;
$$;

CREATE OR REPLACE FUNCTION admira._enqueue_recovery_chat_reply(
  p_request_id uuid, p_bot_id text, p_chat_id text, p_user_id text,
  p_template_code text
)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE reply text;
BEGIN
  IF p_template_code = 'recovery_instructions' THEN
    reply := 'Para recuperar tu espacio, envía en este chat privado: /recuperar correo@ejemplo.com TU_LICENCIA. Recibirás por correo un comando /codigo de un solo uso.';
  ELSIF p_template_code = 'recovery_pending' THEN
    reply := 'Si los datos coinciden, recibirás instrucciones en el correo registrado.';
  ELSIF p_template_code = 'recovery_completed' THEN
    reply := '✅ Tu espacio de Admira IA fue recuperado. Puedes continuar donde quedaste.';
  ELSE
    reply := 'No pudimos completar la recuperación. Solicita un código nuevo e inténtalo de nuevo.';
  END IF;
  INSERT INTO admira.telegram_recovery_chat_outbox
    (request_id, bot_id, chat_id, user_id, template_code, body)
  VALUES (p_request_id, btrim(p_bot_id), btrim(p_chat_id), btrim(p_user_id), p_template_code, reply)
  ON CONFLICT (request_id, template_code) DO NOTHING;
END;
$$;

-- Public replies for malformed/incomplete commands are also durable.  This
-- wrapper deliberately permits only instructions or the generic failure; the
-- recovery role cannot forge a successful rebind notification.
CREATE OR REPLACE FUNCTION admira.enqueue_telegram_recovery_public_reply(
  p_request_id uuid, p_bot_id text, p_chat_id text, p_user_id text,
  p_template_code text
)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
BEGIN
  IF p_request_id IS NULL OR btrim(coalesce(p_bot_id, '')) !~ '^[0-9]{1,32}$'
     OR btrim(coalesce(p_chat_id, '')) !~ '^-?[0-9]{1,32}$'
     OR btrim(coalesce(p_user_id, '')) !~ '^[0-9]{1,32}$'
     OR coalesce(p_template_code, '') NOT IN ('recovery_instructions', 'recovery_failed') THEN
    RAISE EXCEPTION 'invalid recovery public reply' USING ERRCODE = '22023';
  END IF;
  PERFORM admira._enqueue_recovery_chat_reply(
    p_request_id, p_bot_id, p_chat_id, p_user_id, p_template_code);
  RETURN p_template_code;
END;
$$;

CREATE OR REPLACE FUNCTION admira._recovery_rate_allowed(
  p_scope text, p_subject_hash bytea, p_max_requests integer,
  p_window_seconds integer DEFAULT 3600, p_cooldown_seconds integer DEFAULT 60
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE row_value admira.tenant_recovery_rate_limits%ROWTYPE; now_value timestamptz := now();
BEGIN
  INSERT INTO admira.tenant_recovery_rate_limits(scope, subject_hash, window_started_at, request_count)
  VALUES (p_scope, p_subject_hash, now_value, 0)
  ON CONFLICT (scope, subject_hash) DO NOTHING;
  SELECT * INTO row_value FROM admira.tenant_recovery_rate_limits
  WHERE scope = p_scope AND subject_hash = p_subject_hash FOR UPDATE;
  IF row_value.window_started_at + make_interval(secs => p_window_seconds) <= now_value THEN
    UPDATE admira.tenant_recovery_rate_limits
    SET window_started_at = now_value, request_count = 0, blocked_until = NULL, updated_at = now_value
    WHERE scope = p_scope AND subject_hash = p_subject_hash;
    row_value.request_count := 0;
    row_value.blocked_until := NULL;
  END IF;
  IF row_value.blocked_until IS NOT NULL AND row_value.blocked_until > now_value THEN
    RETURN false;
  END IF;
  IF row_value.request_count >= p_max_requests THEN
    UPDATE admira.tenant_recovery_rate_limits
    SET blocked_until = now_value + make_interval(secs => p_cooldown_seconds), updated_at = now_value
    WHERE scope = p_scope AND subject_hash = p_subject_hash;
    RETURN false;
  END IF;
  UPDATE admira.tenant_recovery_rate_limits
  SET request_count = request_count + 1, updated_at = now_value
  WHERE scope = p_scope AND subject_hash = p_subject_hash;
  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION admira.register_verified_license_contact(
  p_tenant_id uuid, p_email_hmac_hex text, p_license_hmac_hex text,
  p_delivery_ref text, p_verified_at timestamptz DEFAULT now(),
  p_actor_id text DEFAULT 'operator'
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE old admira.tenant_license_contacts%ROWTYPE; changed boolean := true;
BEGIN
  IF p_tenant_id IS NULL OR coalesce(p_email_hmac_hex, '') !~ '^[a-f0-9]{64}$'
     OR coalesce(p_license_hmac_hex, '') !~ '^[a-f0-9]{64}$'
     OR coalesce(p_delivery_ref, '') !~ '^[A-Za-z][A-Za-z0-9+.-]*://'
     OR char_length(p_delivery_ref) NOT BETWEEN 8 AND 512
     OR p_delivery_ref ~ '[[:space:][:cntrl:]]'
     OR p_verified_at IS NULL OR p_verified_at > now()
     OR btrim(coalesce(p_actor_id, '')) = '' OR char_length(p_actor_id) > 200 THEN
    RAISE EXCEPTION 'invalid verified license contact' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenants t JOIN admira.tenant_entitlements e ON e.tenant_id = t.id
    WHERE t.id = p_tenant_id AND t.status = 'active' AND e.lifecycle_state = 'licensed'
  ) THEN
    RAISE EXCEPTION 'licensed tenant is unavailable' USING ERRCODE = '55000';
  END IF;
  SELECT * INTO old FROM admira.tenant_license_contacts WHERE tenant_id = p_tenant_id FOR UPDATE;
  IF FOUND AND old.revoked_at IS NULL
     AND old.email_hmac = decode(p_email_hmac_hex, 'hex')
     AND old.license_hmac = decode(p_license_hmac_hex, 'hex')
     AND old.delivery_ref = p_delivery_ref THEN
    changed := false;
  ELSE
    INSERT INTO admira.tenant_license_contacts
      (tenant_id, email_hmac, license_hmac, delivery_ref, verified_at, identity_version, revoked_at)
    VALUES (p_tenant_id, decode(p_email_hmac_hex, 'hex'), decode(p_license_hmac_hex, 'hex'),
            p_delivery_ref, p_verified_at, coalesce(old.identity_version, 0) + 1, NULL)
    ON CONFLICT (tenant_id) DO UPDATE SET
      email_hmac = EXCLUDED.email_hmac, license_hmac = EXCLUDED.license_hmac,
      delivery_ref = EXCLUDED.delivery_ref, verified_at = EXCLUDED.verified_at,
      identity_version = admira.tenant_license_contacts.identity_version + 1,
      revoked_at = NULL, updated_at = now();
    UPDATE admira.tenant_recovery_challenges SET status = 'invalidated', invalidated_at = now()
    WHERE tenant_id = p_tenant_id AND status = 'pending';
    PERFORM admira._recovery_audit(gen_random_uuid(), p_tenant_id, 'operator', p_tenant_id::text,
      p_actor_id, decode(p_email_hmac_hex, 'hex'), decode(p_license_hmac_hex, 'hex'),
      'contact_registered');
  END IF;
  RETURN changed;
END;
$$;

CREATE OR REPLACE FUNCTION admira.revoke_verified_license_contact(
  p_tenant_id uuid, p_actor_id text DEFAULT 'operator'
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE contact admira.tenant_license_contacts%ROWTYPE;
BEGIN
  SELECT * INTO contact FROM admira.tenant_license_contacts WHERE tenant_id = p_tenant_id FOR UPDATE;
  IF NOT FOUND OR contact.revoked_at IS NOT NULL THEN RETURN false; END IF;
  UPDATE admira.tenant_license_contacts
  SET revoked_at = now(), identity_version = identity_version + 1, updated_at = now()
  WHERE tenant_id = p_tenant_id;
  UPDATE admira.tenant_recovery_challenges SET status = 'invalidated', invalidated_at = now()
  WHERE tenant_id = p_tenant_id AND status = 'pending';
  PERFORM admira._recovery_audit(gen_random_uuid(), p_tenant_id, 'operator', p_tenant_id::text,
    p_actor_id, contact.email_hmac, contact.license_hmac, 'contact_revoked');
  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION admira.begin_telegram_recovery(
  p_request_id uuid, p_bot_id text, p_chat_id text, p_user_id text,
  p_email_hmac_hex text, p_license_hmac_hex text, p_otp_hash_hex text,
  p_otp_ciphertext bytea, p_delivery_key_version text
)
RETURNS TABLE (request_id uuid, public_outcome text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE resolved_tenant uuid; contact_version bigint; delivery_ref_value text;
  email_value bytea; license_value bytea; otp_value bytea; allowed boolean;
  challenge_id uuid; chat_hash bytea; email_hash bytea; license_hash bytea;
BEGIN
  request_id := p_request_id;
  public_outcome := 'recovery_pending';
  IF p_request_id IS NULL OR btrim(coalesce(p_bot_id, '')) !~ '^[0-9]{1,32}$'
     OR btrim(coalesce(p_chat_id, '')) !~ '^-?[0-9]{1,32}$'
     OR btrim(coalesce(p_user_id, '')) !~ '^[0-9]{1,32}$'
     OR coalesce(p_email_hmac_hex, '') !~ '^[a-f0-9]{64}$'
     OR coalesce(p_license_hmac_hex, '') !~ '^[a-f0-9]{64}$'
     OR coalesce(p_otp_hash_hex, '') !~ '^[a-f0-9]{64}$'
     OR p_otp_ciphertext IS NULL OR octet_length(p_otp_ciphertext) NOT BETWEEN 32 AND 8192
     OR coalesce(p_delivery_key_version, '') = '' THEN
    RAISE EXCEPTION 'invalid recovery request' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (SELECT 1 FROM admira.tenant_recovery_challenges AS existing_challenge
             WHERE existing_challenge.request_id = p_request_id) THEN
    RETURN NEXT; RETURN;
  END IF;
  email_value := decode(p_email_hmac_hex, 'hex'); license_value := decode(p_license_hmac_hex, 'hex');
  otp_value := decode(p_otp_hash_hex, 'hex');
  chat_hash := public.digest(convert_to('chat:' || btrim(p_bot_id) || ':' || btrim(p_chat_id), 'UTF8'), 'sha256');
  email_hash := public.digest(convert_to('email:' || p_email_hmac_hex, 'UTF8'), 'sha256');
  license_hash := public.digest(convert_to('license:' || p_license_hmac_hex, 'UTF8'), 'sha256');
  allowed := admira._recovery_rate_allowed('chat', chat_hash, 5)
             AND admira._recovery_rate_allowed('email', email_hash, 5)
             AND admira._recovery_rate_allowed('license', license_hash, 5);
  SELECT c.tenant_id, c.identity_version, c.delivery_ref INTO resolved_tenant, contact_version, delivery_ref_value
  FROM admira.tenant_license_contacts c
  JOIN admira.tenants t ON t.id = c.tenant_id AND t.status = 'active'
  JOIN admira.tenant_entitlements e ON e.tenant_id = c.tenant_id AND e.lifecycle_state = 'licensed'
  WHERE c.email_hmac = email_value AND c.license_hmac = license_value
    AND c.revoked_at IS NULL AND c.verified_at <= now()
    AND EXISTS (
      SELECT 1 FROM admira.tenant_telegram_bindings existing_binding
      WHERE existing_binding.tenant_id = c.tenant_id
        AND existing_binding.bot_id = btrim(p_bot_id)
    );
  IF NOT allowed THEN resolved_tenant := NULL; contact_version := NULL; delivery_ref_value := NULL; END IF;
  INSERT INTO admira.tenant_recovery_challenges
    (request_id, tenant_id, requester_bot_id, requester_chat_id, requester_user_id,
     email_hmac, license_hmac, contact_identity_version, otp_hash, otp_ciphertext,
     delivery_key_version, expires_at)
  VALUES (p_request_id, resolved_tenant, btrim(p_bot_id), btrim(p_chat_id), btrim(p_user_id),
          email_value, license_value, contact_version, otp_value, p_otp_ciphertext,
          p_delivery_key_version, now() + interval '15 minutes')
  RETURNING id INTO challenge_id;
  -- This fixed response is queued for every structurally valid request,
  -- including decoys and rate-limited requests, so the chat cannot enumerate.
  PERFORM admira._enqueue_recovery_chat_reply(
    p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_pending');
  PERFORM admira._recovery_audit(p_request_id, resolved_tenant, p_bot_id, p_chat_id, p_user_id,
    email_value, license_value, 'requested');
  IF NOT allowed THEN
    PERFORM admira._recovery_audit(p_request_id, NULL, p_bot_id, p_chat_id, p_user_id,
      email_value, license_value, 'rate_limited');
  END IF;
  IF allowed AND resolved_tenant IS NOT NULL THEN
    INSERT INTO admira.tenant_recovery_delivery_outbox
      (challenge_id, delivery_ref, template_code, encrypted_payload, delivery_key_version)
    VALUES (challenge_id, delivery_ref_value, 'telegram_recovery_otp', p_otp_ciphertext, p_delivery_key_version);
    PERFORM admira._recovery_audit(p_request_id, resolved_tenant, p_bot_id, p_chat_id, p_user_id,
      email_value, license_value, 'delivery_queued');
  END IF;
  RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION admira.claim_recovery_chat_outbox(
  p_worker_id text, p_limit integer DEFAULT 20, p_lease_seconds integer DEFAULT 120
)
RETURNS TABLE (
  outbox_id uuid, request_id uuid, bot_id text, chat_id text, user_id text,
  template_code text, body text, attempt_count integer, lease_token uuid
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
BEGIN
  IF btrim(coalesce(p_worker_id, '')) = '' OR p_limit NOT BETWEEN 1 AND 100
     OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid recovery chat claim' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  WITH picked AS (
    SELECT o.id FROM admira.telegram_recovery_chat_outbox o
    WHERE (o.status IN ('queued', 'retry') AND o.available_at <= now())
       OR (o.status = 'sending' AND o.leased_until <= now())
    ORDER BY o.created_at, o.id
    FOR UPDATE SKIP LOCKED LIMIT p_limit
  ), claimed AS (
    UPDATE admira.telegram_recovery_chat_outbox o
    SET status = 'sending', attempt_count = o.attempt_count + 1,
        lease_token = gen_random_uuid(), leased_until = now() + make_interval(secs => p_lease_seconds)
    FROM picked WHERE o.id = picked.id
    RETURNING o.id, o.request_id, o.bot_id, o.chat_id, o.user_id, o.template_code,
      o.body, o.attempt_count, o.lease_token
  )
  SELECT claimed.id, claimed.request_id, claimed.bot_id, claimed.chat_id,
         claimed.user_id, claimed.template_code, claimed.body,
         claimed.attempt_count, claimed.lease_token
  FROM claimed;
END;
$$;

CREATE OR REPLACE FUNCTION admira.ack_recovery_chat_outbox(
  p_outbox_id uuid, p_lease_token uuid, p_sent boolean,
  p_error_code text DEFAULT NULL, p_retry_after_seconds integer DEFAULT 30,
  p_max_attempts integer DEFAULT 5
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE changed integer;
BEGIN
  IF p_outbox_id IS NULL OR p_lease_token IS NULL OR p_retry_after_seconds NOT BETWEEN 1 AND 86400
     OR p_max_attempts NOT BETWEEN 1 AND 20
     OR (NOT p_sent AND coalesce(p_error_code, '') NOT IN
       ('telegram_unavailable', 'telegram_rate_limited', 'timeout', 'internal_error')) THEN
    RAISE EXCEPTION 'invalid recovery chat acknowledgement' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.telegram_recovery_chat_outbox
  SET status = CASE WHEN p_sent THEN 'sent'
                    WHEN attempt_count >= p_max_attempts THEN 'dead' ELSE 'retry' END,
      sent_at = CASE WHEN p_sent THEN now() ELSE sent_at END,
      last_error_code = CASE WHEN p_sent THEN NULL ELSE p_error_code END,
      available_at = CASE WHEN NOT p_sent AND attempt_count < p_max_attempts
                          THEN now() + make_interval(secs => p_retry_after_seconds) ELSE available_at END,
      lease_token = NULL, leased_until = NULL
  WHERE id = p_outbox_id AND status = 'sending' AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

-- Email delivery is deliberately provider-neutral.  The worker receives an
-- opaque delivery_ref and an application-encrypted payload; PostgreSQL never
-- exposes a recipient address or OTP in plaintext.  Claim/ack is fenced by a
-- lease token so a late worker cannot overwrite a newer retry.
CREATE OR REPLACE FUNCTION admira.claim_recovery_email_outbox(
  p_worker_id text, p_limit integer DEFAULT 20, p_lease_seconds integer DEFAULT 120
)
RETURNS TABLE (
  outbox_id uuid, challenge_id uuid, request_id uuid,
  delivery_ref text, template_code text,
  encrypted_payload bytea, delivery_key_version text, attempt_count integer,
  lease_token uuid
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
BEGIN
  IF btrim(coalesce(p_worker_id, '')) = '' OR char_length(p_worker_id) > 200
     OR p_limit NOT BETWEEN 1 AND 100
     OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid recovery email claim' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  WITH picked AS (
    SELECT o.id FROM admira.tenant_recovery_delivery_outbox o
    WHERE (o.status IN ('queued', 'retry') AND o.available_at <= now())
       OR (o.status = 'sending' AND o.leased_until <= now())
    ORDER BY o.created_at, o.id
    FOR UPDATE SKIP LOCKED LIMIT p_limit
  ), claimed AS (
    UPDATE admira.tenant_recovery_delivery_outbox o
    SET status = 'sending', attempt_count = o.attempt_count + 1,
        lease_token = gen_random_uuid(), leased_until = now() + make_interval(secs => p_lease_seconds)
    FROM picked WHERE o.id = picked.id
    RETURNING o.id, o.challenge_id, o.delivery_ref, o.template_code,
      o.encrypted_payload, o.delivery_key_version, o.attempt_count, o.lease_token
  )
  SELECT claimed.id, claimed.challenge_id, challenge.request_id,
         claimed.delivery_ref, claimed.template_code, claimed.encrypted_payload,
         claimed.delivery_key_version, claimed.attempt_count, claimed.lease_token
  FROM claimed
  JOIN admira.tenant_recovery_challenges AS challenge
    ON challenge.id = claimed.challenge_id;
END;
$$;

CREATE OR REPLACE FUNCTION admira.ack_recovery_email_outbox(
  p_outbox_id uuid, p_lease_token uuid, p_sent boolean,
  p_error_code text DEFAULT NULL, p_retry_after_seconds integer DEFAULT 60,
  p_max_attempts integer DEFAULT 5
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE changed integer;
BEGIN
  IF p_outbox_id IS NULL OR p_lease_token IS NULL
     OR p_retry_after_seconds NOT BETWEEN 1 AND 86400
     OR p_max_attempts NOT BETWEEN 1 AND 20
     OR (NOT p_sent AND coalesce(p_error_code, '') NOT IN
       ('provider_unavailable', 'provider_rejected', 'timeout', 'internal_error')) THEN
    RAISE EXCEPTION 'invalid recovery email acknowledgement' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.tenant_recovery_delivery_outbox
  SET status = CASE WHEN p_sent THEN 'sent'
                    WHEN attempt_count >= p_max_attempts THEN 'dead' ELSE 'retry' END,
      sent_at = CASE WHEN p_sent THEN now() ELSE sent_at END,
      last_error_code = CASE WHEN p_sent THEN NULL ELSE p_error_code END,
      available_at = CASE WHEN NOT p_sent AND attempt_count < p_max_attempts
                          THEN now() + make_interval(secs => p_retry_after_seconds)
                          ELSE available_at END,
      lease_token = NULL, leased_until = NULL
  WHERE id = p_outbox_id AND status = 'sending' AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.confirm_telegram_recovery(
  p_request_id uuid, p_bot_id text, p_chat_id text, p_user_id text,
  p_otp_hash_hex text
)
RETURNS TABLE (completed boolean, public_outcome text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE challenge admira.tenant_recovery_challenges%ROWTYPE;
  contact admira.tenant_license_contacts%ROWTYPE; old_binding admira.tenant_telegram_bindings%ROWTYPE;
  target_binding admira.tenant_telegram_bindings%ROWTYPE; new_binding_id uuid; otp_value bytea;
BEGIN
  completed := false; public_outcome := 'recovery_failed';
  IF p_request_id IS NULL OR btrim(coalesce(p_bot_id, '')) !~ '^[0-9]{1,32}$'
     OR btrim(coalesce(p_chat_id, '')) !~ '^-?[0-9]{1,32}$'
     OR btrim(coalesce(p_user_id, '')) !~ '^[0-9]{1,32}$'
     OR coalesce(p_otp_hash_hex, '') !~ '^[a-f0-9]{64}$' THEN
    IF p_request_id IS NOT NULL THEN PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed'); END IF;
    RETURN NEXT; RETURN;
  END IF;
  otp_value := decode(p_otp_hash_hex, 'hex');
  SELECT * INTO challenge FROM admira.tenant_recovery_challenges
  WHERE request_id = p_request_id FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  IF challenge.status <> 'pending' OR challenge.expires_at <= now()
     OR challenge.requester_bot_id <> btrim(p_bot_id)
     OR challenge.requester_chat_id <> btrim(p_chat_id)
     OR challenge.requester_user_id <> btrim(p_user_id) THEN
    IF challenge.status = 'pending' AND challenge.expires_at <= now() THEN
      UPDATE admira.tenant_recovery_challenges SET status = 'expired' WHERE id = challenge.id;
      PERFORM admira._recovery_audit(challenge.request_id, challenge.tenant_id, p_bot_id, p_chat_id, p_user_id,
        challenge.email_hmac, challenge.license_hmac, 'otp_expired');
    END IF;
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  IF challenge.attempt_count >= challenge.max_attempts THEN
    UPDATE admira.tenant_recovery_challenges SET status = 'locked', cooldown_until = now() + interval '15 minutes'
    WHERE id = challenge.id;
    PERFORM admira._recovery_audit(challenge.request_id, challenge.tenant_id, p_bot_id, p_chat_id, p_user_id,
      challenge.email_hmac, challenge.license_hmac, 'otp_locked');
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  IF challenge.otp_hash <> otp_value THEN
    UPDATE admira.tenant_recovery_challenges
    SET attempt_count = attempt_count + 1,
        status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'locked' ELSE 'pending' END,
        cooldown_until = CASE WHEN attempt_count + 1 >= max_attempts THEN now() + interval '15 minutes' ELSE cooldown_until END
    WHERE id = challenge.id;
    PERFORM admira._recovery_audit(challenge.request_id, challenge.tenant_id, p_bot_id, p_chat_id, p_user_id,
      challenge.email_hmac, challenge.license_hmac,
      CASE WHEN challenge.attempt_count + 1 >= challenge.max_attempts THEN 'otp_locked' ELSE 'otp_failed' END);
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  IF challenge.tenant_id IS NULL THEN
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  SELECT * INTO contact FROM admira.tenant_license_contacts
  WHERE tenant_id = challenge.tenant_id AND revoked_at IS NULL FOR UPDATE;
  IF NOT FOUND OR contact.identity_version <> challenge.contact_identity_version THEN
    PERFORM admira._recovery_audit(challenge.request_id, challenge.tenant_id, p_bot_id, p_chat_id, p_user_id,
      challenge.email_hmac, challenge.license_hmac, 'rebind_rejected');
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenants t JOIN admira.tenant_entitlements e ON e.tenant_id = t.id
                 WHERE t.id = challenge.tenant_id AND t.status = 'active' AND e.lifecycle_state = 'licensed') THEN
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  SELECT * INTO target_binding FROM admira.tenant_telegram_bindings
  WHERE bot_id = btrim(p_bot_id) AND telegram_chat_id = btrim(p_chat_id) FOR UPDATE;
  IF FOUND AND target_binding.tenant_id <> challenge.tenant_id THEN
    PERFORM admira._recovery_audit(challenge.request_id, challenge.tenant_id, p_bot_id, p_chat_id, p_user_id,
      challenge.email_hmac, challenge.license_hmac, 'rebind_rejected');
    PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
    RETURN NEXT; RETURN;
  END IF;
  IF target_binding.id IS NULL THEN
    -- The unique index is the concurrency boundary.  A concurrent winner is
    -- re-read and checked; this function never transfers a row between tenants.
    INSERT INTO admira.tenant_telegram_bindings
      (tenant_id, telegram_user_id, telegram_chat_id, bot_id, is_primary)
    VALUES (challenge.tenant_id, btrim(p_user_id), btrim(p_chat_id), btrim(p_bot_id), true)
    ON CONFLICT DO NOTHING;
    SELECT * INTO target_binding FROM admira.tenant_telegram_bindings
    WHERE bot_id = btrim(p_bot_id) AND telegram_chat_id = btrim(p_chat_id) FOR UPDATE;
    IF NOT FOUND OR target_binding.tenant_id <> challenge.tenant_id THEN
      PERFORM admira._recovery_audit(challenge.request_id, challenge.tenant_id, p_bot_id, p_chat_id, p_user_id,
        challenge.email_hmac, challenge.license_hmac, 'rebind_rejected');
      PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_failed');
      RETURN NEXT; RETURN;
    END IF;
  ELSE
    UPDATE admira.tenant_telegram_bindings
    SET telegram_user_id = btrim(p_user_id), is_primary = true, updated_at = now()
    WHERE id = target_binding.id;
    SELECT * INTO target_binding FROM admira.tenant_telegram_bindings
    WHERE id = target_binding.id FOR UPDATE;
  END IF;

  new_binding_id := target_binding.id;
  -- Archive and remove every other active binding for this tenant.  The
  -- destination was established first, so a conflict leaves all old state
  -- untouched and can never steal a chat from another tenant.
  FOR old_binding IN
    SELECT * FROM admira.tenant_telegram_bindings
    WHERE tenant_id = challenge.tenant_id AND id <> new_binding_id
    ORDER BY is_primary DESC, created_at ASC
    FOR UPDATE
  LOOP
    INSERT INTO admira.tenant_telegram_binding_history
      (tenant_id, old_binding_id, old_bot_id, old_chat_id, old_user_id,
       new_binding_id, new_bot_id, new_chat_id, new_user_id, reason, actor_id)
    VALUES (challenge.tenant_id, old_binding.id, old_binding.bot_id, old_binding.telegram_chat_id,
            old_binding.telegram_user_id, new_binding_id, btrim(p_bot_id), btrim(p_chat_id),
            btrim(p_user_id), 'recovery_rebind', 'telegram-recovery');
    DELETE FROM admira.tenant_telegram_bindings WHERE id = old_binding.id;
  END LOOP;
  UPDATE admira.tenant_license_contacts
  SET identity_version = identity_version + 1, updated_at = now()
  WHERE tenant_id = challenge.tenant_id;
  UPDATE admira.tenant_recovery_challenges
  SET status = CASE WHEN id = challenge.id THEN 'consumed' ELSE 'invalidated' END,
      consumed_at = CASE WHEN id = challenge.id THEN now() ELSE consumed_at END,
      invalidated_at = CASE WHEN id <> challenge.id THEN now() ELSE invalidated_at END
  WHERE tenant_id = challenge.tenant_id AND status = 'pending';
  PERFORM admira._recovery_audit(challenge.request_id, challenge.tenant_id, p_bot_id, p_chat_id, p_user_id,
    challenge.email_hmac, challenge.license_hmac, 'rebind_succeeded');
  completed := true; public_outcome := 'recovery_completed';
  PERFORM admira._enqueue_recovery_chat_reply(p_request_id, p_bot_id, p_chat_id, p_user_id, 'recovery_completed');
  RETURN NEXT;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_recovery') THEN
    CREATE ROLE admira_recovery NOLOGIN NOBYPASSRLS;
  END IF;
END;
$$;
ALTER ROLE admira_recovery NOLOGIN NOBYPASSRLS;
GRANT USAGE ON SCHEMA admira TO admira_recovery;

REVOKE ALL ON TABLE admira.tenant_license_contacts,
  admira.tenant_telegram_binding_history, admira.tenant_recovery_rate_limits,
  admira.tenant_recovery_challenges, admira.tenant_recovery_delivery_outbox,
  admira.tenant_recovery_audit_events, admira.telegram_recovery_chat_outbox
  FROM PUBLIC, admira_ingress, admira_runtime, admira_delivery, admira_scheduler,
       admira_provisioner, admira_recovery;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_email_delivery') THEN
    CREATE ROLE admira_email_delivery NOLOGIN NOBYPASSRLS;
  END IF;
END;
$$;
ALTER ROLE admira_email_delivery NOLOGIN NOBYPASSRLS;
GRANT USAGE ON SCHEMA admira TO admira_email_delivery;
REVOKE ALL ON TABLE admira.tenant_recovery_delivery_outbox FROM admira_email_delivery;
REVOKE ALL ON FUNCTION admira._recovery_audit(uuid, uuid, text, text, text, bytea, bytea, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira._enqueue_recovery_chat_reply(uuid, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.enqueue_telegram_recovery_public_reply(uuid, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira._recovery_rate_allowed(text, bytea, integer, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.register_verified_license_contact(uuid, text, text, text, timestamptz, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.revoke_verified_license_contact(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.begin_telegram_recovery(uuid, text, text, text, text, text, text, bytea, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.confirm_telegram_recovery(uuid, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_recovery_chat_outbox(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.ack_recovery_chat_outbox(uuid, uuid, boolean, text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_recovery_email_outbox(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.ack_recovery_email_outbox(uuid, uuid, boolean, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.register_verified_license_contact(uuid, text, text, text, timestamptz, text),
  admira.revoke_verified_license_contact(uuid, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.begin_telegram_recovery(uuid, text, text, text, text, text, text, bytea, text),
  admira.confirm_telegram_recovery(uuid, text, text, text, text),
  admira.enqueue_telegram_recovery_public_reply(uuid, text, text, text, text) TO admira_recovery;
GRANT EXECUTE ON FUNCTION admira.claim_recovery_chat_outbox(text, integer, integer),
  admira.ack_recovery_chat_outbox(uuid, uuid, boolean, text, integer, integer) TO admira_delivery;
GRANT EXECUTE ON FUNCTION admira.claim_recovery_email_outbox(text, integer, integer),
  admira.ack_recovery_email_outbox(uuid, uuid, boolean, text, integer, integer) TO admira_email_delivery;

ALTER TABLE admira.tenant_telegram_binding_history OWNER TO admira_control_owner;
ALTER TABLE admira.tenant_license_contacts OWNER TO admira_control_owner;
ALTER TABLE admira.tenant_recovery_rate_limits OWNER TO admira_control_owner;
ALTER TABLE admira.tenant_recovery_challenges OWNER TO admira_control_owner;
ALTER TABLE admira.tenant_recovery_delivery_outbox OWNER TO admira_control_owner;
ALTER TABLE admira.tenant_recovery_audit_events OWNER TO admira_control_owner;
ALTER TABLE admira.telegram_recovery_chat_outbox OWNER TO admira_control_owner;
ALTER FUNCTION admira._recovery_audit(uuid, uuid, text, text, text, bytea, bytea, text, jsonb) OWNER TO admira_control_owner;
ALTER FUNCTION admira._enqueue_recovery_chat_reply(uuid, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.enqueue_telegram_recovery_public_reply(uuid, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira._recovery_rate_allowed(text, bytea, integer, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.prevent_recovery_history_mutation() OWNER TO admira_control_owner;
ALTER FUNCTION admira.register_verified_license_contact(uuid, text, text, text, timestamptz, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.revoke_verified_license_contact(uuid, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.begin_telegram_recovery(uuid, text, text, text, text, text, text, bytea, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.confirm_telegram_recovery(uuid, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_recovery_chat_outbox(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.ack_recovery_chat_outbox(uuid, uuid, boolean, text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_recovery_email_outbox(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.ack_recovery_email_outbox(uuid, uuid, boolean, text, integer, integer) OWNER TO admira_control_owner;

COMMENT ON TABLE admira.tenant_license_contacts IS 'Verified identity metadata only; email/license addresses are never stored, only HMACs and an opaque delivery reference.';
COMMENT ON TABLE admira.tenant_telegram_binding_history IS 'Immutable recovery binding history; active bindings remain in tenant_telegram_bindings for compatibility.';
COMMENT ON TABLE admira.tenant_recovery_delivery_outbox IS 'Provider-neutral encrypted email intent; no plaintext recipient or OTP.';

COMMIT;
