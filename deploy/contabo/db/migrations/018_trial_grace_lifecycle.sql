-- Trial grace lifecycle, operator recovery, Telegram reminders, and cleanup.
--
-- A trial that reaches its end becomes `grace`: the tenant remains in the
-- database for 30 days, is suspended for routing, and receives at most one
-- fixed-template reminder every three days.  The scheduler owns delivery of
-- reminders and the host-side removal of the tenant workspace.  Extending a
-- grace account is an explicit operator action that returns it to `trial`.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:018_trial_grace_lifecycle', 0));

ALTER TABLE admira.tenant_entitlements
  ADD COLUMN IF NOT EXISTS grace_started_at timestamptz,
  ADD COLUMN IF NOT EXISTS grace_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS grace_next_notification_at timestamptz,
  ADD COLUMN IF NOT EXISTS grace_notification_sequence integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS grace_runtime_suspended_at timestamptz;

ALTER TABLE admira.tenant_entitlements
  DROP CONSTRAINT IF EXISTS tenant_entitlements_grace_notification_sequence_check;
ALTER TABLE admira.tenant_entitlements
  ADD CONSTRAINT tenant_entitlements_grace_notification_sequence_check
  CHECK (grace_notification_sequence >= 0);

CREATE TABLE IF NOT EXISTS admira.tenant_grace_reminders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  reminder_no integer NOT NULL CHECK (reminder_no >= 0),
  scheduled_for timestamptz NOT NULL,
  outbox_id uuid REFERENCES admira.tenant_telegram_outbox(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'sent', 'failed', 'cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  UNIQUE (tenant_id, reminder_no)
);

CREATE INDEX IF NOT EXISTS tenant_grace_reminders_status_idx
  ON admira.tenant_grace_reminders (status, scheduled_for);
CREATE INDEX IF NOT EXISTS tenant_grace_reminders_tenant_idx
  ON admira.tenant_grace_reminders (tenant_id, reminder_no);

ALTER TABLE admira.tenant_grace_reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE admira.tenant_grace_reminders FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON admira.tenant_grace_reminders;
CREATE POLICY tenant_isolation ON admira.tenant_grace_reminders
  USING (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''))
  WITH CHECK (tenant_id::text = NULLIF(current_setting('admira.tenant_id', true), ''));

REVOKE ALL ON TABLE admira.tenant_grace_reminders
  FROM PUBLIC, admira_ingress, admira_runtime, admira_delivery,
       admira_scheduler, admira_provisioner, admira_operator;

ALTER TABLE admira.tenant_entitlements
  DROP CONSTRAINT IF EXISTS tenant_entitlements_lifecycle_state_check;

-- Normalize the state introduced by migration 007 before tightening the
-- constraint.  The trial end remains the start of the 30-day retention clock.
UPDATE admira.tenant_entitlements
SET lifecycle_state = 'grace', plan = 'suspended',
    grace_started_at = coalesce(grace_started_at, coalesce(trial_ends_at, now())),
    grace_expires_at = coalesce(
      grace_expires_at,
      coalesce(trial_ends_at, now()) + interval '30 days'
    ),
    grace_next_notification_at = coalesce(grace_next_notification_at, now()),
    grace_runtime_suspended_at = NULL,
    updated_at = now()
WHERE lifecycle_state = 'trial_expired';

ALTER TABLE admira.tenant_entitlements
  ADD CONSTRAINT tenant_entitlements_lifecycle_state_check
  CHECK (lifecycle_state IN ('pending_claim', 'trial', 'grace', 'licensed', 'suspended', 'cancelled'));

UPDATE admira.tenants AS t
SET status = 'suspended', updated_at = now()
WHERE t.status = 'active'
  AND EXISTS (
    SELECT 1 FROM admira.tenant_entitlements AS e
    WHERE e.tenant_id = t.id AND e.lifecycle_state = 'grace'
  );

