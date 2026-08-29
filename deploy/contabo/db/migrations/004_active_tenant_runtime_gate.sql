-- Keep suspended/deleted tenants out of runtime and scheduler dispatch.
--
-- Telegram resolution already rejects inactive tenants, but an update or job
-- queued before suspension could otherwise wake the tenant later.  These
-- SECURITY DEFINER functions remain the only worker-facing claim/lease path.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:004_active_tenant_runtime_gate', 0));

CREATE OR REPLACE FUNCTION admira.claim_telegram_updates(
  p_worker_id text,
  p_limit integer DEFAULT 10,
  p_lease_seconds integer DEFAULT 360
)
RETURNS TABLE (
  update_row_id uuid, tenant_id uuid, runtime_key text, bot_id text, update_id bigint,
  telegram_chat_id text, telegram_user_id text, payload jsonb,
  attempt_count integer, lease_token uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
#variable_conflict use_column
BEGIN
  IF btrim(coalesce(p_worker_id, '')) = '' OR p_limit NOT BETWEEN 1 AND 100
     OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid update claim' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  WITH picked AS (
    SELECT u.id
    FROM admira.tenant_telegram_updates AS u
    JOIN admira.tenant_runtime_leases AS runtime ON runtime.tenant_id = u.tenant_id
    JOIN admira.tenants AS tenant ON tenant.id = u.tenant_id
    WHERE tenant.status = 'active'
      AND ((u.status IN ('received', 'retry') AND u.available_at <= now())
           OR (u.status = 'processing' AND (u.leased_until IS NULL OR u.leased_until < now())))
      AND NOT EXISTS (
        SELECT 1 FROM admira.tenant_telegram_updates AS active
        WHERE active.tenant_id = u.tenant_id AND active.id <> u.id
          AND active.status = 'processing' AND active.leased_until >= now())
      AND NOT EXISTS (
        SELECT 1 FROM admira.tenant_telegram_updates AS earlier
        WHERE earlier.tenant_id = u.tenant_id AND earlier.id <> u.id
          AND ((earlier.status IN ('received', 'retry') AND earlier.available_at <= now())
               OR (earlier.status = 'processing' AND (earlier.leased_until IS NULL OR earlier.leased_until < now())))
          AND (earlier.available_at, earlier.received_at, earlier.id) < (u.available_at, u.received_at, u.id))
    ORDER BY u.available_at, u.received_at
    FOR UPDATE OF u SKIP LOCKED
    LIMIT p_limit
  ), claimed AS (
    UPDATE admira.tenant_telegram_updates AS u
    SET status = 'processing', attempt_count = u.attempt_count + 1,
        lease_token = gen_random_uuid(), lease_holder = btrim(p_worker_id),
        leased_until = now() + make_interval(secs => p_lease_seconds)
    FROM picked WHERE u.id = picked.id
    RETURNING u.id, u.tenant_id, u.bot_id, u.update_id, u.telegram_chat_id,
              u.telegram_user_id, u.payload, u.attempt_count, u.lease_token
  ) SELECT c.id, c.tenant_id, runtime.runtime_key, c.bot_id, c.update_id,
           c.telegram_chat_id, c.telegram_user_id, c.payload, c.attempt_count, c.lease_token
      FROM claimed AS c JOIN admira.tenant_runtime_leases AS runtime ON runtime.tenant_id = c.tenant_id;
END;
$$;

