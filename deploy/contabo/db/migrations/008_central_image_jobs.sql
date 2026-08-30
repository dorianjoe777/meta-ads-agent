-- Durable central image-job ledger.
--
-- This stores job state and opaque artifact metadata only.  Prompts, provider
-- credentials, and provider responses never belong in this ledger.  A job is
-- idempotent within a tenant by (tenant_id, request_id); retries are fenced by
-- a per-claim lease token.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:008_central_image_jobs', 0));

CREATE TABLE IF NOT EXISTS admira.central_image_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  request_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 20),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  leased_until timestamptz,
  output_ref text,
  output_sha256 text,
  output_size_bytes bigint,
  output_mime text,
  error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT central_image_jobs_tenant_request_uq UNIQUE (tenant_id, request_id),
  CHECK (output_ref IS NULL OR output_ref ~ '^[a-f0-9]{32,64}\.(png|jpg|jpeg|webp)$'),
  CHECK (output_sha256 IS NULL OR output_sha256 ~ '^[a-f0-9]{64}$'),
  CHECK (output_size_bytes IS NULL OR output_size_bytes BETWEEN 1 AND 20971520),
  CHECK (output_mime IS NULL OR output_mime IN ('image/png', 'image/jpeg', 'image/webp')),
  CHECK (error_code IS NULL OR error_code IN ('provider_failed', 'provider_unavailable', 'provider_timeout',
                                               'output_invalid', 'output_too_large',
                                               'lease_expired', 'internal_error')),
  CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
  CHECK (status = 'succeeded' OR output_ref IS NULL),
  CHECK (status <> 'succeeded' OR (output_ref IS NOT NULL AND output_sha256 IS NOT NULL
                                  AND output_size_bytes IS NOT NULL AND output_mime IS NOT NULL
                                  AND finished_at IS NOT NULL)),
  CHECK (status <> 'running' OR (lease_token IS NOT NULL AND leased_until IS NOT NULL
                                 AND started_at IS NOT NULL)),
  CHECK (status <> 'failed' OR (finished_at IS NOT NULL OR attempt_count < max_attempts))
);

CREATE INDEX IF NOT EXISTS central_image_jobs_claim_idx
  ON admira.central_image_jobs (available_at, created_at, id)
  WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS central_image_jobs_tenant_created_idx
  ON admira.central_image_jobs (tenant_id, created_at DESC);

COMMENT ON TABLE admira.central_image_jobs IS
  'Durable central image jobs; request and artifact references are opaque and provider secrets are forbidden.';
COMMENT ON COLUMN admira.central_image_jobs.output_ref IS
  'Relative opaque artifact reference only; never an absolute path or path containing . or .. segments.';
COMMENT ON COLUMN admira.central_image_jobs.error_code IS
  'Safe allow-listed error code only; exception text and secrets are never stored.';

