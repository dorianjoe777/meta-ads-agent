-- Telegram throttling is dependency backpressure, not a terminal delivery
-- failure. Keep rate-limited outbox rows retryable regardless of their normal
-- attempt budget while preserving fencing and bounded retry delays.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:005_telegram_rate_limit_retry', 0));

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
                    WHEN p_error_code = 'telegram_rate_limited' THEN 'retry'
                    WHEN attempt_count >= p_max_attempts THEN 'dead' ELSE 'retry' END,
      sent_at = CASE WHEN p_success THEN now() ELSE NULL END,
      telegram_message_id = CASE WHEN p_success THEN p_telegram_message_id ELSE telegram_message_id END,
      last_error = CASE WHEN p_success THEN NULL ELSE left(coalesce(p_error_code, 'delivery_failure'), 160) END,
      available_at = CASE WHEN p_success THEN available_at
                          WHEN p_error_code = 'telegram_rate_limited'
                            THEN now() + make_interval(secs => p_retry_after_seconds)
                          WHEN attempt_count >= p_max_attempts THEN available_at
                          ELSE now() + make_interval(secs => p_retry_after_seconds) END,
      lease_token = NULL, lease_holder = NULL, leased_until = NULL
  WHERE id = p_outbox_id AND status = 'sending' AND lease_token = p_lease_token;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

REVOKE ALL ON FUNCTION admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer)
  TO admira_delivery;
ALTER FUNCTION admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer)
  OWNER TO admira_control_owner;

COMMIT;