CREATE OR REPLACE FUNCTION admira.claim_due_scheduled_jobs(
  p_worker_id text, p_limit integer DEFAULT 10, p_lease_seconds integer DEFAULT 600
)
RETURNS TABLE (
  job_id uuid, tenant_id uuid, runtime_key text, job_key text, payload jsonb,
  scheduled_for timestamptz, run_id uuid, attempt_count integer, lease_token uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
#variable_conflict use_column
BEGIN
  IF btrim(coalesce(p_worker_id, '')) = '' OR p_limit NOT BETWEEN 1 AND 100
     OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid scheduler claim' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  WITH picked AS (
    SELECT j.id FROM admira.tenant_scheduled_jobs AS j
    JOIN admira.tenant_runtime_leases AS runtime ON runtime.tenant_id = j.tenant_id
    JOIN admira.tenants AS tenant ON tenant.id = j.tenant_id
    WHERE tenant.status = 'active'
      AND j.enabled AND j.next_run_at IS NOT NULL AND j.next_run_at <= now()
      AND (j.leased_until IS NULL OR j.leased_until < now())
    ORDER BY j.next_run_at, j.id FOR UPDATE OF j SKIP LOCKED LIMIT p_limit
  ), claimed AS (
    UPDATE admira.tenant_scheduled_jobs AS j
    SET lease_token = gen_random_uuid(), lease_holder = btrim(p_worker_id),
        leased_until = now() + make_interval(secs => p_lease_seconds)
    FROM picked WHERE j.id = picked.id
    RETURNING j.id, j.tenant_id, j.job_key, j.payload, j.next_run_at, j.lease_token
  ), runs AS (
    INSERT INTO admira.tenant_scheduled_job_runs
      (tenant_id, job_id, run_key, scheduled_for, status, started_at, attempt_count, lease_token)
    SELECT c.tenant_id, c.id,
      to_char(c.next_run_at AT TIME ZONE 'UTC', 'YYYYMMDD"T"HH24MISS.MS"Z"'),
      c.next_run_at, 'running', now(), 1, c.lease_token
    FROM claimed AS c
    ON CONFLICT (tenant_id, job_id, run_key) DO UPDATE
      SET status = 'running', started_at = now(), finished_at = NULL,
          attempt_count = admira.tenant_scheduled_job_runs.attempt_count + 1,
          lease_token = EXCLUDED.lease_token
    RETURNING id, tenant_id, job_id, scheduled_for, attempt_count, lease_token
  )
  SELECT c.id, c.tenant_id, runtime.runtime_key, c.job_key, c.payload, c.next_run_at,
         r.id, r.attempt_count, c.lease_token
  FROM claimed AS c JOIN runs AS r
    ON r.job_id = c.id AND r.tenant_id = c.tenant_id AND r.scheduled_for = c.next_run_at
  JOIN admira.tenant_runtime_leases AS runtime ON runtime.tenant_id = c.tenant_id;
END;
$$;

CREATE OR REPLACE FUNCTION admira.acquire_runtime_lease(
  p_tenant_id uuid, p_holder text, p_lease_seconds integer DEFAULT 600
)
RETURNS TABLE (lease_token uuid, acquired boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE token uuid;
BEGIN
  IF p_tenant_id IS NULL OR btrim(coalesce(p_holder, '')) = ''
     OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid runtime lease' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.tenant_runtime_leases AS runtime
  SET state = 'running', holder = btrim(p_holder), acquired_at = now(),
      expires_at = now() + make_interval(secs => p_lease_seconds),
      last_heartbeat_at = now(), lease_token = gen_random_uuid()
  WHERE runtime.tenant_id = p_tenant_id
    AND EXISTS (
      SELECT 1 FROM admira.tenants AS tenant
      WHERE tenant.id = p_tenant_id AND tenant.status = 'active'
    )
    AND (runtime.expires_at IS NULL OR runtime.expires_at < now()
         OR runtime.state IN ('stopped', 'failed'))
  RETURNING runtime.lease_token INTO token;
  IF token IS NULL THEN RETURN QUERY SELECT NULL::uuid, false;
  ELSE RETURN QUERY SELECT token, true; END IF;
END;
$$;

REVOKE ALL ON FUNCTION admira.claim_telegram_updates(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_due_scheduled_jobs(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.acquire_runtime_lease(uuid, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.claim_telegram_updates(text, integer, integer),
  admira.acquire_runtime_lease(uuid, text, integer) TO admira_runtime;
GRANT EXECUTE ON FUNCTION admira.claim_due_scheduled_jobs(text, integer, integer),
  admira.acquire_runtime_lease(uuid, text, integer) TO admira_scheduler;
ALTER FUNCTION admira.claim_telegram_updates(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_due_scheduled_jobs(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.acquire_runtime_lease(uuid, text, integer) OWNER TO admira_control_owner;

COMMIT;
