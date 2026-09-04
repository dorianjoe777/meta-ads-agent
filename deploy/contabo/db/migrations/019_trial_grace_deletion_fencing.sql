-- Fence destructive grace cleanup, isolate its host credential, and make
-- reminder idempotency scoped to one grace cycle instead of one tenant.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('admira:019_trial_grace_deletion_fencing', 0));

ALTER TABLE admira.tenant_entitlements
  ADD COLUMN IF NOT EXISTS grace_cycle_id uuid,
  ADD COLUMN IF NOT EXISTS grace_deletion_claim_id uuid,
  ADD COLUMN IF NOT EXISTS grace_deletion_claimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS grace_deletion_claimed_by text,
  ADD COLUMN IF NOT EXISTS grace_workspace_purged_at timestamptz;

UPDATE admira.tenant_entitlements
SET grace_cycle_id = gen_random_uuid(), updated_at = now()
WHERE lifecycle_state = 'grace' AND grace_cycle_id IS NULL;

UPDATE admira.tenant_entitlements
SET grace_cycle_id = NULL,
    grace_deletion_claim_id = NULL,
    grace_deletion_claimed_at = NULL,
    grace_deletion_claimed_by = NULL,
    grace_workspace_purged_at = NULL,
    updated_at = now()
WHERE lifecycle_state <> 'grace'
  AND (grace_cycle_id IS NOT NULL OR grace_deletion_claim_id IS NOT NULL
       OR grace_deletion_claimed_at IS NOT NULL
       OR grace_deletion_claimed_by IS NOT NULL
       OR grace_workspace_purged_at IS NOT NULL);

ALTER TABLE admira.tenant_entitlements
  DROP CONSTRAINT IF EXISTS tenant_entitlements_grace_cycle_check,
  DROP CONSTRAINT IF EXISTS tenant_entitlements_grace_deletion_claim_check;
ALTER TABLE admira.tenant_entitlements
  ADD CONSTRAINT tenant_entitlements_grace_cycle_check CHECK (
    (lifecycle_state = 'grace' AND grace_cycle_id IS NOT NULL)
    OR (lifecycle_state <> 'grace' AND grace_cycle_id IS NULL)
  ),
  ADD CONSTRAINT tenant_entitlements_grace_deletion_claim_check CHECK (
    (grace_deletion_claim_id IS NULL
      AND grace_deletion_claimed_at IS NULL
      AND grace_deletion_claimed_by IS NULL
      AND grace_workspace_purged_at IS NULL)
    OR
    (lifecycle_state = 'grace'
      AND grace_deletion_claim_id IS NOT NULL
      AND grace_deletion_claimed_at IS NOT NULL
      AND btrim(coalesce(grace_deletion_claimed_by, '')) <> ''
      AND char_length(grace_deletion_claimed_by) <= 200)
  );

ALTER TABLE admira.tenant_grace_reminders
  ADD COLUMN IF NOT EXISTS grace_cycle_id uuid;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE admira.tenant_grace_reminders
  TO admira_control_owner;

UPDATE admira.tenant_grace_reminders AS r
SET grace_cycle_id = e.grace_cycle_id
FROM admira.tenant_entitlements AS e
WHERE r.tenant_id = e.tenant_id
  AND r.grace_cycle_id IS NULL
  AND e.lifecycle_state = 'grace';

WITH historical_cycles AS MATERIALIZED (
  SELECT tenant_id, gen_random_uuid() AS grace_cycle_id
  FROM admira.tenant_grace_reminders
  WHERE grace_cycle_id IS NULL
  GROUP BY tenant_id
)
UPDATE admira.tenant_grace_reminders AS r
SET grace_cycle_id = c.grace_cycle_id
FROM historical_cycles AS c
WHERE r.tenant_id = c.tenant_id AND r.grace_cycle_id IS NULL;

ALTER TABLE admira.tenant_grace_reminders
  ALTER COLUMN grace_cycle_id SET NOT NULL,
  DROP CONSTRAINT IF EXISTS tenant_grace_reminders_tenant_id_reminder_no_key;

DO $migration$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'admira.tenant_grace_reminders'::regclass
      AND conname = 'tenant_grace_reminders_cycle_number_key'
  ) THEN
    ALTER TABLE admira.tenant_grace_reminders
      ADD CONSTRAINT tenant_grace_reminders_cycle_number_key
      UNIQUE (tenant_id, grace_cycle_id, reminder_no);
  END IF;
