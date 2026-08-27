-- Admira hosted Telegram control plane (PostgreSQL 15+)
--
-- Extends the durable update ledger created by 001 instead of introducing a
-- second inbox. Bot credentials never enter PostgreSQL: bot_id is a public,
-- non-secret routing identifier. Every service receives EXECUTE on a narrow
-- SECURITY DEFINER API and no direct table privileges.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:002_telegram_ingress_control', 0));

ALTER TABLE admira.tenant_telegram_updates
  ADD COLUMN IF NOT EXISTS telegram_chat_id text,
  ADD COLUMN IF NOT EXISTS telegram_user_id text,
  ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_holder text,
  ADD COLUMN IF NOT EXISTS leased_until timestamptz,
  ADD COLUMN IF NOT EXISTS last_error text;

ALTER TABLE admira.tenant_telegram_updates
  DROP CONSTRAINT IF EXISTS tenant_telegram_updates_status_check;
ALTER TABLE admira.tenant_telegram_updates
  ADD CONSTRAINT tenant_telegram_updates_status_check
  CHECK (status IN ('received', 'processing', 'processed', 'retry', 'failed', 'dead'));

ALTER TABLE admira.tenant_telegram_updates
  DROP CONSTRAINT IF EXISTS tenant_telegram_updates_attempt_count_check;
ALTER TABLE admira.tenant_telegram_updates
  ADD CONSTRAINT tenant_telegram_updates_attempt_count_check
  CHECK (attempt_count >= 0);

CREATE INDEX IF NOT EXISTS tenant_telegram_updates_claim_v2_idx
  ON admira.tenant_telegram_updates (status, available_at, received_at);
CREATE INDEX IF NOT EXISTS tenant_telegram_updates_active_tenant_idx
  ON admira.tenant_telegram_updates (tenant_id, leased_until)
  WHERE status = 'processing';

-- Long-poll offsets are global to one Telegram bot, not buyer state. This
-- table contains no credential and is reachable only through the functions
-- below, so an unbound update cannot wedge the polling cursor forever.
CREATE TABLE IF NOT EXISTS admira.telegram_ingress_cursors (
  bot_id text PRIMARY KEY CHECK (btrim(bot_id) <> ''),
  next_update_id bigint NOT NULL DEFAULT 0 CHECK (next_update_id >= 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admira.tenant_telegram_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  bot_id text NOT NULL CHECK (btrim(bot_id) <> ''),
  telegram_chat_id text NOT NULL CHECK (btrim(telegram_chat_id) <> ''),
  source_update_id uuid REFERENCES admira.tenant_telegram_updates(id) ON DELETE SET NULL,
  source_job_run_id uuid REFERENCES admira.tenant_scheduled_job_runs(id) ON DELETE SET NULL,
  sequence_no integer NOT NULL CHECK (sequence_no >= 0),
  kind text NOT NULL CHECK (kind IN ('text', 'photo', 'video', 'document')),
  body text,
  media_ref text,
  media_sha256 text,
  caption text,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'sending', 'sent', 'retry', 'failed', 'dead')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  lease_holder text,
  leased_until timestamptz,
  telegram_message_id bigint,
  dispatch_order bigserial NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  last_error text,
  CHECK ((kind = 'text' AND body IS NOT NULL AND media_ref IS NULL)
      OR (kind <> 'text' AND media_ref IS NOT NULL AND body IS NULL)),
  CHECK (body IS NULL OR char_length(body) BETWEEN 1 AND 4000),
  CHECK (caption IS NULL OR char_length(caption) <= 1024),
  CHECK (media_ref IS NULL OR media_ref ~ '^[a-f0-9]{32,64}\.(jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$'),
  CHECK (media_sha256 IS NULL OR media_sha256 ~ '^[a-f0-9]{64}$'),
  UNIQUE (source_update_id, sequence_no),
  UNIQUE (source_job_run_id, sequence_no)
);

