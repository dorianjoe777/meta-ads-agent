-- Durable capacity backpressure and fenced LRU runtime eviction.
--
-- Capacity contention is not a failed buyer turn. Claiming an inbox row still
-- increments attempt_count for crash recovery, so the capacity defer function
-- reverses that increment and records a separate capacity_deferrals metric.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:006_runtime_capacity_queue', 0));

ALTER TABLE admira.tenant_telegram_updates
  ADD COLUMN IF NOT EXISTS capacity_deferrals integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_capacity_deferred_at timestamptz;

ALTER TABLE admira.tenant_scheduled_job_runs
  ADD COLUMN IF NOT EXISTS capacity_deferrals integer NOT NULL DEFAULT 0;

ALTER TABLE admira.tenant_telegram_updates
  DROP CONSTRAINT IF EXISTS tenant_telegram_updates_capacity_deferrals_check;
ALTER TABLE admira.tenant_telegram_updates
  ADD CONSTRAINT tenant_telegram_updates_capacity_deferrals_check
  CHECK (capacity_deferrals >= 0);

ALTER TABLE admira.tenant_scheduled_job_runs
  DROP CONSTRAINT IF EXISTS tenant_scheduled_job_runs_capacity_deferrals_check;
ALTER TABLE admira.tenant_scheduled_job_runs
  ADD CONSTRAINT tenant_scheduled_job_runs_capacity_deferrals_check
  CHECK (capacity_deferrals >= 0);

CREATE INDEX IF NOT EXISTS tenant_telegram_updates_capacity_idx
  ON admira.tenant_telegram_updates (status, available_at, capacity_deferrals)
  WHERE status = 'retry';

