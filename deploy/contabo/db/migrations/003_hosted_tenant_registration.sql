-- Host-only tenant registration plus one-time Telegram DM claims. Raw claim
-- tokens and the shared bot credential are never stored in PostgreSQL.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:003_hosted_tenant_registration', 0));

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_provisioner') THEN
    CREATE ROLE admira_provisioner NOLOGIN;
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS admira.tenant_telegram_claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  token_hash bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS tenant_telegram_claims_tenant_idx
  ON admira.tenant_telegram_claims (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS tenant_telegram_claims_expiry_idx
  ON admira.tenant_telegram_claims (expires_at)
  WHERE used_at IS NULL;

ALTER TABLE admira.tenant_telegram_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_telegram_claims FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_telegram_claims;
CREATE POLICY tenant_isolation ON admira.tenant_telegram_claims
  USING (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

GRANT SELECT, INSERT, UPDATE, DELETE ON admira.tenant_telegram_claims TO admira_control_owner;

CREATE OR REPLACE FUNCTION admira._ensure_hosted_tenant(p_runtime_key text, p_display_name text)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid; existing_runtime text;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR btrim(coalesce(p_display_name, '')) = ''
     OR char_length(btrim(p_display_name)) > 200 THEN
    RAISE EXCEPTION 'invalid hosted tenant registration' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant FROM admira.tenants AS t
  WHERE t.external_customer_id = p_runtime_key FOR UPDATE;
  IF resolved_tenant IS NULL THEN
    INSERT INTO admira.tenants (external_customer_id, display_name, status)
    VALUES (p_runtime_key, btrim(p_display_name), 'active') RETURNING id INTO resolved_tenant;
  ELSE
    UPDATE admira.tenants SET display_name = btrim(p_display_name), status = 'active'
    WHERE id = resolved_tenant AND status <> 'deleted';
    IF NOT FOUND THEN
      RAISE EXCEPTION 'deleted tenant cannot be reactivated' USING ERRCODE = '55000';
    END IF;
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
  RETURN resolved_tenant;
END;
$$;

CREATE OR REPLACE FUNCTION admira.issue_telegram_tenant_claim(
  p_runtime_key text, p_display_name text, p_token_hash_hex text, p_ttl_seconds integer DEFAULT 1800
)
RETURNS TABLE (tenant_id uuid, expires_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid; expiry timestamptz;
BEGIN
  IF coalesce(p_token_hash_hex, '') !~ '^[a-f0-9]{64}$'
     OR p_ttl_seconds NOT BETWEEN 300 AND 86400 THEN
    RAISE EXCEPTION 'invalid telegram claim' USING ERRCODE = '22023';
  END IF;
  resolved_tenant := admira._ensure_hosted_tenant(p_runtime_key, p_display_name);
  UPDATE admira.tenant_telegram_claims SET used_at = now()
  WHERE admira.tenant_telegram_claims.tenant_id = resolved_tenant AND used_at IS NULL;
  expiry := now() + make_interval(secs => p_ttl_seconds);
  INSERT INTO admira.tenant_telegram_claims (tenant_id, token_hash, expires_at)
  VALUES (resolved_tenant, decode(p_token_hash_hex, 'hex'), expiry);
  RETURN QUERY SELECT resolved_tenant, expiry;
END;
$$;

CREATE OR REPLACE FUNCTION admira.register_hosted_tenant(
  p_runtime_key text, p_display_name text, p_bot_id text, p_chat_id text, p_user_id text
)
RETURNS TABLE (tenant_id uuid, runtime_key text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
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
  RETURN QUERY SELECT resolved_tenant, p_runtime_key;
END;
$$;

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
     OR coalesce(p_raw_token, '') !~ '^[A-Za-z0-9_-]{20,128}$' THEN
    RETURN;
  END IF;
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
               AND (b.bot_id <> p_bot_id OR b.telegram_chat_id <> p_chat_id)) THEN
    RETURN;
  END IF;
  INSERT INTO admira.tenant_telegram_bindings
    (tenant_id, telegram_user_id, telegram_chat_id, bot_id, is_primary)
  VALUES (claim.tenant_id, p_user_id, p_chat_id, p_bot_id, true)
  ON CONFLICT (bot_id, telegram_chat_id) DO UPDATE
    SET telegram_user_id = EXCLUDED.telegram_user_id, is_primary = true, updated_at = now();
  UPDATE admira.tenant_telegram_claims SET used_at = now() WHERE id = claim.id;
  INSERT INTO admira.tenant_telegram_outbox
    (tenant_id, bot_id, telegram_chat_id, sequence_no, kind, body)
  VALUES (claim.tenant_id, p_bot_id, p_chat_id, 0, 'text',
          '✅ Tu espacio privado de Admira IA quedó conectado. Escríbeme hola para comenzar.');
  RETURN QUERY SELECT claim.tenant_id;
END;
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA admira FROM admira_provisioner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA admira FROM admira_provisioner;
GRANT USAGE ON SCHEMA admira TO admira_provisioner;
REVOKE ALL ON FUNCTION admira._ensure_hosted_tenant(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.issue_telegram_tenant_claim(text, text, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.register_hosted_tenant(text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_telegram_tenant(text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.issue_telegram_tenant_claim(text, text, text, integer),
  admira.register_hosted_tenant(text, text, text, text, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.claim_telegram_tenant(text, text, text, text) TO admira_ingress;
ALTER FUNCTION admira._ensure_hosted_tenant(text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.issue_telegram_tenant_claim(text, text, text, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.register_hosted_tenant(text, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_telegram_tenant(text, text, text, text) OWNER TO admira_control_owner;

COMMIT;