END;
$migration$;

CREATE INDEX IF NOT EXISTS tenant_entitlements_grace_deletion_idx
  ON admira.tenant_entitlements
  (grace_expires_at, grace_deletion_claimed_at)
  WHERE lifecycle_state = 'grace';

-- This trigger is the serialization boundary shared by every current and
-- future licensing/extension function. Once deletion is claimed, no caller
-- may reactivate the tenant while its host workspace is being purged.
CREATE OR REPLACE FUNCTION admira._fence_grace_lifecycle_transition()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
BEGIN
  IF OLD.lifecycle_state = 'grace' AND NEW.lifecycle_state <> 'grace' THEN
    IF OLD.grace_deletion_claim_id IS NOT NULL THEN
      RAISE EXCEPTION 'grace deletion is in progress' USING ERRCODE = '55000';
    END IF;
    NEW.grace_cycle_id := NULL;
    NEW.grace_deletion_claim_id := NULL;
    NEW.grace_deletion_claimed_at := NULL;
    NEW.grace_deletion_claimed_by := NULL;
    NEW.grace_workspace_purged_at := NULL;
  ELSIF OLD.lifecycle_state <> 'grace' AND NEW.lifecycle_state = 'grace' THEN
    NEW.grace_cycle_id := gen_random_uuid();
    NEW.grace_deletion_claim_id := NULL;
    NEW.grace_deletion_claimed_at := NULL;
    NEW.grace_deletion_claimed_by := NULL;
    NEW.grace_workspace_purged_at := NULL;
  ELSIF NEW.lifecycle_state = 'grace' AND NEW.grace_cycle_id IS NULL THEN
    NEW.grace_cycle_id := coalesce(OLD.grace_cycle_id, gen_random_uuid());
  END IF;
  RETURN NEW;
END;
$$;
ALTER FUNCTION admira._fence_grace_lifecycle_transition() OWNER TO admira_control_owner;
REVOKE ALL ON FUNCTION admira._fence_grace_lifecycle_transition() FROM PUBLIC;

DROP TRIGGER IF EXISTS fence_grace_lifecycle_transition ON admira.tenant_entitlements;
CREATE TRIGGER fence_grace_lifecycle_transition
  BEFORE UPDATE OF lifecycle_state ON admira.tenant_entitlements
  FOR EACH ROW EXECUTE FUNCTION admira._fence_grace_lifecycle_transition();

-- The reminder ledger is idempotent per grace cycle. Extending and later
-- expiring the same tenant starts a fresh cycle with reminder numbers 0..9.
CREATE OR REPLACE FUNCTION admira.enqueue_due_trial_grace_reminders()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE
  current_now timestamptz := clock_timestamp();
  entitlement record;
  binding record;
  reminder_id uuid;
  new_outbox_id uuid;
  notification_no integer;
  queued integer := 0;
  message_body text;
BEGIN
  FOR entitlement IN
    SELECT e.tenant_id, e.grace_cycle_id, e.grace_expires_at,
           e.grace_next_notification_at, e.grace_notification_sequence
    FROM admira.tenant_entitlements AS e
    JOIN admira.tenants AS t ON t.id = e.tenant_id
    WHERE e.lifecycle_state = 'grace'
      AND e.grace_cycle_id IS NOT NULL
      AND t.status = 'suspended'
      AND e.grace_expires_at > current_now
      AND e.grace_next_notification_at IS NOT NULL
      AND e.grace_next_notification_at <= current_now
    ORDER BY e.grace_next_notification_at, e.tenant_id
    FOR UPDATE OF e SKIP LOCKED
  LOOP
    reminder_id := NULL;
    new_outbox_id := NULL;
    notification_no := coalesce(entitlement.grace_notification_sequence, 0);
    IF notification_no >= 10 THEN
      UPDATE admira.tenant_entitlements
      SET grace_next_notification_at = NULL, updated_at = now()
      WHERE tenant_id = entitlement.tenant_id
        AND grace_cycle_id = entitlement.grace_cycle_id;
      CONTINUE;
    END IF;

    SELECT b.bot_id, b.telegram_chat_id INTO binding
    FROM admira.tenant_telegram_bindings AS b
    WHERE b.tenant_id = entitlement.tenant_id
    ORDER BY b.is_primary DESC, b.updated_at DESC, b.id
    LIMIT 1;
    IF NOT FOUND THEN
      UPDATE admira.tenant_entitlements
      SET grace_next_notification_at = greatest(
            coalesce(grace_next_notification_at, current_now) + interval '3 days',
            current_now + interval '3 days'
          ), updated_at = now()
      WHERE tenant_id = entitlement.tenant_id
        AND grace_cycle_id = entitlement.grace_cycle_id;
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
      (tenant_id, grace_cycle_id, reminder_no, scheduled_for, status)
    VALUES (entitlement.tenant_id, entitlement.grace_cycle_id,
            notification_no, entitlement.grace_next_notification_at, 'queued')
    ON CONFLICT (tenant_id, grace_cycle_id, reminder_no) DO NOTHING
    RETURNING id INTO reminder_id;

    IF reminder_id IS NOT NULL THEN
      INSERT INTO admira.tenant_telegram_outbox
        (tenant_id, bot_id, telegram_chat_id, sequence_no, kind, body)
      VALUES (entitlement.tenant_id, binding.bot_id, binding.telegram_chat_id,
              notification_no, 'text', message_body)
      RETURNING id INTO new_outbox_id;
      UPDATE admira.tenant_grace_reminders
      SET outbox_id = new_outbox_id
      WHERE id = reminder_id;
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
    WHERE tenant_id = entitlement.tenant_id
      AND grace_cycle_id = entitlement.grace_cycle_id;
  END LOOP;
  RETURN queued;
