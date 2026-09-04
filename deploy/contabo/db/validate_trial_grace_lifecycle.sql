-- Disposable validator for migration 018. Never run against production data.
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
SET trial_ends_at = now() - interval '1 second'
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

ROLLBACK;
SELECT 'trial_grace_lifecycle_validation=passed';
