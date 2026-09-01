-- Disposable database validator only. All fixtures are rolled back.
-- It proves the same canonical access resolver governs both the image broker
-- and the central campaign compiler without ever accessing tenant OAuth.
\set ON_ERROR_STOP on
BEGIN;

SELECT encode(digest(convert_to('PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP','UTF8'),'sha256'),'hex') AS token_hash \gset

SET ROLE admira_provisioner;
SELECT tenant_id AS pool_switch_tenant
FROM admira.issue_telegram_tenant_claim(
  'pool-switch-001', 'Pool Switch Fixture', :'token_hash', 1800
) \gset
RESET ROLE;

SET ROLE admira_ingress;
SELECT tenant_id
FROM admira.claim_telegram_tenant(
  '123456', '96001', '96001', 'PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP'
);
RESET ROLE;

DO $$
BEGIN
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'pool-switch-001')
      ))
       <> 'central_sponsored' THEN
    RAISE EXCEPTION 'active trial did not retain automatic central route';
  END IF;
END;
$$;

SET ROLE admira_provisioner;
SELECT * FROM admira.transition_hosted_tenant_to_licensed(
  'pool-switch-001', 'ADMIRA-POOL-SWITCH-LICENSE-001',
  'tenant-env://pool-switch-001/GEMINI_API_KEY', repeat('a', 64),
  'pool-switch-validator'
);
RESET ROLE;

-- A fresh license is personal by default, even if its old trial timestamp is
-- still present.  The tenant can connect that account through /conectar_chatgpt.
DO $$
BEGIN
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'pool-switch-001')
      ))
       <> 'personal_chatgpt' THEN
    RAISE EXCEPTION 'new licensed tenant was not personal by default';
  END IF;
END;
$$;

SET ROLE admira_operator;
SELECT route AS enabled_route
FROM admira.operator_set_licensed_central_image_pool('pool-switch-001', true) \gset
RESET ROLE;

DO $$
BEGIN
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'pool-switch-001')
      ))
       <> 'central_sponsored'
     OR (SELECT route FROM admira.resolve_central_campaign_compiler_access_for_runtime('pool-switch-001'))
       <> 'central_sponsored' THEN
    RAISE EXCEPTION 'licensed pool opt-in did not reach image and campaign paths';
  END IF;
END;
$$;

-- A stale or future legacy sponsorship timestamp cannot silently bypass the
-- explicit off switch for a licensed tenant.
UPDATE admira.tenant_entitlements
SET image_sponsorship_ends_at = now() + interval '365 days'
WHERE tenant_id = :'pool_switch_tenant'::uuid;

SET ROLE admira_operator;
SELECT route AS disabled_route
FROM admira.operator_set_licensed_central_image_pool('pool-switch-001', false) \gset
RESET ROLE;

DO $$
BEGIN
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'pool-switch-001')
      ))
       <> 'personal_chatgpt'
     OR (SELECT route FROM admira.resolve_central_campaign_compiler_access_for_runtime('pool-switch-001'))
       <> 'personal_chatgpt' THEN
    RAISE EXCEPTION 'licensed pool opt-out did not restore personal route';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_audit_events
      WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'pool-switch-001')
        AND event_type = 'licensed_central_image_pool_changed') <> 2 THEN
    RAISE EXCEPTION 'licensed pool switch audit is not exact';
  END IF;
  IF has_table_privilege('admira_operator', 'admira.tenant_entitlements', 'SELECT,INSERT,UPDATE,DELETE')
     OR NOT has_function_privilege(
       'admira_operator',
       'admira.operator_set_licensed_central_image_pool(text,boolean)', 'EXECUTE'
     )
     OR has_function_privilege(
       'admira_runtime',
       'admira.operator_set_licensed_central_image_pool(text,boolean)', 'EXECUTE'
     ) THEN
    RAISE EXCEPTION 'licensed pool switch permissions are too broad';
  END IF;
END;
$$;

ROLLBACK;
SELECT 'licensed_central_image_pool_switch_validation=passed';
