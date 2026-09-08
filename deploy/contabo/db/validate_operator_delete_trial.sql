-- All fixtures and assertions are rolled back; no host workspace is touched.
\set ON_ERROR_STOP on
BEGIN;
SET ROLE admira_provisioner;
SELECT * FROM admira.operator_create_trial('operator-delete-validator', 'Disposable deletion validator', 'operator-validator');
RESET ROLE;
DO $$
DECLARE tid uuid; created timestamptz; claim uuid; again uuid;
BEGIN
  SELECT id,created_at INTO tid,created FROM admira.tenants WHERE external_customer_id='operator-delete-validator';
  INSERT INTO admira.tenant_telegram_bindings(tenant_id,telegram_user_id,telegram_chat_id,bot_id)
    VALUES(tid,'delete-validator-user','delete-validator-chat','delete-validator-bot');
  BEGIN
    PERFORM admira.operator_prepare_trial_delete('operator-delete-validator','validator',created-interval '1 second');
    RAISE EXCEPTION 'stale identity was accepted';
  EXCEPTION WHEN SQLSTATE '55000' THEN NULL;
  END;
  UPDATE admira.tenant_entitlements SET license_id='delete-validator-license',plan='paid',lifecycle_state='licensed' WHERE tenant_id=tid;
  BEGIN
    PERFORM admira.operator_prepare_trial_delete('operator-delete-validator','validator',created);
    RAISE EXCEPTION 'licensed account was accepted';
  EXCEPTION WHEN SQLSTATE '55000' THEN NULL;
  END;
  UPDATE admira.tenant_entitlements SET license_id=NULL,plan='trial',lifecycle_state='trial' WHERE tenant_id=tid;
  claim := (admira.operator_prepare_trial_delete('operator-delete-validator','validator',created)->>'claim_id')::uuid;
  again := (admira.operator_prepare_trial_delete('operator-delete-validator','validator',created)->>'claim_id')::uuid;
  IF claim IS NULL OR claim IS DISTINCT FROM again THEN RAISE EXCEPTION 'claim is not retryable'; END IF;
  BEGIN
    UPDATE admira.tenant_entitlements SET plan='paid',lifecycle_state='licensed' WHERE tenant_id=tid;
    RAISE EXCEPTION 'deletion did not fence relicensing';
  EXCEPTION WHEN SQLSTATE '55000' THEN NULL;
  END;
  BEGIN
    PERFORM admira.operator_finish_trial_delete('operator-delete-validator',gen_random_uuid());
    RAISE EXCEPTION 'wrong claim was accepted';
  EXCEPTION WHEN SQLSTATE '55000' THEN NULL;
  END;
  PERFORM admira.operator_finish_trial_delete('operator-delete-validator',claim);
  IF EXISTS(SELECT 1 FROM admira.tenants WHERE id=tid)
     OR EXISTS(SELECT 1 FROM admira.tenant_telegram_bindings WHERE tenant_id=tid)
     OR EXISTS(SELECT 1 FROM admira.tenant_runtime_leases WHERE tenant_id=tid)
     OR EXISTS(SELECT 1 FROM admira.tenant_entitlements WHERE tenant_id=tid) THEN
    RAISE EXCEPTION 'tenant records were not removed';
  END IF;
  IF NOT (admira.operator_prepare_trial_delete('operator-delete-validator','validator',created)->>'already_deleted')::boolean THEN
    RAISE EXCEPTION 'completed deletion retry failed';
  END IF;
  IF has_function_privilege('admira_operator','admira.operator_prepare_trial_delete(text,text,timestamptz)','EXECUTE')
    OR has_function_privilege('admira_operator','admira.operator_finish_trial_delete(text,uuid)','EXECUTE') THEN
    RAISE EXCEPTION 'dashboard role has destructive direct privileges';
  END IF;
END $$;
-- Exercise SECURITY DEFINER privileges as the actual host role as well.
SET ROLE admira_provisioner;
SELECT * FROM admira.operator_create_trial('operator-delete-role-validator', 'Disposable role validator', 'operator-validator');
RESET ROLE;
SELECT created_at AS deletion_created FROM admira.tenants WHERE external_customer_id='operator-delete-role-validator' \gset
SET ROLE admira_provisioner;
SELECT admira.operator_prepare_trial_delete('operator-delete-role-validator','validator',:'deletion_created'::timestamptz)->>'claim_id' AS deletion_claim \gset
SELECT admira.operator_finish_trial_delete('operator-delete-role-validator',:'deletion_claim'::uuid);
RESET ROLE;
ROLLBACK;
SELECT 'operator_delete_trial_validation=passed';
