-- Narrow ingress-side status probe for the Telegram typing indicator.
--
-- The poller owns the bot token and may observe only whether its own durable
-- update is still active.  It never receives tenant data or direct table
-- privileges; the runtime worker remains completely tokenless.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:014_telegram_typing_indicator', 0));

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
        u.status = 'received'
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
  'Ingress-only boolean probe used to refresh Telegram typing while one durable update is active.';

COMMIT;