END;
$$;

DROP FUNCTION IF EXISTS admira.grace_deletion_candidates();
DROP FUNCTION IF EXISTS admira.delete_grace_tenant(uuid);

-- Claims are short leases. A crashed scheduler can be superseded, while the
-- claim itself continuously blocks extension/licensing until cleanup ends.
CREATE OR REPLACE FUNCTION admira.claim_grace_deletion_candidates(
  p_worker_id text, p_limit integer DEFAULT 25, p_lease_seconds integer DEFAULT 900
)
RETURNS TABLE (
  tenant_id uuid, runtime_key text, deletion_claim_id uuid,
  workspace_purged boolean
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE current_now timestamptz := clock_timestamp();
BEGIN
  IF btrim(coalesce(p_worker_id, '')) = '' OR char_length(btrim(p_worker_id)) > 200
     OR p_limit NOT BETWEEN 1 AND 100
     OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid grace deletion claim' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  WITH candidates AS MATERIALIZED (
    SELECT e.tenant_id
    FROM admira.tenant_entitlements AS e
    JOIN admira.tenants AS t ON t.id = e.tenant_id
    JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = e.tenant_id
    WHERE t.status = 'suspended'
      AND e.lifecycle_state = 'grace'
      AND e.grace_runtime_suspended_at IS NOT NULL
      AND e.grace_expires_at IS NOT NULL
      AND e.grace_expires_at <= current_now
      AND (e.grace_deletion_claim_id IS NULL
           OR e.grace_deletion_claimed_at <= current_now - make_interval(secs => p_lease_seconds))
    ORDER BY e.grace_expires_at, l.runtime_key
    FOR UPDATE OF e SKIP LOCKED
    LIMIT p_limit
  ), claimed AS (
    UPDATE admira.tenant_entitlements AS e
    SET grace_deletion_claim_id = gen_random_uuid(),
        grace_deletion_claimed_at = current_now,
        grace_deletion_claimed_by = btrim(p_worker_id),
        updated_at = now()
    FROM candidates AS c
    WHERE e.tenant_id = c.tenant_id
      AND e.lifecycle_state = 'grace'
    RETURNING e.tenant_id, e.grace_deletion_claim_id,
              e.grace_workspace_purged_at IS NOT NULL AS workspace_purged
  )
  SELECT c.tenant_id, l.runtime_key, c.grace_deletion_claim_id,
         c.workspace_purged
  FROM claimed AS c
  JOIN admira.tenant_runtime_leases AS l ON l.tenant_id = c.tenant_id
  ORDER BY l.runtime_key;
END;
$$;

