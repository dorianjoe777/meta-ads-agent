-- Keep the buyer-visible typing indicator alive while a durable turn retries.
--
-- The poller starts one watcher when it durably enqueues a Telegram update.
-- A recoverable runtime failure releases that update into `retry`; treating
-- that state as terminal stopped the watcher before the same turn was claimed
-- again. `retry` remains a durable, bounded in-flight state and must remain
-- visible to the ingress-only probe until the update is processed or dead.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:015_telegram_typing_retry_continuity', 0));

CREATE OR REPLACE FUNCTION admira.telegram_update_pending(
  p_bot_id text,
  p_update_id bigint
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = admira, pg_catalog
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM admira.tenant_telegram_updates AS u
    WHERE u.bot_id = btrim(p_bot_id)
      AND u.update_id = p_update_id
      AND (
        u.status IN ('received', 'retry')
        OR (
          u.status = 'processing'
          AND (u.leased_until IS NULL OR u.leased_until > now())
        )
      )
  );
$$;

REVOKE ALL ON FUNCTION admira.telegram_update_pending(text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.telegram_update_pending(text, bigint) TO admira_ingress;
ALTER FUNCTION admira.telegram_update_pending(text, bigint) OWNER TO admira_control_owner;

COMMENT ON FUNCTION admira.telegram_update_pending(text, bigint) IS
  'Ingress-only boolean probe used to refresh Telegram typing through active runtime retries.';

COMMIT;
