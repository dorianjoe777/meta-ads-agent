-- Run only in an empty disposable database after the migrations.
\set ON_ERROR_STOP on
DO $$
DECLARE project uuid; tenant uuid; runtime text; assigned uuid; i integer;
BEGIN
  FOR i IN 1..6 LOOP
    project := admira.register_gemini_pool_project('inventory-fixture-' || i, 2, 'healthy');
    PERFORM admira.register_gemini_pool_credential(project, 'secret://fixture/' || i,
      lpad(i::text,64,'0'), 'healthy', 'auth');
  END LOOP;
  FOR i IN 1..13 LOOP
    runtime := 'inventory-client-' || lpad(i::text,2,'0');
    INSERT INTO admira.tenants(external_customer_id,display_name,status)
      VALUES(runtime,runtime,'active') RETURNING id INTO tenant;
    INSERT INTO admira.tenant_entitlements(tenant_id,plan,lifecycle_state)
      VALUES(tenant,'trial','trial');
    INSERT INTO admira.tenant_runtime_leases(tenant_id,runtime_key,state)
      VALUES(tenant,runtime,'stopped');
    SELECT assignment_id INTO assigned FROM admira.assign_hosted_gemini_trial(runtime);
    IF (i <= 12 AND assigned IS NULL) OR (i = 13 AND assigned IS NOT NULL) THEN
      RAISE EXCEPTION 'Capacity enforcement failed at client %', i;
    END IF;
    IF i <= 12 AND (SELECT assignment_id FROM admira.assign_hosted_gemini_trial(runtime)) IS DISTINCT FROM assigned THEN
      RAISE EXCEPTION 'Repeat assignment changed identity';
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM admira.operator_gemini_pool_inventory()
      WHERE used=2 AND available=0 AND cardinality(clients)=2) <> 6 THEN
    RAISE EXCEPTION 'Inventory occupancy is incorrect';
  END IF;
  PERFORM admira.release_hosted_gemini_trial('inventory-client-01','operator');
  IF (SELECT sum(available) FROM admira.operator_gemini_pool_inventory()) <> 1 THEN
    RAISE EXCEPTION 'Released slot not available';
  END IF;
  PERFORM admira.assign_hosted_gemini_trial('inventory-client-13');
  UPDATE admira.tenant_entitlements SET lifecycle_state='licensed'
    WHERE tenant_id=(SELECT tenant_id FROM admira.tenant_runtime_leases WHERE runtime_key='inventory-client-13');
  IF (SELECT sum(available) FROM admira.operator_gemini_pool_inventory()) <> 1 THEN
    RAISE EXCEPTION 'Licensing did not free slot';
  END IF;
  UPDATE admira.gemini_pool_credentials SET health='unhealthy';
  IF (SELECT sum(available) FROM admira.operator_gemini_pool_inventory()) <> 0 THEN
    RAISE EXCEPTION 'Unhealthy credentials counted as available';
  END IF;
  IF has_function_privilege('admira_runtime', 'admira.operator_gemini_pool_inventory()', 'EXECUTE') THEN
    RAISE EXCEPTION 'Runtime can read operator inventory';
  END IF;
END $$;
SET ROLE admira_operator;
SELECT count(*) AS visible_projects FROM admira.operator_gemini_pool_inventory();
RESET ROLE;
SELECT 'gemini_inventory_validation=passed';