-- The pool-release trigger predates `grace`; keep the existing public release
-- reason for quota accounting while making the new state explicit.
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
      WHEN NEW.lifecycle_state = 'grace' THEN 'trial_expired'
      WHEN NEW.lifecycle_state = 'cancelled' THEN 'cancelled'
      WHEN NEW.lifecycle_state = 'suspended' THEN 'suspended'
      ELSE 'operator'
    END;
  END IF;
  PERFORM admira.release_gemini_trial(tenant_id_value, release_reason_value);
  RETURN NEW;
END;
$$;
ALTER FUNCTION admira._gemini_pool_release_on_state_change() OWNER TO admira_control_owner;

CREATE OR REPLACE FUNCTION admira._cancel_grace_reminders(p_tenant_id uuid)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  IF p_tenant_id IS NULL THEN RETURN 0; END IF;
  UPDATE admira.tenant_telegram_outbox AS o
  SET status = 'dead', last_error = 'grace_reminder_cancelled',
      lease_token = NULL, lease_holder = NULL, leased_until = NULL
  WHERE o.id IN (
    SELECT r.outbox_id FROM admira.tenant_grace_reminders AS r
    WHERE r.tenant_id = p_tenant_id AND r.status IN ('queued', 'failed')
      AND r.outbox_id IS NOT NULL
  ) AND o.status IN ('queued', 'retry', 'sending');
  UPDATE admira.tenant_grace_reminders
  SET status = 'cancelled'
  WHERE tenant_id = p_tenant_id AND status IN ('queued', 'failed');
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END;
$$;

CREATE OR REPLACE FUNCTION admira._cancel_grace_reminders_on_lifecycle_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
BEGIN
  IF OLD.lifecycle_state = 'grace' AND NEW.lifecycle_state <> 'grace' THEN
    PERFORM admira._cancel_grace_reminders(NEW.tenant_id);
  END IF;
  RETURN NEW;
END;
$$;
ALTER FUNCTION admira._cancel_grace_reminders_on_lifecycle_change() OWNER TO admira_control_owner;
DROP TRIGGER IF EXISTS cancel_grace_reminders_on_lifecycle_change ON admira.tenant_entitlements;
CREATE TRIGGER cancel_grace_reminders_on_lifecycle_change
  AFTER UPDATE OF lifecycle_state ON admira.tenant_entitlements
  FOR EACH ROW EXECUTE FUNCTION admira._cancel_grace_reminders_on_lifecycle_change();

-- The existing callers keep their no-argument API.  This transition is
-- idempotent: repeated poller/scheduler calls do not restart the grace clock.
CREATE OR REPLACE FUNCTION admira.expire_due_trials()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  WITH expired AS (
    UPDATE admira.tenant_entitlements AS e
    SET lifecycle_state = 'grace', plan = 'suspended',
        grace_started_at = coalesce(e.grace_started_at, e.trial_ends_at),
        grace_expires_at = coalesce(
          e.grace_expires_at, e.trial_ends_at + interval '30 days'
        ),
        grace_next_notification_at = coalesce(e.grace_next_notification_at, e.trial_ends_at),
        grace_notification_sequence = coalesce(e.grace_notification_sequence, 0),
        grace_runtime_suspended_at = NULL,
        updated_at = now()
    WHERE e.lifecycle_state = 'trial'
      AND e.trial_ends_at IS NOT NULL AND e.trial_ends_at <= now()
    RETURNING e.tenant_id
  ), suspended AS (
    UPDATE admira.tenants AS t SET status = 'suspended', updated_at = now()
    WHERE t.id IN (SELECT tenant_id FROM expired) AND t.status = 'active'
    RETURNING t.id
  )
  SELECT count(*)::integer INTO changed FROM expired;
  RETURN changed;
END;
$$;

CREATE OR REPLACE FUNCTION admira.enqueue_due_trial_grace_reminders()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE
  current_now timestamptz := clock_timestamp();
  entitlement record;
  binding record;
  reminder_id uuid; new_outbox_id uuid;
  notification_no integer;
  queued integer := 0;
  message_body text;
