-- Disposable validator only. It rolls every fixture back.
\set ON_ERROR_STOP on
BEGIN;

SET ROLE admira_provisioner;
SELECT trial_ends_at AS operator_trial_end
FROM admira.operator_create_trial('operator-trial-001', 'Operator Trial Fixture', 'operator-validator') \gset
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM admira.tenants AS t
    JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
    WHERE t.external_customer_id = 'operator-trial-001'
      AND t.status = 'active'
      AND e.lifecycle_state = 'trial'
      AND e.trial_started_at = t.created_at
      AND e.trial_ends_at = t.created_at + interval '5 days'
  ) THEN
    RAISE EXCEPTION 'operator trial was not anchored to account creation';
  END IF;
END;
$$;

SET ROLE admira_operator;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.operator_trial_accounts()
    WHERE runtime_key = 'operator-trial-001'
      AND lifecycle_state = 'trial'
      AND gemini_pool_ready = false
  ) THEN
    RAISE EXCEPTION 'operator trial projection is incomplete or leaks pool state';
  END IF;
  IF has_table_privilege('admira_operator', 'admira.tenants', 'SELECT,INSERT,UPDATE,DELETE')
     OR has_table_privilege('admira_operator', 'admira.tenant_entitlements', 'SELECT,INSERT,UPDATE,DELETE')
     OR has_function_privilege('admira_operator',
       'admira.operator_create_trial(text,text,text)', 'EXECUTE')
     OR has_function_privilege('admira_operator',
       'admira.operator_extend_trial(text,timestamp with time zone,text)', 'EXECUTE')
     OR has_function_privilege('admira_operator',
       'admira.operator_expire_trial(text,text)', 'EXECUTE') THEN
    RAISE EXCEPTION 'operator trial permissions are too broad';
  END IF;
END;
$$;
RESET ROLE;

CREATE TEMP TABLE operator_trial_requested AS
SELECT now() + interval '8 days' AS requested_end;
SELECT requested_end AS requested_operator_trial_end FROM operator_trial_requested \gset
SET ROLE admira_provisioner;
SELECT trial_ends_at
FROM admira.operator_extend_trial(
  'operator-trial-001', :'requested_operator_trial_end'::timestamptz, 'operator-validator'
);
-- Retrying the exact accepted timestamp must be a no-op rather than a second
-- audit row or a client-visible error.
SELECT trial_ends_at
FROM admira.operator_extend_trial(
  'operator-trial-001', :'requested_operator_trial_end'::timestamptz, 'operator-validator'
);
SELECT lifecycle_state
FROM admira.operator_expire_trial('operator-trial-001', 'operator-validator');
-- The retry remains an idempotent success so the host process can repeat a
-- failed runtime suspension without reopening the database transition.
SELECT lifecycle_state
FROM admira.operator_expire_trial('operator-trial-001', 'operator-validator');
RESET ROLE;

DO $$
BEGIN
  -- The expiry has changed its lifecycle state, but the audited prior end
  -- remains visible in the audit event and must match the requested instant.
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenant_audit_events AS event
    JOIN admira.tenants AS t ON t.id = event.tenant_id
    WHERE t.external_customer_id = 'operator-trial-001'
      AND event.event_type = 'trial_extended'
      AND (event.payload ->> 'trial_ends_at')::timestamptz =
          (SELECT requested_end FROM operator_trial_requested)
  ) THEN
    RAISE EXCEPTION 'operator trial extension did not preserve the exact timestamp';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_audit_events AS event
      JOIN admira.tenants AS t ON t.id = event.tenant_id
      WHERE t.external_customer_id = 'operator-trial-001'
        AND event.event_type = 'trial_extended') <> 1 THEN
    RAISE EXCEPTION 'operator trial extension retry duplicated its audit event';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenants AS t
    JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
    WHERE t.external_customer_id = 'operator-trial-001'
      AND t.status = 'suspended' AND e.lifecycle_state = 'grace'
  ) THEN
    RAISE EXCEPTION 'operator expiry did not fail closed';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_audit_events AS event
      JOIN admira.tenants AS t ON t.id = event.tenant_id
      WHERE t.external_customer_id = 'operator-trial-001'
        AND event.event_type = 'trial_expired_manually') <> 1 THEN
    RAISE EXCEPTION 'operator expiry retry duplicated its audit event';
  END IF;
END;
$$;

ROLLBACK;
SELECT 'operator_trial_provisioning_validation=passed';
