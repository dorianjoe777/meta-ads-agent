-- Disposable database validator only. All fixtures are rolled back.
\set ON_ERROR_STOP on
BEGIN;

SELECT encode(digest(convert_to('SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS','UTF8'),'sha256'),'hex') AS token_hash \gset

SET ROLE admira_provisioner;
SELECT tenant_id AS sponsorship_tenant
FROM admira.issue_telegram_tenant_claim(
  'sponsorship-cycle-001', 'Sponsorship Cycle', :'token_hash', 1800
) \gset
RESET ROLE;

SET ROLE admira_ingress;
SELECT tenant_id
FROM admira.claim_telegram_tenant(
  '123456', '95001', '95001', 'SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS'
);
RESET ROLE;

CREATE TEMP TABLE sponsorship_target AS
SELECT now() + interval '8 days' AS requested_end;
SELECT requested_end FROM sponsorship_target \gset

SET ROLE admira_operator;
SELECT image_sponsorship_ends_at AS first_end
FROM admira.operator_set_image_sponsorship_end(
  'sponsorship-cycle-001', :'requested_end'::timestamptz
) \gset
SELECT image_sponsorship_ends_at AS retried_end
FROM admira.operator_set_image_sponsorship_end(
  'sponsorship-cycle-001', :'requested_end'::timestamptz
) \gset
RESET ROLE;

DO $$
BEGIN
  IF (SELECT count(*) FROM admira.operator_tenant_sponsorship_status()
      WHERE runtime_key = 'sponsorship-cycle-001'
        AND lifecycle_state = 'trial'
        AND route = 'central_sponsored'
        AND effective_sponsorship_ends_at =
          (SELECT requested_end FROM sponsorship_target)) <> 1 THEN
    RAISE EXCEPTION 'operator sponsorship status is incorrect';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_audit_events
      WHERE tenant_id = (SELECT id FROM admira.tenants
                         WHERE external_customer_id = 'sponsorship-cycle-001')
        AND event_type = 'image_sponsorship_extended') <> 1 THEN
    RAISE EXCEPTION 'sponsorship extension retry was not idempotent';
  END IF;
  IF has_table_privilege('admira_operator', 'admira.tenant_entitlements', 'SELECT,INSERT,UPDATE,DELETE')
     OR has_table_privilege('admira_operator', 'admira.tenants', 'SELECT,INSERT,UPDATE,DELETE')
     OR has_function_privilege('admira_operator',
       'admira.transition_hosted_tenant_to_licensed(text,text,text,text,text)', 'EXECUTE') THEN
    RAISE EXCEPTION 'operator sponsorship grants are too broad';
  END IF;
END;
$$;

SET ROLE admira_operator;
DO $$
BEGIN
  BEGIN
    PERFORM * FROM admira.operator_set_image_sponsorship_end(
      'sponsorship-cycle-001', now() + interval '1 day'
    );
    RAISE EXCEPTION 'operator shortened an active sponsorship';
  EXCEPTION WHEN invalid_parameter_value THEN NULL;
  END;
END;
$$;
RESET ROLE;

ROLLBACK;
SELECT 'personal_chatgpt_sponsorship_validation=passed';