BEGIN
  FOR entitlement IN
    SELECT e.tenant_id, e.grace_expires_at, e.grace_next_notification_at,
           e.grace_notification_sequence
    FROM admira.tenant_entitlements AS e
    JOIN admira.tenants AS t ON t.id = e.tenant_id
    WHERE e.lifecycle_state = 'grace'
      AND t.status = 'suspended'
      AND e.grace_expires_at > current_now
      AND e.grace_next_notification_at IS NOT NULL
      AND e.grace_next_notification_at <= current_now
    ORDER BY e.grace_next_notification_at, e.tenant_id
    FOR UPDATE OF e SKIP LOCKED
  LOOP
    notification_no := coalesce(entitlement.grace_notification_sequence, 0);
    IF notification_no >= 10 THEN
      UPDATE admira.tenant_entitlements
      SET grace_next_notification_at = NULL, updated_at = now()
      WHERE tenant_id = entitlement.tenant_id;
      CONTINUE;
    END IF;

    SELECT b.bot_id, b.telegram_chat_id INTO binding
    FROM admira.tenant_telegram_bindings AS b
    WHERE b.tenant_id = entitlement.tenant_id
    ORDER BY b.is_primary DESC, b.updated_at DESC, b.id
    LIMIT 1;
    IF NOT FOUND THEN
      -- Do not burn the reminder number if the account is temporarily
      -- unbound; one reminder is sent after a binding becomes available.
      UPDATE admira.tenant_entitlements
      SET grace_next_notification_at = greatest(
            coalesce(grace_next_notification_at, current_now) + interval '3 days',
            current_now + interval '3 days'
          ), updated_at = now()
      WHERE tenant_id = entitlement.tenant_id;
      CONTINUE;
    END IF;

    message_body := CASE
      WHEN notification_no = 0 THEN
        'Tu periodo de prueba de Admira IA ha terminado. Tu espacio entra en un periodo de gracia y no puede procesar nuevas solicitudes. Si deseas seguir usando el servicio, contacta a tu ejecutivo de Admira IA para coordinar tu licencia.'
      WHEN notification_no >= 9 THEN
        'Último aviso de Admira IA: tu periodo de prueba terminó y tu espacio será eliminado al finalizar el periodo de gracia si no se licencia. Si deseas continuar, contacta a tu ejecutivo de Admira IA para organizar tu licencia.'
      ELSE
        'Recordatorio de Admira IA: tu periodo de prueba terminó. Tu espacio se conservará durante el periodo de gracia, pero permanece pausado. Si deseas continuar, contacta a tu ejecutivo de Admira IA para organizar tu licencia.'
    END;

    INSERT INTO admira.tenant_grace_reminders
      (tenant_id, reminder_no, scheduled_for, status)
    VALUES (entitlement.tenant_id, notification_no,
            entitlement.grace_next_notification_at, 'queued')
    ON CONFLICT (tenant_id, reminder_no) DO NOTHING
    RETURNING id INTO reminder_id;

    IF reminder_id IS NOT NULL THEN
      INSERT INTO admira.tenant_telegram_outbox
        (tenant_id, bot_id, telegram_chat_id, sequence_no, kind, body)
      VALUES (entitlement.tenant_id, binding.bot_id, binding.telegram_chat_id,
              notification_no, 'text', message_body)
      RETURNING id INTO new_outbox_id;
      UPDATE admira.tenant_grace_reminders AS r
      SET outbox_id = new_outbox_id
      WHERE r.id = reminder_id;
      queued := queued + 1;
    END IF;

    UPDATE admira.tenant_entitlements
    SET grace_notification_sequence = notification_no + 1,
        grace_next_notification_at = CASE
          WHEN notification_no >= 9 THEN NULL
          ELSE greatest(
            coalesce(grace_next_notification_at, current_now) + interval '3 days',
            current_now + interval '3 days'
          )
        END,
        updated_at = now()
    WHERE tenant_id = entitlement.tenant_id;
  END LOOP;
  RETURN queued;
END;
$$;

