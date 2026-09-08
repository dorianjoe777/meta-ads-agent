BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('admira:021_operator_delete_trial', 0));

-- Claim before touching the filesystem. The existing lifecycle fence blocks
-- licensing/extensions throughout cleanup, including after a daemon crash.
CREATE OR REPLACE FUNCTION admira.operator_prepare_trial_delete(p_runtime_key text, p_actor text, p_created_at timestamptz)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE tid uuid; created timestamptz; ent admira.tenant_entitlements%ROWTYPE; claim uuid;
BEGIN
  IF coalesce(p_runtime_key,'') !~ '^[a-z0-9][a-z0-9-]{2,62}$'
     OR btrim(coalesce(p_actor,'')) = '' OR char_length(p_actor)>200 THEN
    RAISE EXCEPTION 'invalid deletion request' USING ERRCODE='22023';
  END IF;
  SELECT t.id, t.created_at INTO tid, created FROM admira.tenants t WHERE t.external_customer_id=p_runtime_key FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('already_deleted',true); END IF;
  IF p_created_at IS DISTINCT FROM created OR NOT EXISTS (
    SELECT 1 FROM admira.tenant_runtime_leases WHERE tenant_id=tid AND runtime_key=p_runtime_key
  ) THEN
    RAISE EXCEPTION 'stale or mismatched account' USING ERRCODE='55000';
  END IF;
  SELECT * INTO ent FROM admira.tenant_entitlements WHERE tenant_id=tid FOR UPDATE;
  IF NOT FOUND OR ent.license_id IS NOT NULL OR ent.lifecycle_state NOT IN ('trial','pending_claim','trial_expired','grace') THEN
    RAISE EXCEPTION 'only trial accounts can be deleted' USING ERRCODE='55000';
  END IF;
  IF ent.grace_deletion_claim_id IS NOT NULL THEN
    IF ent.grace_deletion_claimed_by <> 'operator-delete' THEN
      RAISE EXCEPTION 'cleanup already claimed' USING ERRCODE='55000';
    END IF;
    RETURN jsonb_build_object('claim_id',ent.grace_deletion_claim_id);
  END IF;
  UPDATE admira.tenant_entitlements SET lifecycle_state='grace', plan='suspended',
    grace_started_at=coalesce(grace_started_at,now()),
    grace_expires_at=now()+interval '100 years', grace_next_notification_at=NULL,
    updated_at=now() WHERE tenant_id=tid;
  claim := gen_random_uuid();
  UPDATE admira.tenant_entitlements SET grace_deletion_claim_id=claim,
    grace_deletion_claimed_at=now(), grace_deletion_claimed_by='operator-delete'
    WHERE tenant_id=tid;
  UPDATE admira.tenants SET status='suspended', updated_at=now() WHERE id=tid;
  PERFORM admira._cancel_grace_reminders(tid);
  RETURN jsonb_build_object('claim_id',claim);
END;
$$;

-- Called only after the host broker confirms removal of the workspace.
CREATE OR REPLACE FUNCTION admira.operator_finish_trial_delete(p_runtime_key text, p_claim uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = admira, pg_catalog AS $$
DECLARE tid uuid;
BEGIN
  SELECT t.id INTO tid FROM admira.tenants t
    JOIN admira.tenant_entitlements e ON e.tenant_id=t.id
    WHERE t.external_customer_id=p_runtime_key AND t.status='suspended'
      AND e.lifecycle_state='grace' AND e.grace_deletion_claim_id=p_claim
      AND e.grace_deletion_claimed_by='operator-delete' FOR UPDATE OF t,e;
  IF NOT FOUND THEN RAISE EXCEPTION 'deletion claim mismatch' USING ERRCODE='55000'; END IF;
  DELETE FROM admira.tenant_recovery_audit_events WHERE tenant_id=tid;
  DELETE FROM admira.gemini_pool_audit_events WHERE tenant_id=tid;
  DELETE FROM admira.tenants WHERE id=tid;
  RETURN jsonb_build_object('deleted',true);
END;
$$;
ALTER FUNCTION admira.operator_prepare_trial_delete(text,text,timestamptz) OWNER TO admira_control_owner;
ALTER FUNCTION admira.operator_finish_trial_delete(text,uuid) OWNER TO admira_control_owner;
REVOKE ALL ON FUNCTION admira.operator_prepare_trial_delete(text,text,timestamptz), admira.operator_finish_trial_delete(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admira.operator_prepare_trial_delete(text,text,timestamptz), admira.operator_finish_trial_delete(text,uuid) TO admira_provisioner;
COMMIT;