CREATE INDEX IF NOT EXISTS tenant_telegram_outbox_claim_idx
  ON admira.tenant_telegram_outbox (status, available_at, created_at);
CREATE INDEX IF NOT EXISTS tenant_telegram_outbox_chat_order_idx
  ON admira.tenant_telegram_outbox (bot_id, telegram_chat_id, dispatch_order);
CREATE INDEX IF NOT EXISTS tenant_telegram_outbox_tenant_idx
  ON admira.tenant_telegram_outbox (tenant_id, created_at DESC);

ALTER TABLE admira.tenant_scheduled_jobs
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_holder text,
  ADD COLUMN IF NOT EXISTS leased_until timestamptz;
ALTER TABLE admira.tenant_scheduled_job_runs
  ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS lease_token uuid;

CREATE INDEX IF NOT EXISTS tenant_scheduled_jobs_claim_idx
  ON admira.tenant_scheduled_jobs (next_run_at, id)
  WHERE enabled AND next_run_at IS NOT NULL;

ALTER TABLE admira.tenant_telegram_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_telegram_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_telegram_outbox;
CREATE POLICY tenant_isolation ON admira.tenant_telegram_outbox
  USING (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

COMMENT ON TABLE admira.telegram_ingress_cursors IS 'Non-secret long-poll cursor per shared Telegram bot.';
COMMENT ON TABLE admira.tenant_telegram_outbox IS 'Ordered Telegram delivery queue; media_ref is an opaque spool key, never a tenant or host path.';
COMMENT ON COLUMN admira.tenant_telegram_updates.lease_token IS 'Fencing token for one durable runtime turn claim.';

CREATE OR REPLACE FUNCTION admira.resolve_telegram_chat(
  p_bot_id text,
  p_chat_id text,
  p_user_id text
)
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
  SELECT b.tenant_id
  FROM admira.tenant_telegram_bindings AS b
  JOIN admira.tenants AS t ON t.id = b.tenant_id
  WHERE b.bot_id = btrim(p_bot_id)
    AND b.telegram_chat_id = btrim(p_chat_id)
    AND b.telegram_user_id = btrim(p_user_id)
    AND t.status = 'active'
  ORDER BY b.is_primary DESC, b.created_at ASC
  LIMIT 1
$$;

CREATE OR REPLACE FUNCTION admira.get_telegram_ingress_cursor(p_bot_id text)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
  SELECT coalesce((SELECT c.next_update_id FROM admira.telegram_ingress_cursors AS c
                   WHERE c.bot_id = btrim(p_bot_id)), 0::bigint)
$$;

CREATE OR REPLACE FUNCTION admira.advance_telegram_ingress_cursor(p_bot_id text, p_next_update_id bigint)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE advanced bigint;
BEGIN
  IF btrim(coalesce(p_bot_id, '')) = '' OR p_next_update_id IS NULL OR p_next_update_id < 0 THEN
    RAISE EXCEPTION 'invalid telegram cursor' USING ERRCODE = '22023';
  END IF;
  INSERT INTO admira.telegram_ingress_cursors (bot_id, next_update_id)
  VALUES (btrim(p_bot_id), p_next_update_id)
  ON CONFLICT (bot_id) DO UPDATE
    SET next_update_id = greatest(admira.telegram_ingress_cursors.next_update_id, EXCLUDED.next_update_id),
        updated_at = now()
  RETURNING next_update_id INTO advanced;
  RETURN advanced;
END;
$$;

CREATE OR REPLACE FUNCTION admira.ingest_telegram_update(
  p_bot_id text,
  p_update_id bigint,
  p_chat_id text,
  p_user_id text,
  p_payload jsonb DEFAULT '{}'::jsonb
)
RETURNS TABLE (update_row_id uuid, tenant_id uuid, inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid; stored_id uuid; stored_tenant uuid;
BEGIN
  IF btrim(coalesce(p_bot_id, '')) = '' OR p_update_id IS NULL OR p_update_id < 0
     OR btrim(coalesce(p_chat_id, '')) = '' OR btrim(coalesce(p_user_id, '')) = ''
     OR octet_length(coalesce(p_payload, '{}'::jsonb)::text) > 262144 THEN
    RAISE EXCEPTION 'invalid telegram update' USING ERRCODE = '22023';
  END IF;
  SELECT r.tenant_id INTO resolved_tenant
  FROM admira.resolve_telegram_chat(p_bot_id, p_chat_id, p_user_id) AS r;
  IF resolved_tenant IS NULL THEN RETURN; END IF;
  INSERT INTO admira.tenant_telegram_updates
    (tenant_id, bot_id, update_id, telegram_chat_id, telegram_user_id, payload, status)
  VALUES
    (resolved_tenant, btrim(p_bot_id), p_update_id, btrim(p_chat_id), btrim(p_user_id), coalesce(p_payload, '{}'::jsonb), 'received')
  ON CONFLICT (bot_id, update_id) DO NOTHING
  RETURNING id, admira.tenant_telegram_updates.tenant_id INTO stored_id, stored_tenant;
  IF stored_id IS NOT NULL THEN
    RETURN QUERY SELECT stored_id, stored_tenant, true;
    RETURN;
  END IF;
  SELECT u.id, u.tenant_id INTO stored_id, stored_tenant
  FROM admira.tenant_telegram_updates AS u
  WHERE u.bot_id = btrim(p_bot_id) AND u.update_id = p_update_id;
  RETURN QUERY SELECT stored_id, stored_tenant, false;
END;
$$;

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
    WHERE ((u.status IN ('received', 'retry') AND u.available_at <= now())
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

CREATE OR REPLACE FUNCTION admira._enqueue_telegram_parts(
  p_tenant_id uuid, p_bot_id text, p_chat_id text, p_text text, p_media jsonb,
  p_source_update_id uuid, p_source_job_run_id uuid
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE pos integer := 1; seq integer := 0; chunk text; item jsonb; media_count integer := 0;
BEGIN
  IF p_tenant_id IS NULL OR btrim(coalesce(p_bot_id, '')) = '' OR btrim(coalesce(p_chat_id, '')) = ''
     OR jsonb_typeof(coalesce(p_media, '[]'::jsonb)) <> 'array' THEN
    RAISE EXCEPTION 'invalid telegram response' USING ERRCODE = '22023';
  END IF;
  media_count := jsonb_array_length(coalesce(p_media, '[]'::jsonb));
  IF media_count > 8 THEN
    RAISE EXCEPTION 'too many telegram media items' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings AS b
    WHERE b.tenant_id = p_tenant_id AND b.bot_id = btrim(p_bot_id)
      AND b.telegram_chat_id = btrim(p_chat_id)) THEN
    RAISE EXCEPTION 'telegram binding does not match tenant' USING ERRCODE = '28000';
  END IF;
  IF octet_length(coalesce(p_text, '')) > 262144 THEN
    RAISE EXCEPTION 'telegram response too large' USING ERRCODE = '22023';
  END IF;
  WHILE pos <= char_length(coalesce(p_text, '')) LOOP
    chunk := substr(p_text, pos, 4000);
    INSERT INTO admira.tenant_telegram_outbox
      (tenant_id, bot_id, telegram_chat_id, source_update_id, source_job_run_id,
       sequence_no, kind, body)
    VALUES (p_tenant_id, btrim(p_bot_id), btrim(p_chat_id), p_source_update_id,
            p_source_job_run_id, seq, 'text', chunk);
    pos := pos + char_length(chunk); seq := seq + 1;
  END LOOP;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_media, '[]'::jsonb)) LOOP
    IF coalesce(item->>'kind', '') NOT IN ('photo', 'video', 'document')
       OR coalesce(item->>'ref', '') !~ '^[a-f0-9]{32,64}\.(jpg|jpeg|png|webp|gif|mp4|mov|pdf|bin)$'
       OR char_length(coalesce(item->>'caption', '')) > 1024
       OR (coalesce(item->>'sha256', '') <> '' AND coalesce(item->>'sha256', '') !~ '^[a-f0-9]{64}$') THEN
      RAISE EXCEPTION 'invalid telegram media reference' USING ERRCODE = '22023';
    END IF;
    INSERT INTO admira.tenant_telegram_outbox
      (tenant_id, bot_id, telegram_chat_id, source_update_id, source_job_run_id,
       sequence_no, kind, media_ref, media_sha256, caption)
    VALUES (p_tenant_id, btrim(p_bot_id), btrim(p_chat_id), p_source_update_id,
            p_source_job_run_id, seq, item->>'kind', item->>'ref',
            nullif(item->>'sha256', ''), nullif(item->>'caption', ''));
    seq := seq + 1;
  END LOOP;
  RETURN seq;
END;
$$;

CREATE OR REPLACE FUNCTION admira.complete_telegram_update(
  p_update_row_id uuid, p_lease_token uuid, p_reply_text text DEFAULT '',
  p_media jsonb DEFAULT '[]'::jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE u admira.tenant_telegram_updates%ROWTYPE; queued integer;
BEGIN
  SELECT * INTO u FROM admira.tenant_telegram_updates
  WHERE id = p_update_row_id AND status = 'processing' AND lease_token = p_lease_token
  FOR UPDATE;
  IF NOT FOUND THEN RETURN -1; END IF;
  queued := admira._enqueue_telegram_parts(u.tenant_id, u.bot_id, u.telegram_chat_id,
    coalesce(p_reply_text, ''), coalesce(p_media, '[]'::jsonb), u.id, NULL);
  UPDATE admira.tenant_telegram_updates
  SET status = 'processed', processed_at = now(), error = NULL, last_error = NULL,
      lease_token = NULL, lease_holder = NULL, leased_until = NULL
  WHERE id = u.id AND lease_token = p_lease_token;
  RETURN queued;
END;
$$;

CREATE OR REPLACE FUNCTION admira.retry_telegram_update(
  p_update_row_id uuid, p_lease_token uuid, p_error_code text,
  p_retry_after_seconds integer DEFAULT 30, p_max_attempts integer DEFAULT 5
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  IF p_retry_after_seconds NOT BETWEEN 1 AND 86400 OR p_max_attempts NOT BETWEEN 1 AND 20 THEN
    RAISE EXCEPTION 'invalid retry policy' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.tenant_telegram_updates
  SET status = CASE WHEN attempt_count >= p_max_attempts THEN 'dead' ELSE 'retry' END,
      available_at = CASE WHEN attempt_count >= p_max_attempts THEN available_at
                          ELSE now() + make_interval(secs => p_retry_after_seconds) END,
      last_error = left(coalesce(p_error_code, 'runtime_failure'), 160),
      error = left(coalesce(p_error_code, 'runtime_failure'), 160),
      lease_token = NULL, lease_holder = NULL, leased_until = NULL
  WHERE id = p_update_row_id AND status = 'processing' AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.claim_telegram_outbox(
  p_worker_id text, p_limit integer DEFAULT 20, p_lease_seconds integer DEFAULT 120
)
RETURNS TABLE (
  outbox_id uuid, tenant_id uuid, bot_id text, telegram_chat_id text,
  kind text, body text, media_ref text, media_sha256 text, caption text,
  attempt_count integer, lease_token uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
BEGIN
  IF btrim(coalesce(p_worker_id, '')) = '' OR p_limit NOT BETWEEN 1 AND 100
     OR p_lease_seconds NOT BETWEEN 15 AND 1800 THEN
    RAISE EXCEPTION 'invalid outbox claim' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  WITH picked AS (
    SELECT o.id FROM admira.tenant_telegram_outbox AS o
    WHERE ((o.status IN ('queued', 'retry') AND o.available_at <= now())
           OR (o.status = 'sending' AND (o.leased_until IS NULL OR o.leased_until < now())))
      AND NOT EXISTS (
        SELECT 1 FROM admira.tenant_telegram_outbox AS earlier
        WHERE earlier.bot_id = o.bot_id AND earlier.telegram_chat_id = o.telegram_chat_id
          AND earlier.id <> o.id AND earlier.status NOT IN ('sent', 'dead')
          AND earlier.dispatch_order < o.dispatch_order)
    ORDER BY o.available_at, o.created_at
    FOR UPDATE SKIP LOCKED LIMIT p_limit
  ), claimed AS (
    UPDATE admira.tenant_telegram_outbox AS o
    SET status = 'sending', attempt_count = o.attempt_count + 1,
        lease_token = gen_random_uuid(), lease_holder = btrim(p_worker_id),
        leased_until = now() + make_interval(secs => p_lease_seconds)
    FROM picked WHERE o.id = picked.id
    RETURNING o.id, o.tenant_id, o.bot_id, o.telegram_chat_id, o.kind, o.body,
              o.media_ref, o.media_sha256, o.caption, o.attempt_count, o.lease_token
  ) SELECT * FROM claimed;
END;
$$;

CREATE OR REPLACE FUNCTION admira.ack_telegram_outbox(
  p_outbox_id uuid, p_lease_token uuid, p_success boolean,
  p_telegram_message_id bigint DEFAULT NULL, p_error_code text DEFAULT NULL,
  p_retry_after_seconds integer DEFAULT 30, p_max_attempts integer DEFAULT 8
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  IF p_retry_after_seconds NOT BETWEEN 1 AND 86400 OR p_max_attempts NOT BETWEEN 1 AND 20 THEN
    RAISE EXCEPTION 'invalid outbox retry policy' USING ERRCODE = '22023';
  END IF;
  UPDATE admira.tenant_telegram_outbox
  SET status = CASE WHEN p_success THEN 'sent'
                    WHEN attempt_count >= p_max_attempts THEN 'dead' ELSE 'retry' END,
      sent_at = CASE WHEN p_success THEN now() ELSE NULL END,
      telegram_message_id = CASE WHEN p_success THEN p_telegram_message_id ELSE telegram_message_id END,
      last_error = CASE WHEN p_success THEN NULL ELSE left(coalesce(p_error_code, 'delivery_failure'), 160) END,
      available_at = CASE WHEN p_success OR attempt_count >= p_max_attempts THEN available_at
                          ELSE now() + make_interval(secs => p_retry_after_seconds) END,
      lease_token = NULL, lease_holder = NULL, leased_until = NULL
  WHERE id = p_outbox_id AND status = 'sending' AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.sync_hermes_scheduled_jobs(
  p_tenant_id uuid, p_lease_token uuid, p_bot_id text, p_chat_id text, p_jobs jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE item jsonb; seen text[] := ARRAY[]::text[]; synced integer := 0;
BEGIN
  IF p_tenant_id IS NULL OR jsonb_typeof(coalesce(p_jobs, '[]'::jsonb)) <> 'array'
     OR jsonb_array_length(coalesce(p_jobs, '[]'::jsonb)) > 100 THEN
    RAISE EXCEPTION 'invalid cron snapshot' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenant_runtime_leases l
    WHERE l.tenant_id = p_tenant_id AND l.lease_token = p_lease_token
      AND l.state = 'running' AND l.expires_at >= now()) THEN
    RAISE EXCEPTION 'runtime lease does not match tenant' USING ERRCODE = '28000';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings b
    WHERE b.tenant_id = p_tenant_id AND b.bot_id = btrim(p_bot_id)
      AND b.telegram_chat_id = btrim(p_chat_id)) THEN
    RAISE EXCEPTION 'telegram binding does not match tenant' USING ERRCODE = '28000';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_jobs, '[]'::jsonb)) LOOP
    IF coalesce(item->>'id', '') !~ '^[A-Za-z0-9_-]{1,64}$' THEN
      RAISE EXCEPTION 'invalid Hermes cron id' USING ERRCODE = '22023';
    END IF;
    seen := array_append(seen, item->>'id');
    INSERT INTO admira.tenant_scheduled_jobs
      (tenant_id, job_key, job_type, cron_expression, timezone, enabled, next_run_at, payload)
    VALUES
      (p_tenant_id, item->>'id', 'hermes_cron', left(coalesce(item->>'schedule_display', ''), 200),
       left(coalesce(nullif(item->>'timezone', ''), 'UTC'), 100),
       coalesce((item->>'enabled')::boolean, true), nullif(item->>'next_run_at', '')::timestamptz,
       jsonb_build_object('bot_id', btrim(p_bot_id), 'chat_id', btrim(p_chat_id),
                          'name', left(coalesce(item->>'name', ''), 200)))
    ON CONFLICT (tenant_id, job_key) DO UPDATE
      SET cron_expression = EXCLUDED.cron_expression, timezone = EXCLUDED.timezone,
          enabled = EXCLUDED.enabled, next_run_at = EXCLUDED.next_run_at,
          payload = EXCLUDED.payload;
    synced := synced + 1;
  END LOOP;
  UPDATE admira.tenant_scheduled_jobs
  SET enabled = false, next_run_at = NULL
  WHERE tenant_id = p_tenant_id AND job_type = 'hermes_cron'
    AND NOT (job_key = ANY(seen));
  RETURN synced;
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
    WHERE j.enabled AND j.next_run_at IS NOT NULL AND j.next_run_at <= now()
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

CREATE OR REPLACE FUNCTION admira.complete_scheduled_job_run(
  p_job_id uuid, p_run_id uuid, p_lease_token uuid, p_next_run_at timestamptz,
  p_reply_text text DEFAULT '', p_media jsonb DEFAULT '[]'::jsonb,
  p_result jsonb DEFAULT '{}'::jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE j admira.tenant_scheduled_jobs%ROWTYPE; queued integer; run_matches integer;
BEGIN
  PERFORM 1 FROM admira.tenant_scheduled_job_runs
  WHERE id = p_run_id AND job_id = p_job_id AND lease_token = p_lease_token
    AND status = 'running' FOR UPDATE;
  IF NOT FOUND THEN RETURN -1; END IF;
  SELECT * INTO j FROM admira.tenant_scheduled_jobs
  WHERE id = p_job_id AND lease_token = p_lease_token FOR UPDATE;
  IF NOT FOUND THEN RETURN -1; END IF;
  queued := admira._enqueue_telegram_parts(j.tenant_id, j.payload->>'bot_id', j.payload->>'chat_id',
    coalesce(p_reply_text, ''), coalesce(p_media, '[]'::jsonb), NULL, p_run_id);
  UPDATE admira.tenant_scheduled_job_runs
  SET status = 'succeeded', finished_at = now(), error = NULL,
      result = coalesce(p_result, '{}'::jsonb), lease_token = NULL
  WHERE id = p_run_id AND job_id = p_job_id AND lease_token = p_lease_token;
  GET DIAGNOSTICS run_matches = ROW_COUNT;
  IF run_matches <> 1 THEN
    RAISE EXCEPTION 'scheduled run lease lost' USING ERRCODE = '40001';
  END IF;
  UPDATE admira.tenant_scheduled_jobs
  SET next_run_at = p_next_run_at, enabled = p_next_run_at IS NOT NULL,
      lease_token = NULL, lease_holder = NULL, leased_until = NULL
  WHERE id = p_job_id AND lease_token = p_lease_token;
  RETURN queued;
END;
$$;

CREATE OR REPLACE FUNCTION admira.retry_scheduled_job_run(
  p_job_id uuid, p_run_id uuid, p_lease_token uuid, p_error_code text,
  p_retry_after_seconds integer DEFAULT 60, p_max_attempts integer DEFAULT 5
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE attempts integer; changed integer;
BEGIN
  IF p_retry_after_seconds NOT BETWEEN 1 AND 86400 OR p_max_attempts NOT BETWEEN 1 AND 20 THEN
    RAISE EXCEPTION 'invalid scheduler retry policy' USING ERRCODE = '22023';
  END IF;
  SELECT attempt_count INTO attempts FROM admira.tenant_scheduled_job_runs
  WHERE id = p_run_id AND job_id = p_job_id AND lease_token = p_lease_token FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  UPDATE admira.tenant_scheduled_job_runs
  SET status = CASE WHEN attempts >= p_max_attempts THEN 'failed' ELSE 'queued' END,
      finished_at = CASE WHEN attempts >= p_max_attempts THEN now() ELSE NULL END,
      error = left(coalesce(p_error_code, 'scheduler_failure'), 160), lease_token = NULL
  WHERE id = p_run_id;
  UPDATE admira.tenant_scheduled_jobs
  SET enabled = attempts < p_max_attempts,
      leased_until = CASE WHEN attempts >= p_max_attempts THEN NULL
                          ELSE now() + make_interval(secs => p_retry_after_seconds) END,
      lease_token = NULL, lease_holder = NULL
  WHERE id = p_job_id AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
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
  UPDATE admira.tenant_runtime_leases
  SET state = 'running', holder = btrim(p_holder), acquired_at = now(),
      expires_at = now() + make_interval(secs => p_lease_seconds),
      last_heartbeat_at = now(), lease_token = gen_random_uuid()
  WHERE tenant_id = p_tenant_id
    AND (expires_at IS NULL OR expires_at < now() OR state IN ('stopped', 'failed'))
  RETURNING admira.tenant_runtime_leases.lease_token INTO token;
  IF token IS NULL THEN RETURN QUERY SELECT NULL::uuid, false;
  ELSE RETURN QUERY SELECT token, true; END IF;
END;
$$;

CREATE OR REPLACE FUNCTION admira.release_runtime_lease(p_tenant_id uuid, p_lease_token uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  UPDATE admira.tenant_runtime_leases
  SET state = 'running', holder = NULL, acquired_at = NULL, expires_at = NULL,
      last_heartbeat_at = now()
  WHERE tenant_id = p_tenant_id AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.mark_runtime_suspended(p_tenant_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  UPDATE admira.tenant_runtime_leases
  SET state = 'stopped', holder = NULL, acquired_at = NULL, expires_at = NULL,
      last_heartbeat_at = now()
  WHERE tenant_id = p_tenant_id AND holder IS NULL;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.list_idle_runtime_keys(p_idle_seconds integer DEFAULT 900)
RETURNS TABLE (tenant_id uuid, runtime_key text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
  SELECT l.tenant_id, l.runtime_key FROM admira.tenant_runtime_leases AS l
  JOIN admira.tenants AS t ON t.id = l.tenant_id
  WHERE t.status = 'active' AND l.state = 'running'
    AND coalesce(l.expires_at, l.last_heartbeat_at, l.updated_at)
        < now() - make_interval(secs => greatest(60, least(p_idle_seconds, 86400)))
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_control_owner') THEN CREATE ROLE admira_control_owner NOLOGIN BYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_ingress') THEN CREATE ROLE admira_ingress NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_runtime') THEN CREATE ROLE admira_runtime NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_delivery') THEN CREATE ROLE admira_delivery NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_scheduler') THEN CREATE ROLE admira_scheduler NOLOGIN; END IF;
END;
$$;

ALTER ROLE admira_control_owner NOLOGIN BYPASSRLS;
GRANT USAGE ON SCHEMA admira TO admira_control_owner;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA admira TO admira_control_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA admira TO admira_control_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA admira FROM admira_ingress, admira_runtime, admira_delivery, admira_scheduler;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA admira FROM admira_ingress, admira_runtime, admira_delivery, admira_scheduler;
GRANT USAGE ON SCHEMA admira TO admira_ingress, admira_runtime, admira_delivery, admira_scheduler;

REVOKE ALL ON FUNCTION admira.resolve_telegram_chat(text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.get_telegram_ingress_cursor(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.advance_telegram_ingress_cursor(text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.ingest_telegram_update(text, bigint, text, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_telegram_updates(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira._enqueue_telegram_parts(uuid, text, text, text, jsonb, uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.complete_telegram_update(uuid, uuid, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.retry_telegram_update(uuid, uuid, text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_telegram_outbox(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.sync_hermes_scheduled_jobs(uuid, uuid, text, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_due_scheduled_jobs(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.complete_scheduled_job_run(uuid, uuid, uuid, timestamptz, text, jsonb, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.retry_scheduled_job_run(uuid, uuid, uuid, text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.acquire_runtime_lease(uuid, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.release_runtime_lease(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.mark_runtime_suspended(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.list_idle_runtime_keys(integer) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION admira.resolve_telegram_chat(text, text, text),
  admira.get_telegram_ingress_cursor(text), admira.advance_telegram_ingress_cursor(text, bigint),
  admira.ingest_telegram_update(text, bigint, text, text, jsonb) TO admira_ingress;
GRANT EXECUTE ON FUNCTION admira.claim_telegram_updates(text, integer, integer),
  admira.complete_telegram_update(uuid, uuid, text, jsonb),
  admira.retry_telegram_update(uuid, uuid, text, integer, integer),
  admira.sync_hermes_scheduled_jobs(uuid, uuid, text, text, jsonb),
  admira.acquire_runtime_lease(uuid, text, integer), admira.release_runtime_lease(uuid, uuid) TO admira_runtime;
GRANT EXECUTE ON FUNCTION admira.claim_telegram_outbox(text, integer, integer),
  admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer) TO admira_delivery;
GRANT EXECUTE ON FUNCTION admira.claim_due_scheduled_jobs(text, integer, integer),
  admira.complete_scheduled_job_run(uuid, uuid, uuid, timestamptz, text, jsonb, jsonb),
  admira.retry_scheduled_job_run(uuid, uuid, uuid, text, integer, integer),
  admira.acquire_runtime_lease(uuid, text, integer), admira.release_runtime_lease(uuid, uuid),
  admira.list_idle_runtime_keys(integer), admira.mark_runtime_suspended(uuid) TO admira_scheduler;

ALTER FUNCTION admira.resolve_telegram_chat(text, text, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.get_telegram_ingress_cursor(text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.advance_telegram_ingress_cursor(text, bigint) OWNER TO admira_control_owner;
ALTER FUNCTION admira.ingest_telegram_update(text, bigint, text, text, jsonb) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_telegram_updates(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira._enqueue_telegram_parts(uuid, text, text, text, jsonb, uuid, uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.complete_telegram_update(uuid, uuid, text, jsonb) OWNER TO admira_control_owner;
ALTER FUNCTION admira.retry_telegram_update(uuid, uuid, text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_telegram_outbox(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.sync_hermes_scheduled_jobs(uuid, uuid, text, text, jsonb) OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_due_scheduled_jobs(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.complete_scheduled_job_run(uuid, uuid, uuid, timestamptz, text, jsonb, jsonb) OWNER TO admira_control_owner;
ALTER FUNCTION admira.retry_scheduled_job_run(uuid, uuid, uuid, text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.acquire_runtime_lease(uuid, text, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.release_runtime_lease(uuid, uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.mark_runtime_suspended(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.list_idle_runtime_keys(integer) OWNER TO admira_control_owner;

COMMIT;
