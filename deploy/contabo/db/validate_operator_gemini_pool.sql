-- Destructive validator for a fresh disposable PostgreSQL database only.
\set ON_ERROR_STOP on

SELECT gen_random_uuid() AS pool_tenant \gset
INSERT INTO admira.tenants(id, external_customer_id, display_name, status)
VALUES (:'pool_tenant', 'gemini-pool-cycle-001', 'Pool Cycle', 'active');
INSERT INTO admira.tenant_entitlements(tenant_id, plan, lifecycle_state)
VALUES (:'pool_tenant', 'trial', 'trial');
INSERT INTO admira.tenant_runtime_leases(tenant_id, runtime_key, state)
VALUES (:'pool_tenant', 'gemini-pool-cycle-001', 'stopped');

SET ROLE admira_provisioner;
SELECT admira.register_gemini_pool_project('project-fixture-001', 1, 'healthy') AS pool_project \gset
SELECT admira.register_gemini_pool_credential(:'pool_project'::uuid,
  'secret://operator/gemini-fixture', repeat('a', 64), 'healthy', 'auth') AS pool_credential \gset
SELECT * FROM admira.assign_hosted_gemini_trial('gemini-pool-cycle-001') \gset
SELECT admira.finalize_hosted_gemini_trial('gemini-pool-cycle-001', :'assignment_id'::uuid) AS finalized \gset
SELECT admira.finalize_hosted_gemini_trial('gemini-pool-cycle-001', :'assignment_id'::uuid) AS finalized_idempotent \gset
RESET ROLE;

DO $$
DECLARE assigned_secret_ref text;
BEGIN
  SELECT c.secret_ref INTO assigned_secret_ref
  FROM admira.gemini_pool_assignments a
  JOIN admira.gemini_pool_credentials c ON c.id = a.credential_id
  JOIN admira.tenants t ON t.id = a.tenant_id
  WHERE t.external_customer_id = 'gemini-pool-cycle-001' AND a.status = 'active';
  IF assigned_secret_ref <> 'secret://operator/gemini-fixture' THEN
    RAISE EXCEPTION 'pool assignment returned the wrong opaque secret reference';
  END IF;
  IF (SELECT count(*) FROM admira.gemini_pool_assignments WHERE status = 'active') <> 1 THEN
    RAISE EXCEPTION 'pool assignment was not created';
  END IF;
  IF (SELECT count(*) FROM admira.gemini_pool_audit_events WHERE event_type = 'assigned') <> 1 THEN
    RAISE EXCEPTION 'pool assignment audit missing';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_provider_credentials
      WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'gemini-pool-cycle-001')
        AND provider = 'gemini' AND purpose = 'text' AND origin = 'operator_pool' AND status = 'active'
        AND secret_ref = 'tenant-env://gemini-pool-cycle-001/GEMINI_API_KEY') <> 1 THEN
    RAISE EXCEPTION 'finalized Gemini metadata missing or not operator-owned';
  END IF;
END;
$$;

-- Capacity one cannot be over-assigned; a second tenant receives no row.
SELECT gen_random_uuid() AS pool_tenant_two \gset
INSERT INTO admira.tenants(id, external_customer_id, display_name, status)
VALUES (:'pool_tenant_two', 'gemini-pool-cycle-002', 'Pool Cycle Two', 'active');
INSERT INTO admira.tenant_entitlements(tenant_id, plan, lifecycle_state)
VALUES (:'pool_tenant_two', 'trial', 'trial');
INSERT INTO admira.tenant_runtime_leases(tenant_id, runtime_key, state)
VALUES (:'pool_tenant_two', 'gemini-pool-cycle-002', 'stopped');
SET ROLE admira_provisioner;
SELECT count(*) AS second_assignment_count FROM admira.assign_hosted_gemini_trial('gemini-pool-cycle-002') \gset
RESET ROLE;
SET ROLE admira_provisioner;
SELECT admira.release_hosted_gemini_trial('gemini-pool-cycle-002', 'operator') AS missing_release_count \gset
RESET ROLE;
DO $$
BEGIN
  IF (SELECT count(*) FROM admira.gemini_pool_assignments a
      JOIN admira.tenants t ON t.id = a.tenant_id
      WHERE t.external_customer_id = 'gemini-pool-cycle-002' AND a.status = 'active') <> 0 THEN
    RAISE EXCEPTION 'pool capacity was over-assigned';
  END IF;
END;
$$;

-- Licensed transition releases the active assignment through the migration trigger.
UPDATE admira.tenant_entitlements SET lifecycle_state = 'licensed' WHERE tenant_id = :'pool_tenant'::uuid;
DO $$
BEGIN
  IF (SELECT count(*) FROM admira.gemini_pool_assignments a
      JOIN admira.tenants t ON t.id = a.tenant_id
      WHERE t.external_customer_id = 'gemini-pool-cycle-001' AND a.status = 'active') <> 0
     OR (SELECT count(*) FROM admira.gemini_pool_assignments a
         JOIN admira.tenants t ON t.id = a.tenant_id
         WHERE t.external_customer_id = 'gemini-pool-cycle-001' AND a.release_reason = 'licensed') <> 1 THEN
    RAISE EXCEPTION 'licensed transition did not release Gemini assignment';
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT ((SELECT relrowsecurity FROM pg_class WHERE oid = 'admira.gemini_pool_projects'::regclass)
      AND (SELECT relforcerowsecurity FROM pg_class WHERE oid = 'admira.gemini_pool_projects'::regclass)
      AND (SELECT relrowsecurity FROM pg_class WHERE oid = 'admira.gemini_pool_assignments'::regclass)
      AND (SELECT relforcerowsecurity FROM pg_class WHERE oid = 'admira.gemini_pool_assignments'::regclass)) THEN
    RAISE EXCEPTION 'pool tables do not force RLS';
  END IF;
  IF has_table_privilege('admira_runtime', 'admira.gemini_pool_projects', 'SELECT')
     OR has_table_privilege('admira_provisioner', 'admira.gemini_pool_assignments', 'SELECT')
     OR has_function_privilege('admira_runtime', 'admira.assign_gemini_trial(uuid)', 'EXECUTE')
     OR has_function_privilege('admira_provisioner', 'admira.assign_gemini_trial(uuid)', 'EXECUTE')
     OR has_function_privilege('admira_provisioner', 'admira.release_gemini_trial(uuid,text)', 'EXECUTE')
     OR has_function_privilege('admira_runtime', 'admira.assign_hosted_gemini_trial(text)', 'EXECUTE')
     OR has_function_privilege('admira_runtime', 'admira.finalize_hosted_gemini_trial(text,uuid)', 'EXECUTE')
     OR has_function_privilege('admira_runtime', 'admira.release_hosted_gemini_trial(text,text)', 'EXECUTE') THEN
    RAISE EXCEPTION 'pool roles are not least privilege';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'admira'
               AND table_name IN ('gemini_pool_projects','gemini_pool_credentials','gemini_pool_assignments')
               AND column_name ~ '(api_key|token|password|secret_value|raw_key)') THEN
    RAISE EXCEPTION 'pool schema contains a raw secret column';
  END IF;
END;
$$;

SELECT 'operator_gemini_pool_validation=passed';
