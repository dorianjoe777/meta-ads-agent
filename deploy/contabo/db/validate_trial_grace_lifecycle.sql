-- Disposable validator for migrations 018-019. Never run against production data.
\set ON_ERROR_STOP on
BEGIN;

SELECT encode(digest(convert_to('CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC','UTF8'),'sha256'),'hex') AS token_hash \gset

SET ROLE admira_provisioner;
SELECT tenant_id AS grace_tenant
FROM admira.issue_telegram_tenant_claim(
  'grace-cycle-001', 'Grace Cycle', :'token_hash', 1800
) \gset
RESET ROLE;

SET ROLE admira_ingress;
SELECT tenant_id
FROM admira.claim_telegram_tenant('123456', '92001', '92001',
                                   'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC') \gset
RESET ROLE;

UPDATE admira.tenant_entitlements
SET trial_started_at = now() - interval '2 seconds',
    trial_ends_at = now() - interval '1 second'
WHERE tenant_id = :'grace_tenant'::uuid;

SET ROLE admira_runtime;
SELECT admira.expire_due_trials();
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenants AS t
    JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
    WHERE t.external_customer_id = 'grace-cycle-001'
      AND t.status = 'suspended' AND e.lifecycle_state = 'grace'
      AND e.grace_expires_at > now() + interval '29 days'
  ) THEN
    RAISE EXCEPTION 'trial did not enter the 30-day grace state';
  END IF;
END;
$$;

SET ROLE admira_scheduler;
SELECT admira.enqueue_due_trial_grace_reminders();
RESET ROLE;

DO $$
BEGIN
  IF (SELECT count(*) FROM admira.tenant_grace_reminders AS r
      JOIN admira.tenants AS t ON t.id = r.tenant_id
      WHERE t.external_customer_id = 'grace-cycle-001') <> 1 THEN
    RAISE EXCEPTION 'grace reminder was not queued exactly once';
  END IF;
END;
$$;

SET ROLE admira_provisioner;
SELECT lifecycle_state
FROM admira.operator_extend_trial(
  'grace-cycle-001', now() + interval '8 days', 'grace-validator'
);
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenants AS t
    JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
    WHERE t.external_customer_id = 'grace-cycle-001'
      AND t.status = 'active' AND e.lifecycle_state = 'trial'
      AND e.grace_started_at IS NULL AND e.grace_next_notification_at IS NULL
  ) THEN
    RAISE EXCEPTION 'grace extension did not restore pure trial';
  END IF;
END;
$$;

-- A later expiry is a new grace cycle: reminder number zero must be reusable
-- without colliding with the retained history from the first cycle.
SET ROLE admira_provisioner;
SELECT lifecycle_state
FROM admira.operator_expire_trial('grace-cycle-001', 'grace-validator');
RESET ROLE;

SET ROLE admira_scheduler;
SELECT admira.enqueue_due_trial_grace_reminders();
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM admira.tenant_grace_reminders AS r
    JOIN admira.tenants AS t ON t.id = r.tenant_id
    WHERE t.external_customer_id = 'grace-cycle-001'
      AND r.reminder_no = 0
    GROUP BY r.tenant_id
    HAVING count(*) = 2 AND count(DISTINCT r.grace_cycle_id) = 2
  ) THEN
    RAISE EXCEPTION 'a second grace cycle did not enqueue a fresh reminder zero';
  END IF;
END;
$$;

UPDATE admira.tenant_entitlements
SET grace_expires_at = now() - interval '1 second'
WHERE tenant_id = :'grace_tenant'::uuid;

SET ROLE admira_scheduler;
SELECT admira.mark_grace_runtime_suspended(:'grace_tenant'::uuid);
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM admira.grace_deletion_candidates())
     OR admira.delete_grace_tenant('00000000-0000-0000-0000-000000000001'::uuid) THEN
    RAISE EXCEPTION 'legacy grace deletion API is not fail-closed';
  END IF;
END;
$$;
SELECT deletion_claim_id AS grace_deletion_claim
FROM admira.claim_grace_deletion_candidates('grace-validator', 1, 900)
WHERE tenant_id = :'grace_tenant'::uuid
\gset

SELECT admira.delete_grace_tenant(
  :'grace_tenant'::uuid, :'grace_deletion_claim'::uuid
);
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenants
    WHERE external_customer_id = 'grace-cycle-001'
  ) THEN
    RAISE EXCEPTION 'database deletion succeeded without a host-purge marker';
  END IF;
END;
$$;

SET ROLE admira_provisioner;
DO $$
DECLARE transition_blocked boolean := false;
BEGIN
  BEGIN
    PERFORM admira.operator_extend_trial(
      'grace-cycle-001', now() + interval '9 days', 'grace-validator'
    );
  EXCEPTION WHEN SQLSTATE '55000' THEN
    transition_blocked := true;
  END;
  IF NOT transition_blocked THEN
    RAISE EXCEPTION 'extension crossed an active grace-deletion claim';
  END IF;
END;
$$;
RESET ROLE;

SET ROLE admira_scheduler;
SELECT admira.mark_grace_workspace_purged(
  :'grace_tenant'::uuid, :'grace_deletion_claim'::uuid
);
SELECT admira.delete_grace_tenant(
  :'grace_tenant'::uuid, :'grace_deletion_claim'::uuid
);
RESET ROLE;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM admira.tenants
    WHERE external_customer_id = 'grace-cycle-001'
  ) THEN
    RAISE EXCEPTION 'expired grace tenant remains after fenced deletion';
  END IF;
END;
$$;

ROLLBACK;
SELECT 'trial_grace_lifecycle_validation=passed';