CREATE OR REPLACE FUNCTION admira.mark_grace_workspace_purged(
  p_tenant_id uuid, p_deletion_claim_id uuid
)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE changed integer;
BEGIN
  IF p_tenant_id IS NULL OR p_deletion_claim_id IS NULL THEN RETURN false; END IF;
  UPDATE admira.tenant_entitlements
  SET grace_workspace_purged_at = coalesce(grace_workspace_purged_at, now()),
      updated_at = now()
  WHERE tenant_id = p_tenant_id
    AND lifecycle_state = 'grace'
    AND grace_runtime_suspended_at IS NOT NULL
    AND grace_expires_at IS NOT NULL AND grace_expires_at <= now()
    AND grace_deletion_claim_id = p_deletion_claim_id;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION admira.delete_grace_tenant(
  p_tenant_id uuid, p_deletion_claim_id uuid
)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog
AS $$
DECLARE deleted_id uuid;
BEGIN
  IF p_tenant_id IS NULL OR p_deletion_claim_id IS NULL THEN RETURN false; END IF;
  DELETE FROM admira.tenants AS t
  USING admira.tenant_entitlements AS e
  WHERE t.id = p_tenant_id AND e.tenant_id = t.id
    AND t.status = 'suspended' AND e.lifecycle_state = 'grace'
    AND e.grace_runtime_suspended_at IS NOT NULL
    AND e.grace_workspace_purged_at IS NOT NULL
    AND e.grace_deletion_claim_id = p_deletion_claim_id
    AND e.grace_expires_at IS NOT NULL AND e.grace_expires_at <= now()
  RETURNING t.id INTO deleted_id;
  RETURN deleted_id IS NOT NULL;
END;
$$;

-- Fail-closed compatibility for a temporary rollback to a pre-019 scheduler.
-- The old read-then-purge loop receives no work and its one-argument delete
-- can never mutate data; only the claimed APIs above are operational.
CREATE OR REPLACE FUNCTION admira.grace_deletion_candidates()
RETURNS TABLE (tenant_id uuid, runtime_key text, grace_expires_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = admira, pg_catalog
AS $$
  SELECT NULL::uuid, NULL::text, NULL::timestamptz WHERE false;
$$;

CREATE OR REPLACE FUNCTION admira.delete_grace_tenant(p_tenant_id uuid)
RETURNS boolean
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = admira, pg_catalog
AS $$
  SELECT false;
$$;

ALTER FUNCTION admira.enqueue_due_trial_grace_reminders() OWNER TO admira_control_owner;
ALTER FUNCTION admira.claim_grace_deletion_candidates(text, integer, integer) OWNER TO admira_control_owner;
ALTER FUNCTION admira.mark_grace_workspace_purged(uuid, uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.delete_grace_tenant(uuid, uuid) OWNER TO admira_control_owner;
ALTER FUNCTION admira.grace_deletion_candidates() OWNER TO admira_control_owner;
ALTER FUNCTION admira.delete_grace_tenant(uuid) OWNER TO admira_control_owner;

REVOKE ALL ON FUNCTION admira.enqueue_due_trial_grace_reminders() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.claim_grace_deletion_candidates(text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.mark_grace_workspace_purged(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.delete_grace_tenant(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.grace_deletion_candidates() FROM PUBLIC;
REVOKE ALL ON FUNCTION admira.delete_grace_tenant(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.enqueue_due_trial_grace_reminders(),
  admira.claim_grace_deletion_candidates(text, integer, integer),
  admira.mark_grace_workspace_purged(uuid, uuid),
  admira.delete_grace_tenant(uuid, uuid)
  TO admira_scheduler;
GRANT EXECUTE ON FUNCTION admira.grace_deletion_candidates(),
  admira.delete_grace_tenant(uuid) TO admira_scheduler;

COMMENT ON COLUMN admira.tenant_entitlements.grace_cycle_id IS
  'Fresh id for each trial-to-grace transition; scopes reminder idempotency.';
COMMENT ON COLUMN admira.tenant_entitlements.grace_deletion_claim_id IS
  'Scheduler fencing token that blocks reactivation while host cleanup is in progress.';
COMMENT ON COLUMN admira.tenant_entitlements.grace_workspace_purged_at IS
  'Set only after the authenticated host broker confirms tenant workspace purge.';
COMMENT ON FUNCTION admira.claim_grace_deletion_candidates(text, integer, integer) IS
  'Atomically leases expired grace tenants for host cleanup; stale claims can be safely reclaimed.';
COMMENT ON FUNCTION admira.delete_grace_tenant(uuid, uuid) IS
  'Deletes an expired grace tenant only with its current claim and recorded host-purge marker.';
COMMENT ON FUNCTION admira.grace_deletion_candidates() IS
  'Fail-closed compatibility stub for schedulers older than migration 019; always empty.';
COMMENT ON FUNCTION admira.delete_grace_tenant(uuid) IS
  'Fail-closed compatibility stub for schedulers older than migration 019; always false.';

COMMIT;