CREATE OR REPLACE FUNCTION admira.defer_telegram_update_capacity(
  p_update_row_id uuid,
  p_lease_token uuid,
  p_error_code text DEFAULT 'tenant_busy',
  p_retry_after_seconds integer DEFAULT 2
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  deferred_tenant uuid;
  deferral_count integer;
BEGIN
  IF p_retry_after_seconds NOT BETWEEN 1 AND 86400
     OR p_error_code NOT IN (
       'tenant_busy', 'runtime_capacity_exhausted', 'runtime_capacity_headroom_low'
     ) THEN
    RAISE EXCEPTION 'invalid capacity deferral' USING ERRCODE = '22023';
  END IF;

  UPDATE admira.tenant_telegram_updates
  SET status = 'retry',
      available_at = now() + make_interval(secs => p_retry_after_seconds),
      last_error = p_error_code,
      error = p_error_code,
      -- claim_telegram_updates increments this once. Capacity does not spend
      -- the finite execution-failure budget, so reverse exactly that claim.
      attempt_count = greatest(0, attempt_count - 1),
      capacity_deferrals = capacity_deferrals + 1,
      last_capacity_deferred_at = now(),
      lease_token = NULL,
      lease_holder = NULL,
      leased_until = NULL
  WHERE id = p_update_row_id
    AND status = 'processing'
    AND lease_token = p_lease_token
  RETURNING tenant_id, capacity_deferrals
  INTO deferred_tenant, deferral_count;

  IF deferred_tenant IS NOT NULL THEN
    INSERT INTO admira.tenant_audit_events
      (tenant_id, actor_type, event_type, resource_type, resource_id, payload)
    VALUES
      (deferred_tenant, 'system', 'runtime_capacity_deferred',
       'telegram_update', p_update_row_id::text,
       jsonb_build_object(
         'error_code', p_error_code,
         'retry_after_seconds', p_retry_after_seconds,
         'capacity_deferrals', deferral_count
       ));
  END IF;

  RETURN deferred_tenant IS NOT NULL;
END;
$$;

CREATE OR REPLACE FUNCTION admira.defer_scheduled_job_capacity(
  p_job_id uuid,
  p_run_id uuid,
  p_lease_token uuid,
  p_error_code text DEFAULT 'tenant_busy',
  p_retry_after_seconds integer DEFAULT 5
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  deferred_tenant uuid;
  deferral_count integer;
  changed integer;
BEGIN
  IF p_retry_after_seconds NOT BETWEEN 1 AND 86400
     OR p_error_code NOT IN (
       'tenant_busy', 'runtime_capacity_exhausted', 'runtime_capacity_headroom_low'
     ) THEN
    RAISE EXCEPTION 'invalid scheduler capacity deferral' USING ERRCODE = '22023';
  END IF;

  SELECT job_run.tenant_id
  INTO deferred_tenant
  FROM admira.tenant_scheduled_job_runs AS job_run
  JOIN admira.tenant_scheduled_jobs AS scheduled_job
    ON scheduled_job.id = job_run.job_id
   AND scheduled_job.tenant_id = job_run.tenant_id
  WHERE job_run.id = p_run_id
    AND job_run.job_id = p_job_id
    AND job_run.lease_token = p_lease_token
    AND scheduled_job.lease_token = p_lease_token
  FOR UPDATE OF job_run, scheduled_job;

  IF deferred_tenant IS NULL THEN
    RETURN false;
  END IF;

  UPDATE admira.tenant_scheduled_job_runs
  SET status = 'queued',
      finished_at = NULL,
      error = p_error_code,
      attempt_count = greatest(0, attempt_count - 1),
      capacity_deferrals = capacity_deferrals + 1,
      lease_token = NULL
  WHERE id = p_run_id
    AND job_id = p_job_id
    AND lease_token = p_lease_token
  RETURNING capacity_deferrals INTO deferral_count;

  UPDATE admira.tenant_scheduled_jobs
  SET leased_until = now() + make_interval(secs => p_retry_after_seconds),
      lease_token = NULL,
      lease_holder = NULL
  WHERE id = p_job_id
    AND tenant_id = deferred_tenant
    AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed <> 1 THEN
    RAISE EXCEPTION 'scheduler lease lost' USING ERRCODE = '40001';
  END IF;

  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, event_type, resource_type, resource_id, payload)
  VALUES
    (deferred_tenant, 'system', 'scheduled_runtime_capacity_deferred',
     'scheduled_job_run', p_run_id::text,
     jsonb_build_object(
       'error_code', p_error_code,
       'retry_after_seconds', p_retry_after_seconds,
       'capacity_deferrals', deferral_count
     ));

  RETURN true;
END;
$$;

-- Remove the pre-release, unfenced signatures if a development database saw
-- an earlier draft of this migration.
DROP FUNCTION IF EXISTS admira.claim_idle_runtime(integer);
DROP FUNCTION IF EXISTS admira.complete_idle_runtime(uuid);
DROP FUNCTION IF EXISTS admira.release_idle_runtime_claim(uuid);

CREATE OR REPLACE FUNCTION admira.claim_idle_runtime(
  p_holder text,
  p_idle_seconds integer DEFAULT 0,
  p_claim_seconds integer DEFAULT 60
)
RETURNS TABLE (tenant_id uuid, runtime_key text, eviction_token uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  claim_holder text;
BEGIN
  claim_holder := 'capacity-evict:' || btrim(coalesce(p_holder, ''));
  IF btrim(coalesce(p_holder, '')) = ''
     OR char_length(p_holder) > 200
     OR p_idle_seconds NOT BETWEEN 0 AND 86400
     OR p_claim_seconds NOT BETWEEN 15 AND 300 THEN
    RAISE EXCEPTION 'invalid idle runtime claim' USING ERRCODE = '22023';
  END IF;

  -- A worker can die after the database claim and before suspend/complete.
  -- Expired fencing claims are recoverable and may be selected again.
  UPDATE admira.tenant_runtime_leases
  SET state = 'running',
      holder = NULL,
      acquired_at = NULL,
      expires_at = NULL,
      lease_token = gen_random_uuid()
  WHERE state = 'stopping'
    AND holder LIKE 'capacity-evict:%'
    AND (expires_at IS NULL OR expires_at < now());

  RETURN QUERY
  WITH candidate AS (
    SELECT runtime.tenant_id
    FROM admira.tenant_runtime_leases AS runtime
    JOIN admira.tenants AS tenant ON tenant.id = runtime.tenant_id
    WHERE tenant.status = 'active'
      AND runtime.state = 'running'
      AND runtime.holder IS NULL
      AND coalesce(runtime.last_heartbeat_at, runtime.updated_at)
          <= now() - make_interval(secs => p_idle_seconds)
      AND NOT EXISTS (
        SELECT 1
        FROM admira.tenant_telegram_updates AS processing_update
        WHERE processing_update.tenant_id = runtime.tenant_id
          AND processing_update.status = 'processing'
          AND processing_update.leased_until >= now()
      )
      AND NOT EXISTS (
        SELECT 1
        FROM admira.tenant_telegram_updates AS queued_update
        WHERE queued_update.tenant_id = runtime.tenant_id
          AND queued_update.status IN ('received', 'retry')
          AND queued_update.available_at <= now()
      )
      AND NOT EXISTS (
        SELECT 1
        FROM admira.tenant_scheduled_jobs AS scheduled_job
        WHERE scheduled_job.tenant_id = runtime.tenant_id
          AND (
            scheduled_job.leased_until >= now()
            OR (
              scheduled_job.enabled
              AND scheduled_job.next_run_at IS NOT NULL
              AND scheduled_job.next_run_at <= now()
            )
          )
      )
    ORDER BY coalesce(runtime.last_heartbeat_at, runtime.updated_at), runtime.tenant_id
    FOR UPDATE OF runtime SKIP LOCKED
    LIMIT 1
  ), marked AS (
    UPDATE admira.tenant_runtime_leases AS runtime
    SET state = 'stopping',
        holder = claim_holder,
        acquired_at = now(),
        expires_at = now() + make_interval(secs => p_claim_seconds),
        lease_token = gen_random_uuid()
    FROM candidate
    WHERE runtime.tenant_id = candidate.tenant_id
      AND runtime.state = 'running'
      AND runtime.holder IS NULL
    RETURNING runtime.tenant_id, runtime.runtime_key, runtime.lease_token
  )
  SELECT marked.tenant_id, marked.runtime_key, marked.lease_token
  FROM marked;
END;
$$;

CREATE OR REPLACE FUNCTION admira.complete_idle_runtime(
  p_tenant_id uuid,
  p_eviction_token uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  changed integer;
BEGIN
  UPDATE admira.tenant_runtime_leases
  SET state = 'stopped',
      holder = NULL,
      acquired_at = NULL,
      expires_at = NULL,
      last_heartbeat_at = now(),
      lease_token = gen_random_uuid()
  WHERE tenant_id = p_tenant_id
    AND state = 'stopping'
    AND holder LIKE 'capacity-evict:%'
    AND lease_token = p_eviction_token
    AND expires_at >= now();
  GET DIAGNOSTICS changed = ROW_COUNT;

  IF changed = 1 THEN
    INSERT INTO admira.tenant_audit_events
      (tenant_id, actor_type, event_type, resource_type, resource_id)
    VALUES
      (p_tenant_id, 'system', 'runtime_idle_evicted', 'runtime', p_tenant_id::text);
  END IF;

  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.release_idle_runtime_claim(
  p_tenant_id uuid,
  p_eviction_token uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE
  changed integer;
BEGIN
  UPDATE admira.tenant_runtime_leases
  SET state = 'running',
      holder = NULL,
      acquired_at = NULL,
      expires_at = NULL,
      lease_token = gen_random_uuid()
  WHERE tenant_id = p_tenant_id
    AND state = 'stopping'
    AND holder LIKE 'capacity-evict:%'
    AND lease_token = p_eviction_token
    AND expires_at >= now();
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

REVOKE ALL ON FUNCTION admira.defer_telegram_update_capacity(uuid, uuid, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.defer_scheduled_job_capacity(uuid, uuid, uuid, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_idle_runtime(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.complete_idle_runtime(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.release_idle_runtime_claim(uuid, uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION admira.defer_telegram_update_capacity(uuid, uuid, text, integer),
  admira.claim_idle_runtime(text, integer, integer),
  admira.complete_idle_runtime(uuid, uuid),
  admira.release_idle_runtime_claim(uuid, uuid)
TO admira_runtime;

GRANT EXECUTE ON FUNCTION admira.defer_scheduled_job_capacity(uuid, uuid, uuid, text, integer)
TO admira_scheduler;

ALTER FUNCTION admira.defer_telegram_update_capacity(uuid, uuid, text, integer)
  OWNER TO admira_control_owner;
ALTER FUNCTION admira.defer_scheduled_job_capacity(uuid, uuid, uuid, text, integer)
  OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_idle_runtime(text, integer, integer)
  OWNER TO admira_control_owner;
ALTER FUNCTION admira.complete_idle_runtime(uuid, uuid)
  OWNER TO admira_control_owner;
ALTER FUNCTION admira.release_idle_runtime_claim(uuid, uuid)
  OWNER TO admira_control_owner;

COMMIT;