CREATE OR REPLACE FUNCTION admira.grace_runtime_candidates()
RETURNS TABLE (tenant_id uuid, runtime_key text)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = admira, pg_catalog
AS $$
  SELECT t.id, l.runtime_key
  FROM admira.tenants AS t
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
  WHERE t.status = 'suspended' AND e.lifecycle_state = 'grace'
    AND e.grace_runtime_suspended_at IS NULL
  ORDER BY t.created_at, l.runtime_key;
$$;

CREATE OR REPLACE FUNCTION admira.mark_grace_runtime_suspended(p_tenant_id uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  UPDATE admira.tenant_entitlements
  SET grace_runtime_suspended_at = coalesce(grace_runtime_suspended_at, now()), updated_at = now()
  WHERE tenant_id = p_tenant_id AND lifecycle_state = 'grace';
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.grace_deletion_candidates()
RETURNS TABLE (tenant_id uuid, runtime_key text, grace_expires_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = admira, pg_catalog
AS $$
  SELECT t.id, l.runtime_key, e.grace_expires_at
  FROM admira.tenants AS t
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
  WHERE t.status = 'suspended' AND e.lifecycle_state = 'grace'
    AND e.grace_runtime_suspended_at IS NOT NULL
    AND e.grace_expires_at IS NOT NULL AND e.grace_expires_at <= now()
  ORDER BY e.grace_expires_at, l.runtime_key;
$$;

CREATE OR REPLACE FUNCTION admira.delete_grace_tenant(p_tenant_id uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE deleted_id uuid;
BEGIN
  DELETE FROM admira.tenants AS t
  USING admira.tenant_entitlements AS e
  WHERE t.id = p_tenant_id AND e.tenant_id = t.id
    AND t.status = 'suspended' AND e.lifecycle_state = 'grace'
    AND e.grace_expires_at IS NOT NULL AND e.grace_expires_at <= now()
  RETURNING t.id INTO deleted_id;
  RETURN deleted_id IS NOT NULL;
END;
$$;

-- Keep delivery status and reminder history consistent without granting the
-- delivery worker direct table access.
CREATE OR REPLACE FUNCTION admira.ack_telegram_outbox(
  p_outbox_id uuid, p_lease_token uuid, p_success boolean,
  p_telegram_message_id bigint DEFAULT NULL, p_error_code text DEFAULT NULL,
  p_retry_after_seconds integer DEFAULT 30, p_max_attempts integer DEFAULT 8
)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer; attempts_value integer;
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
  WHERE id = p_outbox_id AND status = 'sending' AND lease_token = p_lease_token
  RETURNING attempt_count INTO attempts_value;
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed = 1 THEN
    UPDATE admira.tenant_grace_reminders
    SET status = CASE WHEN p_success THEN 'sent'
                      WHEN p_error_code = 'telegram_rate_limited'
                           OR attempts_value < p_max_attempts THEN 'queued'
                      ELSE 'failed' END,
        sent_at = CASE WHEN p_success THEN now() ELSE sent_at END
    WHERE outbox_id = p_outbox_id AND status <> 'cancelled';
  END IF;
  RETURN changed = 1;
END;
$$;

-- Operator-safe projection and lifecycle operations are redefined here so a
-- grace row is visible and can be licensed or explicitly extended.
CREATE OR REPLACE FUNCTION admira.operator_trial_accounts()
RETURNS TABLE (
  runtime_key text, display_name text, lifecycle_state text,
  tenant_created_at timestamptz, trial_started_at timestamptz,
  trial_ends_at timestamptz, image_sponsorship_ends_at timestamptz,
  gemini_pool_ready boolean
)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = admira, pg_catalog
AS $$
  SELECT l.runtime_key, left(t.display_name, 200), e.lifecycle_state,
         t.created_at, e.trial_started_at, e.trial_ends_at,
         e.image_sponsorship_ends_at,
         EXISTS (
           SELECT 1 FROM admira.gemini_pool_assignments AS assignment
           WHERE assignment.tenant_id = t.id AND assignment.status = 'active'
         )
  FROM admira.tenants AS t
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = t.id
  JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
  WHERE t.status <> 'deleted'
    AND e.lifecycle_state IN ('pending_claim', 'trial', 'grace')
  ORDER BY t.created_at DESC, l.runtime_key
  LIMIT 1000;
$$;

CREATE OR REPLACE FUNCTION admira.operator_extend_trial(
  p_runtime_key text, p_trial_ends_at timestamptz,
  p_actor_id text DEFAULT 'operator-dashboard'
)
RETURNS TABLE (runtime_key text, lifecycle_state text,
               previous_trial_ends_at timestamptz, trial_ends_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE
  resolved_tenant uuid; prior_end timestamptz; resolved_state text;
  was_expired boolean; now_value timestamptz := clock_timestamp();
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR p_trial_ends_at IS NULL OR p_trial_ends_at <= now_value
     OR p_trial_ends_at > now_value + interval '365 days'
     OR btrim(coalesce(p_actor_id, '')) = '' OR char_length(btrim(p_actor_id)) > 200 THEN
    RAISE EXCEPTION 'invalid trial extension' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant FROM admira.tenants AS t
  WHERE t.external_customer_id = btrim(p_runtime_key) AND t.status <> 'deleted'
  FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023'; END IF;
  SELECT e.lifecycle_state, e.trial_ends_at INTO resolved_state, prior_end
  FROM admira.tenant_entitlements AS e WHERE e.tenant_id = resolved_tenant FOR UPDATE;
  was_expired := resolved_state = 'grace'
                 OR (resolved_state = 'trial' AND prior_end IS NOT NULL AND prior_end <= now_value);
  IF resolved_state <> 'trial' AND resolved_state <> 'grace' THEN
    RAISE EXCEPTION 'tenant is not an extendable trial' USING ERRCODE = '55000';
  END IF;
  IF prior_end IS NULL THEN
    RAISE EXCEPTION 'tenant is not an extendable trial' USING ERRCODE = '55000';
  END IF;
  IF p_trial_ends_at < prior_end THEN
    RAISE EXCEPTION 'trial extension must be later than current end' USING ERRCODE = '22023';
  END IF;
  IF p_trial_ends_at = prior_end THEN
    RETURN QUERY SELECT p_runtime_key, resolved_state, prior_end, prior_end;
    RETURN;
  END IF;

  IF was_expired THEN PERFORM admira._cancel_grace_reminders(resolved_tenant); END IF;
  UPDATE admira.tenant_entitlements
  SET plan = 'trial', lifecycle_state = 'trial',
      trial_started_at = coalesce(trial_started_at, now_value),
      trial_ends_at = p_trial_ends_at,
      grace_started_at = NULL, grace_expires_at = NULL,
      grace_next_notification_at = NULL,
      grace_notification_sequence = 0,
      grace_runtime_suspended_at = NULL,
      updated_at = now()
  WHERE tenant_id = resolved_tenant;
  UPDATE admira.tenants SET status = 'active', updated_at = now()
  WHERE id = resolved_tenant;
  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  VALUES (resolved_tenant, 'operator', btrim(p_actor_id),
          CASE WHEN was_expired THEN 'trial_extended_from_grace' ELSE 'trial_extended' END,
          'tenant_entitlement', p_runtime_key,
          jsonb_build_object('previous_trial_ends_at', prior_end,
                             'trial_ends_at', p_trial_ends_at,
                             'previous_lifecycle_state', resolved_state));
  RETURN QUERY SELECT p_runtime_key, 'trial'::text, prior_end, p_trial_ends_at;
END;
$$;

CREATE OR REPLACE FUNCTION admira.operator_expire_trial(
  p_runtime_key text, p_actor_id text DEFAULT 'operator-dashboard'
)
RETURNS TABLE (runtime_key text, lifecycle_state text, expired_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE resolved_tenant uuid; resolved_state text; now_value timestamptz := clock_timestamp();
BEGIN
  IF coalesce(p_runtime_key, '') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR btrim(coalesce(p_actor_id, '')) = '' OR char_length(btrim(p_actor_id)) > 200 THEN
    RAISE EXCEPTION 'invalid trial expiration' USING ERRCODE = '22023';
  END IF;
  SELECT t.id INTO resolved_tenant FROM admira.tenants AS t
  WHERE t.external_customer_id = btrim(p_runtime_key) AND t.status <> 'deleted'
  FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'tenant not found' USING ERRCODE = '22023'; END IF;
  SELECT e.lifecycle_state INTO resolved_state FROM admira.tenant_entitlements AS e
  WHERE e.tenant_id = resolved_tenant FOR UPDATE;
  IF resolved_state = 'grace' THEN
    RETURN QUERY SELECT p_runtime_key, 'grace'::text, now_value;
    RETURN;
  END IF;
  IF resolved_state <> 'trial' THEN
    RAISE EXCEPTION 'tenant is not an active trial' USING ERRCODE = '55000';
  END IF;
  UPDATE admira.tenant_entitlements
  SET lifecycle_state = 'grace', plan = 'suspended',
      grace_started_at = now_value, grace_expires_at = now_value + interval '30 days',
      grace_next_notification_at = now_value, grace_notification_sequence = 0,
      grace_runtime_suspended_at = NULL, updated_at = now()
  WHERE tenant_id = resolved_tenant;
  UPDATE admira.tenants SET status = 'suspended', updated_at = now()
  WHERE id = resolved_tenant;
  INSERT INTO admira.tenant_audit_events
    (tenant_id, actor_type, actor_id, event_type, resource_type, resource_id, payload)
  VALUES (resolved_tenant, 'operator', btrim(p_actor_id), 'trial_entered_grace_manually',
          'tenant_entitlement', p_runtime_key,
          jsonb_build_object('grace_started_at', now_value,
                             'grace_expires_at', now_value + interval '30 days'));
  RETURN QUERY SELECT p_runtime_key, 'grace'::text, now_value;
END;
$$;

ALTER FUNCTION admira._cancel_grace_reminders(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.expire_due_trials() OWNER TO admira_control_owner;
ALTER FUNCTION admira.enqueue_due_trial_grace_reminders() OWNER TO admira_control_owner;
ALTER FUNCTION admira.grace_runtime_candidates() OWNER TO admira_control_owner;
ALTER FUNCTION admira.mark_grace_runtime_suspended(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.grace_deletion_candidates() OWNER TO admira_control_owner;
ALTER FUNCTION admira.delete_grace_tenant(uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_trial_accounts() OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_extend_trial(text, timestamptz, text) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_expire_trial(text, text) OWNER TO admira_control_owner;

REVOKE ALL ON FUNCTION admira._cancel_grace_reminders(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.enqueue_due_trial_grace_reminders() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.grace_runtime_candidates() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.mark_grace_runtime_suspended(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.grace_deletion_candidates() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.delete_grace_tenant(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.expire_due_trials() TO admira_runtime, admira_scheduler;
GRANT EXECUTE ON FUNCTION admira.enqueue_due_trial_grace_reminders(),
  admira.grace_runtime_candidates(), admira.mark_grace_runtime_suspended(uuid),
  admira.grace_deletion_candidates(), admira.delete_grace_tenant(uuid)
  TO admira_scheduler;
GRANT EXECUTE ON FUNCTION admira.ack_telegram_outbox(uuid, uuid, boolean, bigint, text, integer, integer)
  TO admira_delivery;
GRANT EXECUTE ON FUNCTION admira.operator_extend_trial(text, timestamptz, text),
  admira.operator_expire_trial(text, text) TO admira_provisioner;
GRANT EXECUTE ON FUNCTION admira.operator_trial_accounts() TO admira_operator;

COMMENT ON TABLE admira.tenant_grace_reminders IS
  'Idempotent, fixed-template Telegram reminders for the 30-day trial grace period.';
COMMENT ON FUNCTION admira.operator_extend_trial(text, timestamptz, text) IS
  'Extends an active or expired/grace trial to a later bounded timestamp; grace returns to pure trial and cancels pending reminders.';
COMMENT ON FUNCTION admira.delete_grace_tenant(uuid) IS
  'Deletes only a suspended tenant whose grace retention deadline has passed; host workspace removal is performed first by the scheduler.';

COMMIT;
