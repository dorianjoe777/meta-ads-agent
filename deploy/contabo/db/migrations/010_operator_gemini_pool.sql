-- Operator-managed Gemini trial pool metadata.
--
-- Project quota is the capacity boundary.  This migration stores only opaque
-- secret references and fingerprints; provider keys never enter PostgreSQL.
-- Assignment is intentionally operator/provisioner-only and is valid only for
-- active tenants in pending_claim/trial state.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:010_operator_gemini_pool', 0));

CREATE TABLE IF NOT EXISTS admira.gemini_pool_projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_ref text NOT NULL UNIQUE CHECK (
    char_length(project_ref) BETWEEN 3 AND 200
    AND project_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]*$'
  ),
  max_trial_assignments integer NOT NULL CHECK (max_trial_assignments BETWEEN 1 AND 10000),
  health text NOT NULL DEFAULT 'healthy'
    CHECK (health IN ('healthy', 'degraded', 'unhealthy', 'disabled')),
  health_checked_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admira.gemini_pool_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES admira.gemini_pool_projects(id) ON DELETE CASCADE,
  secret_ref text NOT NULL CHECK (
    char_length(secret_ref) BETWEEN 8 AND 512
    AND secret_ref ~ '^[A-Za-z][A-Za-z0-9+.-]*://'
    AND secret_ref !~ '[[:space:][:cntrl:]]'
  ),
  fingerprint text NOT NULL CHECK (fingerprint ~ '^[a-f0-9]{64}$'),
  key_kind text NOT NULL DEFAULT 'unknown' CHECK (key_kind IN ('auth', 'standard', 'unknown')),
  health text NOT NULL DEFAULT 'healthy'
    CHECK (health IN ('healthy', 'degraded', 'unhealthy', 'disabled')),
  health_checked_at timestamptz NOT NULL DEFAULT now(),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (fingerprint),
  UNIQUE (project_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS gemini_pool_credentials_active_project_uq
  ON admira.gemini_pool_credentials(project_id) WHERE active;

CREATE TABLE IF NOT EXISTS admira.gemini_pool_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES admira.gemini_pool_projects(id) ON DELETE RESTRICT,
  credential_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released')),
  assigned_at timestamptz NOT NULL DEFAULT now(),
  released_at timestamptz,
  release_reason text CHECK (release_reason IS NULL OR release_reason IN (
    'licensed', 'trial_expired', 'suspended', 'cancelled', 'operator', 'replaced'
  )),
  CHECK ((status = 'active' AND released_at IS NULL)
      OR (status = 'released' AND released_at IS NOT NULL)),
  CHECK (project_id IS NOT NULL AND credential_id IS NOT NULL),
  FOREIGN KEY (project_id, credential_id)
    REFERENCES admira.gemini_pool_credentials(project_id, id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS gemini_pool_assignments_active_tenant_uq
  ON admira.gemini_pool_assignments(tenant_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS gemini_pool_assignments_project_status_idx
  ON admira.gemini_pool_assignments(project_id, status);

CREATE TABLE IF NOT EXISTS admira.gemini_pool_audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid REFERENCES admira.tenants(id) ON DELETE SET NULL,
  project_id uuid REFERENCES admira.gemini_pool_projects(id) ON DELETE SET NULL,
  assignment_id uuid REFERENCES admira.gemini_pool_assignments(id) ON DELETE SET NULL,
  event_type text NOT NULL CHECK (event_type IN (
    'project_registered', 'credential_registered', 'assigned', 'released', 'health_changed'
  )),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS gemini_pool_audit_tenant_idx
  ON admira.gemini_pool_audit_events(tenant_id, created_at DESC);

ALTER TABLE admira.gemini_pool_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.gemini_pool_projects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pool_owner_only ON admira.gemini_pool_projects;
CREATE POLICY pool_owner_only ON admira.gemini_pool_projects USING (false) WITH CHECK (false);
ALTER TABLE admira.gemini_pool_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.gemini_pool_credentials FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pool_owner_only ON admira.gemini_pool_credentials;
CREATE POLICY pool_owner_only ON admira.gemini_pool_credentials USING (false) WITH CHECK (false);
ALTER TABLE admira.gemini_pool_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.gemini_pool_assignments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pool_owner_only ON admira.gemini_pool_assignments;
CREATE POLICY pool_owner_only ON admira.gemini_pool_assignments USING (false) WITH CHECK (false);
ALTER TABLE admira.gemini_pool_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.gemini_pool_audit_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pool_owner_only ON admira.gemini_pool_audit_events;
CREATE POLICY pool_owner_only ON admira.gemini_pool_audit_events USING (false) WITH CHECK (false);

CREATE OR REPLACE FUNCTION admira._gemini_pool_audit(
  p_tenant_id uuid, p_project_id uuid, p_assignment_id uuid, p_event_type text,
  p_metadata jsonb DEFAULT '{}'::jsonb
)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
BEGIN
  INSERT INTO admira.gemini_pool_audit_events
    (tenant_id, project_id, assignment_id, event_type, metadata)
  VALUES (p_tenant_id, p_project_id, p_assignment_id, p_event_type,
          coalesce(p_metadata, '{}'::jsonb));
END;
$$;

CREATE OR REPLACE FUNCTION admira.register_gemini_pool_project(
  p_project_ref text, p_max_trial_assignments integer, p_health text DEFAULT 'healthy'
)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE project_id_value uuid;
BEGIN
  IF coalesce(p_project_ref, '') !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}$'
     OR p_max_trial_assignments NOT BETWEEN 1 AND 10000
     OR p_health NOT IN ('healthy', 'degraded', 'unhealthy', 'disabled') THEN
    RAISE EXCEPTION 'invalid Gemini pool project' USING ERRCODE = '22023';
  END IF;
  INSERT INTO admira.gemini_pool_projects(project_ref, max_trial_assignments, health)
  VALUES (p_project_ref, p_max_trial_assignments, p_health)
  ON CONFLICT (project_ref) DO UPDATE SET
    max_trial_assignments = EXCLUDED.max_trial_assignments,
    health = EXCLUDED.health, health_checked_at = now(), updated_at = now()
  RETURNING id INTO project_id_value;
  PERFORM admira._gemini_pool_audit(NULL, project_id_value, NULL, 'project_registered',
    jsonb_build_object('health', p_health));
  RETURN project_id_value;
END;
$$;

CREATE OR REPLACE FUNCTION admira.register_gemini_pool_credential(
  p_project_id uuid, p_secret_ref text, p_fingerprint text,
  p_health text DEFAULT 'healthy', p_key_kind text DEFAULT 'unknown'
)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE credential_id_value uuid;
  existing_project uuid; existing_id uuid;
BEGIN
  IF p_project_id IS NULL OR coalesce(p_secret_ref, '') !~ '^[A-Za-z][A-Za-z0-9+.-]*://'
     OR char_length(p_secret_ref) NOT BETWEEN 8 AND 512
     OR p_secret_ref ~ '[[:space:][:cntrl:]]'
     OR coalesce(p_fingerprint, '') !~ '^[a-f0-9]{64}$'
     OR p_health NOT IN ('healthy', 'degraded', 'unhealthy', 'disabled')
     OR p_key_kind NOT IN ('auth', 'standard', 'unknown') THEN
    RAISE EXCEPTION 'invalid Gemini pool credential' USING ERRCODE = '22023';
  END IF;
  PERFORM 1 FROM admira.gemini_pool_projects WHERE id = p_project_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Gemini pool project is unavailable' USING ERRCODE = '55000'; END IF;
  SELECT id, project_id INTO existing_id, existing_project
  FROM admira.gemini_pool_credentials WHERE fingerprint = p_fingerprint FOR UPDATE;
  IF FOUND AND existing_project <> p_project_id THEN
    RAISE EXCEPTION 'Gemini fingerprint is already registered to another project' USING ERRCODE = '23505';
  END IF;
  UPDATE admira.gemini_pool_credentials SET active = false, updated_at = now()
  WHERE project_id = p_project_id AND active;
  IF existing_id IS NULL THEN
    INSERT INTO admira.gemini_pool_credentials(project_id, secret_ref, fingerprint, key_kind, health, health_checked_at, active)
    VALUES (p_project_id, p_secret_ref, p_fingerprint, p_key_kind, p_health, now(), true)
    RETURNING id INTO credential_id_value;
  ELSE
    UPDATE admira.gemini_pool_credentials
    SET secret_ref = p_secret_ref, key_kind = p_key_kind, health = p_health,
        health_checked_at = now(), active = true, updated_at = now()
    WHERE id = existing_id
    RETURNING id INTO credential_id_value;
  END IF;
  PERFORM admira._gemini_pool_audit(NULL, p_project_id, NULL, 'credential_registered',
    jsonb_build_object('health', p_health));
  RETURN credential_id_value;
END;
$$;

CREATE OR REPLACE FUNCTION admira.assign_gemini_trial(p_tenant_id uuid)
RETURNS TABLE (assignment_id uuid, project_id uuid, credential_id uuid, secret_ref text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE tenant_state text; tenant_status text; project_row record; credential_row record;
  active_count integer; inserted_id uuid;
BEGIN
  SELECT t.status, e.lifecycle_state INTO tenant_status, tenant_state
  FROM admira.tenants t JOIN admira.tenant_entitlements e ON e.tenant_id = t.id
  WHERE t.id = p_tenant_id FOR UPDATE OF t, e;
  IF NOT FOUND OR tenant_status <> 'active' OR tenant_state NOT IN ('pending_claim', 'trial') THEN RETURN; END IF;
  SELECT a.id, a.project_id, a.credential_id, c.secret_ref INTO assignment_id, project_id, credential_id, secret_ref
  FROM admira.gemini_pool_assignments a JOIN admira.gemini_pool_credentials c ON c.id = a.credential_id
  WHERE a.tenant_id = p_tenant_id AND a.status = 'active';
  IF FOUND THEN RETURN NEXT; RETURN; END IF;
  FOR project_row IN
    SELECT * FROM admira.gemini_pool_projects
    WHERE health IN ('healthy', 'degraded')
    ORDER BY CASE WHEN health = 'healthy' THEN 0 ELSE 1 END, updated_at ASC, id
    FOR UPDATE SKIP LOCKED
  LOOP
    SELECT count(*)::integer INTO active_count
    FROM admira.gemini_pool_assignments a
    WHERE a.project_id = project_row.id AND a.status = 'active';
    IF active_count >= project_row.max_trial_assignments THEN CONTINUE; END IF;
    SELECT c.* INTO credential_row FROM admira.gemini_pool_credentials c
    WHERE c.project_id = project_row.id AND c.active AND c.key_kind = 'auth'
      AND c.health IN ('healthy', 'degraded')
    ORDER BY c.updated_at DESC, c.id LIMIT 1;
    IF NOT FOUND THEN CONTINUE; END IF;
    INSERT INTO admira.gemini_pool_assignments(tenant_id, project_id, credential_id)
    VALUES (p_tenant_id, project_row.id, credential_row.id)
    ON CONFLICT DO NOTHING RETURNING id INTO inserted_id;
    IF inserted_id IS NULL THEN
      SELECT a.id, a.project_id, a.credential_id, c.secret_ref INTO assignment_id, project_id, credential_id, secret_ref
      FROM admira.gemini_pool_assignments a JOIN admira.gemini_pool_credentials c ON c.id = a.credential_id
      WHERE a.tenant_id = p_tenant_id AND a.status = 'active';
      IF FOUND THEN RETURN NEXT; RETURN; END IF;
      RETURN;
    END IF;
    assignment_id := inserted_id; project_id := project_row.id;
    credential_id := credential_row.id; secret_ref := credential_row.secret_ref;
    PERFORM admira._gemini_pool_audit(p_tenant_id, project_id, assignment_id, 'assigned');
    RETURN NEXT; RETURN;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION admira.release_gemini_trial(
  p_tenant_id uuid, p_reason text DEFAULT 'operator'
)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE changed integer;
BEGIN
  IF p_tenant_id IS NULL OR p_reason NOT IN ('licensed', 'trial_expired', 'suspended', 'cancelled', 'operator', 'replaced') THEN
    RAISE EXCEPTION 'invalid Gemini pool release' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.gemini_pool_assignments a
  SET status = 'released', released_at = now(), release_reason = p_reason
  WHERE a.tenant_id = p_tenant_id AND a.status = 'active';
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed > 0 THEN
    PERFORM admira._gemini_pool_audit(p_tenant_id, NULL, NULL, 'released',
      jsonb_build_object('reason', p_reason, 'count', changed));
  END IF;
  RETURN changed;
END;
$$;

CREATE OR REPLACE FUNCTION admira._gemini_pool_release_on_state_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE tenant_id_value uuid; release_reason_value text;
BEGIN
  IF TG_TABLE_NAME = 'tenants' THEN
    IF NEW.status = 'active' THEN RETURN NEW; END IF;
    tenant_id_value := NEW.id;
    release_reason_value := CASE WHEN NEW.status = 'suspended' THEN 'suspended' ELSE 'cancelled' END;
  ELSE
    IF NEW.lifecycle_state IN ('pending_claim', 'trial') THEN RETURN NEW; END IF;
    tenant_id_value := NEW.tenant_id;
    release_reason_value := CASE
      WHEN NEW.lifecycle_state = 'licensed' THEN 'licensed'
      WHEN NEW.lifecycle_state = 'trial_expired' THEN 'trial_expired'
      WHEN NEW.lifecycle_state = 'cancelled' THEN 'cancelled'
      WHEN NEW.lifecycle_state = 'suspended' THEN 'suspended'
      ELSE 'operator'
    END;
  END IF;
  PERFORM admira.release_gemini_trial(tenant_id_value, release_reason_value);
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS gemini_pool_release_on_entitlement_state ON admira.tenant_entitlements;
CREATE TRIGGER gemini_pool_release_on_entitlement_state
  AFTER UPDATE OF lifecycle_state ON admira.tenant_entitlements
  FOR EACH ROW EXECUTE FUNCTION admira._gemini_pool_release_on_state_change();
DROP TRIGGER IF EXISTS gemini_pool_release_on_tenant_state ON admira.tenants;
CREATE TRIGGER gemini_pool_release_on_tenant_state
  AFTER UPDATE OF status ON admira.tenants
  FOR EACH ROW EXECUTE FUNCTION admira._gemini_pool_release_on_state_change();

-- Runtime-key adapters are the only pool lifecycle entry points exposed to
-- the hosted provisioner.  They resolve the key to exactly one tenant before
-- touching pool state, and return metadata only (never a provider secret).
CREATE OR REPLACE FUNCTION admira.assign_hosted_gemini_trial(p_runtime_key text)
RETURNS TABLE (
  assignment_id uuid, project_id uuid, credential_id uuid, secret_ref text,
  fingerprint text, key_kind text
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE resolved_tenant uuid;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$' THEN
    RAISE EXCEPTION 'invalid hosted runtime key' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant
  FROM admira.tenants t
  JOIN admira.tenant_runtime_leases l ON l.tenant_id = t.id
  JOIN admira.tenant_entitlements e ON e.tenant_id = t.id
  WHERE l.runtime_key = p_runtime_key
    AND t.status = 'active'
    AND e.lifecycle_state IN ('pending_claim', 'trial')
  FOR UPDATE OF t, e;
  IF NOT FOUND THEN
    RETURN;
  END IF;
  PERFORM admira.assign_gemini_trial(resolved_tenant);
  RETURN QUERY
  SELECT a.id, a.project_id, a.credential_id, c.secret_ref,
         c.fingerprint, c.key_kind
  FROM admira.gemini_pool_assignments a
  JOIN admira.gemini_pool_credentials c ON c.id = a.credential_id
  WHERE a.tenant_id = resolved_tenant AND a.status = 'active';
END;
$$;

CREATE OR REPLACE FUNCTION admira.finalize_hosted_gemini_trial(
  p_runtime_key text, p_assignment_id uuid
)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE resolved_tenant uuid; assignment_tenant uuid; project_value uuid;
  pool_secret_ref text; tenant_secret_ref text; fingerprint_value text; recorded boolean;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_assignment_id IS NULL THEN
    RAISE EXCEPTION 'invalid hosted Gemini trial finalization' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant
  FROM admira.tenants t
  JOIN admira.tenant_runtime_leases l ON l.tenant_id = t.id
  JOIN admira.tenant_entitlements e ON e.tenant_id = t.id
  WHERE l.runtime_key = p_runtime_key AND t.status = 'active'
    AND e.lifecycle_state IN ('pending_claim', 'trial')
  FOR UPDATE OF t, e;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'hosted tenant is not eligible for Gemini trial' USING ERRCODE = '55000';
  END IF;
  SELECT a.tenant_id, a.project_id, c.secret_ref, c.fingerprint
    INTO assignment_tenant, project_value, pool_secret_ref, fingerprint_value
  FROM admira.gemini_pool_assignments a
  JOIN admira.gemini_pool_credentials c ON c.id = a.credential_id
  WHERE a.id = p_assignment_id AND a.status = 'active'
  FOR UPDATE OF a;
  IF NOT FOUND OR assignment_tenant <> resolved_tenant THEN
    RAISE EXCEPTION 'Gemini assignment does not belong to runtime tenant' USING ERRCODE = '42501';
  END IF;
  -- The tenant-facing metadata points at its private env namespace.  The
  -- operator pool reference remains internal and is never copied into it.
  tenant_secret_ref := 'tenant-env://' || p_runtime_key || '/GEMINI_API_KEY';
  recorded := admira.record_tenant_provider_credential(
    resolved_tenant, 'gemini', 'text', tenant_secret_ref, fingerprint_value, 'operator_pool'
  );
  RETURN recorded;
END;
$$;

CREATE OR REPLACE FUNCTION admira.release_hosted_gemini_trial(
  p_runtime_key text, p_reason text DEFAULT 'operator'
)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE resolved_tenant uuid; changed integer;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_reason NOT IN ('licensed', 'trial_expired', 'suspended', 'cancelled', 'operator', 'replaced') THEN
    RAISE EXCEPTION 'invalid hosted Gemini trial release' USING ERRCODE = '22023';
  END IF;
  SELECT l.tenant_id INTO resolved_tenant
  FROM admira.tenant_runtime_leases l
  WHERE l.runtime_key = p_runtime_key FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 0;
  END IF;
  -- A finalized assignment has a live tenant-facing credential.  Do not
  -- release quota behind the runtime's back while that credential remains
  -- usable; callers must transition lifecycle (the automatic trigger may
  -- still use the internal UUID release function).
  IF EXISTS (
    SELECT 1
    FROM admira.tenant_entitlements e
    JOIN admira.tenant_provider_credentials pc ON pc.tenant_id = e.tenant_id
    WHERE e.tenant_id = resolved_tenant
      AND e.lifecycle_state IN ('pending_claim', 'trial')
      AND pc.provider = 'gemini' AND pc.purpose = 'text'
      AND pc.origin = 'operator_pool' AND pc.status = 'active'
  ) THEN
    RAISE EXCEPTION 'cannot release finalized hosted Gemini trial while tenant remains active'
      USING ERRCODE = '55000';
  END IF;
  changed := admira.release_gemini_trial(resolved_tenant, p_reason);
  RETURN changed;
END;
$$;

REVOKE ALL ON TABLE admira.gemini_pool_projects, admira.gemini_pool_credentials,
  admira.gemini_pool_assignments, admira.gemini_pool_audit_events
  FROM PUBLIC, admira_ingress, admira_runtime, admira_delivery, admira_scheduler,
       admira_recovery, admira_image;
REVOKE ALL ON FUNCTION admira._gemini_pool_audit(uuid, uuid, uuid, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.register_gemini_pool_project(text, integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.register_gemini_pool_credential(uuid, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.assign_gemini_trial(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.release_gemini_trial(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.assign_hosted_gemini_trial(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.finalize_hosted_gemini_trial(text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.release_hosted_gemini_trial(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira._gemini_pool_release_on_state_change() FROM PUBLIC;
GRANT USAGE ON SCHEMA admira TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.register_gemini_pool_project(text, integer, text),
  admira.register_gemini_pool_credential(uuid, text, text, text, text),
  admira.assign_hosted_gemini_trial(text), admira.finalize_hosted_gemini_trial(text, uuid),
  admira.release_hosted_gemini_trial(text, text)
  TO admira_provisioner;

ALTER TABLE admira.gemini_pool_projects OWNER TO admira_control_owner;
ALTER TABLE admira.gemini_pool_credentials OWNER TO admira_control_owner;
ALTER TABLE admira.gemini_pool_assignments OWNER TO admira_control_owner;
ALTER TABLE admira.gemini_pool_audit_events OWNER TO admira_control_owner;
ALTER FUNCTION admira._gemini_pool_audit(uuid, uuid, uuid, text, jsonb) OWNER TO admira_control_owner;
ALTER FUNCTION admira.register_gemini_pool_project(text, integer, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.register_gemini_pool_credential(uuid, text, text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.assign_gemini_trial(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.release_gemini_trial(uuid, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.assign_hosted_gemini_trial(text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.finalize_hosted_gemini_trial(text, uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.release_hosted_gemini_trial(text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira._gemini_pool_release_on_state_change() OWNER TO admira_control_owner;

COMMENT ON TABLE admira.gemini_pool_projects IS 'Operator Gemini project metadata; capacity/quota is counted per project.';
COMMENT ON TABLE admira.gemini_pool_credentials IS 'Secret references, fingerprints and key kind only; raw API keys never enter PostgreSQL.';
COMMENT ON TABLE admira.gemini_pool_assignments IS 'Active operator-pool assignments for trial/pending tenants; released on licensing or suspension.';

COMMIT;
