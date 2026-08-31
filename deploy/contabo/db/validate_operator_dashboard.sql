-- Disposable database validator only. All fixtures are rolled back.
\set ON_ERROR_STOP on
BEGIN;

SET ROLE admira_operator;
SELECT admira.register_gemini_pool_project('operator-dashboard-fixture', 2, 'healthy') AS dashboard_project \gset
SELECT admira.register_gemini_pool_credential(:'dashboard_project'::uuid,
  'secret://operator/dashboard-fixture', repeat('f', 64), 'healthy', 'auth');
DO $$
BEGIN
  IF (SELECT count(*) FROM admira.operator_gemini_pool_status()
      WHERE project_ref = 'operator-dashboard-fixture' AND capacity = 2 AND health = 'healthy') <> 1 THEN
    RAISE EXCEPTION 'operator status projection failed';
  END IF;
  BEGIN
    PERFORM 1 FROM admira.gemini_pool_credentials;
    RAISE EXCEPTION 'operator can read pool credentials directly';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM admira.assign_hosted_gemini_trial('operator-forbidden-fixture');
    RAISE EXCEPTION 'operator can assign tenant credentials';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END;
$$;
RESET ROLE;

DO $$
DECLARE role_row record; table_name text;
BEGIN
  SELECT * INTO role_row FROM pg_roles WHERE rolname = 'admira_operator';
  IF role_row.rolcanlogin OR role_row.rolsuper OR role_row.rolcreatedb
     OR role_row.rolcreaterole OR role_row.rolreplication OR role_row.rolbypassrls
     OR pg_has_role('admira_operator', 'admira_provisioner', 'MEMBER') THEN
    RAISE EXCEPTION 'operator role has elevated privileges';
  END IF;
  FOREACH table_name IN ARRAY ARRAY['gemini_pool_projects', 'gemini_pool_credentials',
    'gemini_pool_assignments', 'gemini_pool_audit_events', 'tenants', 'tenant_license_contacts']
  LOOP
    IF has_table_privilege('admira_operator', 'admira.' || table_name, 'SELECT,INSERT,UPDATE,DELETE') THEN
      RAISE EXCEPTION 'operator has direct table privileges';
    END IF;
  END LOOP;
  IF NOT (SELECT bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class
          WHERE oid IN ('admira.gemini_pool_projects'::regclass,
                        'admira.gemini_pool_credentials'::regclass,
                        'admira.gemini_pool_assignments'::regclass,
                        'admira.gemini_pool_audit_events'::regclass)) THEN
    RAISE EXCEPTION 'operator pool RLS was weakened';
  END IF;
  IF has_function_privilege('admira_runtime', 'admira.operator_gemini_pool_status()', 'EXECUTE')
     OR has_function_privilege('admira_provisioner', 'admira.operator_gemini_pool_status()', 'EXECUTE')
     OR has_function_privilege('admira_operator', 'admira.assign_gemini_trial(uuid)', 'EXECUTE')
     OR has_function_privilege('admira_operator', 'admira.release_gemini_trial(uuid,text)', 'EXECUTE') THEN
    RAISE EXCEPTION 'operator function grants are not narrow';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_operator_login') THEN
    IF pg_has_role('admira_operator_login', 'admira_provisioner', 'MEMBER')
       OR NOT pg_has_role('admira_operator_login', 'admira_operator', 'MEMBER') THEN
      RAISE EXCEPTION 'operator login has incorrect group membership';
    END IF;
  END IF;
END;
$$;
ROLLBACK;
SELECT 'operator_dashboard_validation=passed';