ALTER TABLE admira.central_image_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.central_image_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS central_image_jobs_tenant_isolation ON admira.central_image_jobs;
CREATE POLICY central_image_jobs_tenant_isolation ON admira.central_image_jobs
  USING (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

-- The central image service knows the runtime key, not a tenant UUID.  This is
-- the sole enqueue/lease boundary: it resolves the exact runtime lease row,
-- checks entitlement, and atomically creates or claims the job.
CREATE OR REPLACE FUNCTION admira.begin_central_image_job_for_runtime(
  p_runtime_key text, p_request_id uuid, p_max_attempts integer DEFAULT 3,
  p_lease_seconds integer DEFAULT 300
)
RETURNS TABLE (
  lifecycle_state text, route text, job_id uuid, request_id uuid,
  status text, attempt_count integer, lease_token uuid, leased_until timestamptz,
  output_ref text, output_sha256 text, output_size_bytes bigint, output_mime text,
  error_code text
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE
  resolved_tenant uuid;
  access record;
  existing admira.central_image_jobs%ROWTYPE;
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_request_id IS NULL OR p_max_attempts NOT BETWEEN 1 AND 20
     OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid central image runtime request' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant
  FROM admira.tenant_runtime_leases AS runtime
  JOIN admira.tenants AS t ON t.id = runtime.tenant_id
  WHERE runtime.runtime_key = p_runtime_key AND t.status = 'active'
  FOR UPDATE OF runtime;
  IF resolved_tenant IS NULL THEN
    RAISE EXCEPTION 'runtime tenant is not active' USING ERRCODE = '55000';
  END IF;
  SELECT * INTO access FROM admira.resolve_tenant_image_access(resolved_tenant);
  IF NOT FOUND THEN
    RAISE EXCEPTION 'tenant entitlement is unavailable' USING ERRCODE = '55000';
  END IF;
  lifecycle_state := access.lifecycle_state;
  route := access.route;
  IF route IS DISTINCT FROM 'central_sponsored' THEN
    RETURN NEXT;
    RETURN;
  END IF;
  INSERT INTO admira.central_image_jobs (tenant_id, request_id, max_attempts)
  VALUES (resolved_tenant, p_request_id, p_max_attempts)
  ON CONFLICT ON CONSTRAINT central_image_jobs_tenant_request_uq DO NOTHING;
  SELECT j.* INTO existing FROM admira.central_image_jobs AS j
  WHERE j.tenant_id = resolved_tenant AND j.request_id = p_request_id
  FOR UPDATE;
  IF existing.status = 'running' AND existing.leased_until > now() THEN
    job_id := existing.id; request_id := existing.request_id; status := existing.status;
    attempt_count := existing.attempt_count; output_ref := existing.output_ref;
    output_sha256 := existing.output_sha256; output_size_bytes := existing.output_size_bytes;
    output_mime := existing.output_mime; error_code := existing.error_code;
    RETURN NEXT; RETURN;
  END IF;
  IF existing.status IN ('succeeded', 'failed') THEN
    job_id := existing.id; request_id := existing.request_id; status := existing.status;
    attempt_count := existing.attempt_count; output_ref := existing.output_ref;
    output_sha256 := existing.output_sha256; output_size_bytes := existing.output_size_bytes;
    output_mime := existing.output_mime; error_code := existing.error_code;
    RETURN NEXT; RETURN;
  END IF;
  IF existing.status = 'queued' AND existing.available_at > now() THEN
    job_id := existing.id; request_id := existing.request_id; status := existing.status;
    attempt_count := existing.attempt_count; error_code := existing.error_code;
    RETURN NEXT; RETURN;
  END IF;
  IF existing.attempt_count >= existing.max_attempts THEN
    UPDATE admira.central_image_jobs SET status = 'failed', error_code = 'lease_expired',
      lease_token = NULL, leased_until = NULL, finished_at = coalesce(finished_at, now()), updated_at = now()
    WHERE id = existing.id;
    status := 'failed'; attempt_count := existing.attempt_count; error_code := 'lease_expired';
  ELSE
    UPDATE admira.central_image_jobs AS j
    SET status = 'running', attempt_count = j.attempt_count + 1,
        lease_token = gen_random_uuid(), leased_until = now() + make_interval(secs => p_lease_seconds),
        started_at = coalesce(j.started_at, now()), updated_at = now()
    WHERE j.id = existing.id
    RETURNING j.id, j.request_id, j.status, j.attempt_count, j.lease_token,
      j.leased_until, j.output_ref, j.output_sha256, j.output_size_bytes,
      j.output_mime, j.error_code
    INTO job_id, request_id, status, attempt_count, lease_token, leased_until,
      output_ref, output_sha256, output_size_bytes, output_mime, error_code;
  END IF;
  IF job_id IS NULL THEN job_id := existing.id; request_id := existing.request_id; END IF;
  RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION admira.complete_central_image_job(
  p_job_id uuid, p_lease_token uuid, p_output_ref text,
  p_output_sha256 text, p_output_size_bytes bigint, p_output_mime text
)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  IF p_job_id IS NULL OR p_lease_token IS NULL
     OR p_output_ref !~ '^[a-f0-9]{32,64}\.(png|jpg|jpeg|webp)$'
     OR p_output_sha256 !~ '^[a-f0-9]{64}$'
     OR p_output_size_bytes IS NULL OR p_output_size_bytes NOT BETWEEN 1 AND 20971520
     OR p_output_mime NOT IN ('image/png', 'image/jpeg', 'image/webp') THEN
    RAISE EXCEPTION 'invalid central image output metadata' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.central_image_jobs
  SET status = 'succeeded', output_ref = p_output_ref,
      output_sha256 = p_output_sha256, output_size_bytes = p_output_size_bytes,
      output_mime = p_output_mime, error_code = NULL,
      lease_token = NULL, leased_until = NULL, finished_at = now(), updated_at = now()
  WHERE id = p_job_id AND status = 'running' AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.fail_central_image_job(
  p_job_id uuid, p_lease_token uuid, p_error_code text,
  p_retry_after_seconds integer DEFAULT 30
)
RETURNS TABLE (status text, attempt_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE next_status text; changed integer;
BEGIN
  IF p_job_id IS NULL OR p_lease_token IS NULL
     OR p_error_code NOT IN ('provider_failed', 'provider_unavailable', 'provider_timeout',
                             'output_invalid', 'output_too_large',
                             'lease_expired', 'internal_error')
     OR p_retry_after_seconds NOT BETWEEN 1 AND 86400 THEN
    RAISE EXCEPTION 'invalid central image failure' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.central_image_jobs AS j
  SET status = CASE WHEN j.attempt_count < j.max_attempts THEN 'queued' ELSE 'failed' END,
      error_code = p_error_code,
      available_at = CASE WHEN j.attempt_count < j.max_attempts
                          THEN now() + make_interval(secs => p_retry_after_seconds)
                          ELSE j.available_at END,
      lease_token = NULL, leased_until = NULL,
      finished_at = CASE WHEN j.attempt_count < j.max_attempts THEN NULL ELSE now() END,
      updated_at = now()
  WHERE j.id = p_job_id AND j.status = 'running' AND j.lease_token = p_lease_token
  RETURNING j.status, j.attempt_count INTO next_status, attempt_count;
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed = 1 THEN
    status := next_status;
    RETURN NEXT;
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_image') THEN
    CREATE ROLE admira_image NOLOGIN;
  END IF;
END;
$$;
ALTER ROLE admira_image NOLOGIN NOBYPASSRLS;
ALTER TABLE admira.central_image_jobs OWNER TO admira_control_owner;
REVOKE ALL ON TABLE admira.central_image_jobs FROM PUBLIC, admira_image, admira_runtime;
GRANT USAGE ON SCHEMA admira TO admira_image;
REVOKE ALL ON FUNCTION admira.begin_central_image_job_for_runtime(text, uuid, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.complete_central_image_job(uuid, uuid, text, text, bigint, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.fail_central_image_job(uuid, uuid, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.begin_central_image_job_for_runtime(text, uuid, integer, integer),
  admira.complete_central_image_job(uuid, uuid, text, text, bigint, text),
  admira.fail_central_image_job(uuid, uuid, text, integer) TO admira_image;
ALTER FUNCTION admira.begin_central_image_job_for_runtime(text, uuid, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.complete_central_image_job(uuid, uuid, text, text, bigint, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.fail_central_image_job(uuid, uuid, text, integer) OWNER TO admira_control_owner;

-- Remove the pre-release global claim API if this migration had been applied
-- during an earlier iteration.  Runtime-keyed begin is the only claim path.
DROP FUNCTION IF EXISTS admira.claim_central_image_jobs(text, integer, integer);
DROP FUNCTION IF EXISTS admira.enqueue_central_image_job_for_runtime(text, uuid, integer);
DROP FUNCTION IF EXISTS admira.enqueue_central_image_job(uuid, uuid, integer);

COMMIT;
