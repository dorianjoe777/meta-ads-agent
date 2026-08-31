-- Destructive lifecycle fixture for a fresh, disposable PostgreSQL database
-- only. Never run this against the live Admira control database.
\set ON_ERROR_STOP on

SELECT encode(digest(convert_to('BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB','UTF8'),'sha256'),'hex') AS token_hash \gset

SET ROLE admira_provisioner;
SELECT tenant_id AS lifecycle_tenant
FROM admira.issue_telegram_tenant_claim(
  'trial-cycle-001', 'Trial Cycle', :'token_hash', 1800
) \gset
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenant_entitlements
    WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
      AND lifecycle_state = 'pending_claim'
      AND trial_started_at IS NULL AND trial_ends_at IS NULL
  ) THEN
    RAISE EXCEPTION 'claim issuance started the trial clock early';
  END IF;
END;
$$;

SET ROLE admira_ingress;
SELECT tenant_id AS claimed_tenant
FROM admira.claim_telegram_tenant(
  '123456', '91001', '91001', 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'
) \gset
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenant_telegram_bindings AS b
    JOIN admira.tenants AS t ON t.id = b.tenant_id
    WHERE t.external_customer_id = 'trial-cycle-001'
      AND b.bot_id = '123456' AND b.telegram_chat_id = '91001'
  ) THEN
    RAISE EXCEPTION 'claim resolved the wrong tenant';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenant_entitlements
    WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
      AND lifecycle_state = 'trial'
      AND trial_started_at <= now()
      AND trial_ends_at BETWEEN now() + interval '4 days 23 hours'
                            AND now() + interval '5 days 1 minute'
  ) THEN
    RAISE EXCEPTION 'claim did not start one five-day trial';
  END IF;
END;
$$;

-- Force the boundary instead of waiting five days.
UPDATE admira.tenant_entitlements
SET trial_started_at = now() - interval '2 seconds',
    trial_ends_at = now() - interval '1 second'
WHERE tenant_id = :'lifecycle_tenant'::uuid;
SET ROLE admira_runtime;
SELECT admira.expire_due_trials() AS expired_count \gset
SELECT route AS expired_route
FROM admira.resolve_tenant_image_access(:'lifecycle_tenant'::uuid) \gset
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.tenants AS t
    JOIN admira.tenant_entitlements AS e ON e.tenant_id = t.id
    WHERE t.id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
      AND t.status = 'suspended' AND e.lifecycle_state = 'trial_expired'
  ) THEN
    RAISE EXCEPTION 'trial expiry did not suspend tenant and entitlement';
  END IF;
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
      )) <> 'blocked' THEN
    RAISE EXCEPTION 'trial expiry did not fail closed';
  END IF;
END;
$$;

SET ROLE admira_runtime;
SELECT admira.expire_due_trials() AS second_expired_count \gset
RESET ROLE;

SET ROLE admira_provisioner;
SELECT image_sponsorship_ends_at AS first_sponsorship_end
FROM admira.transition_hosted_tenant_to_licensed(
  'trial-cycle-001',
  'ADMIRA-TEST-LICENSE-001',
  'tenant-env://trial-cycle-001/GEMINI_API_KEY',
  repeat('a', 64),
  'lifecycle-fixture'
) \gset
RESET ROLE;

SET ROLE admira_runtime;
SELECT route AS sponsored_route
FROM admira.resolve_tenant_image_access(:'lifecycle_tenant'::uuid) \gset
RESET ROLE;

CREATE TEMP TABLE lifecycle_sponsorship_snapshot AS
SELECT image_sponsorship_ends_at
FROM admira.tenant_entitlements
WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001');

-- An identical retry must not extend sponsorship or create another provider
-- version/audit event.
SET ROLE admira_provisioner;
SELECT image_sponsorship_ends_at AS retried_sponsorship_end
FROM admira.transition_hosted_tenant_to_licensed(
  'trial-cycle-001',
  'ADMIRA-TEST-LICENSE-001',
  'tenant-env://trial-cycle-001/GEMINI_API_KEY',
  repeat('a', 64),
  'lifecycle-fixture'
) \gset
RESET ROLE;

DO $$
BEGIN
  IF admira.expire_due_trials() <> 0 THEN
    RAISE EXCEPTION 'expiry was not idempotent';
  END IF;
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
      )) <> 'personal_chatgpt'
     OR (SELECT image_sponsorship_ends_at FROM lifecycle_sponsorship_snapshot)
        <> (SELECT image_sponsorship_ends_at FROM admira.tenant_entitlements
            WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')) THEN
    RAISE EXCEPTION 'late license retry changed personal image access';
  END IF;
  IF (SELECT image_sponsorship_ends_at FROM lifecycle_sponsorship_snapshot)
       <> (SELECT trial_ends_at FROM admira.tenant_entitlements
           WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')) THEN
    RAISE EXCEPTION 'licensing restarted the original five-day sponsorship';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_provider_credentials
      WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
        AND provider = 'gemini'
        AND purpose = 'text' AND status = 'active') <> 1 THEN
    RAISE EXCEPTION 'license retry duplicated active Gemini metadata';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_audit_events
      WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
        AND event_type = 'tenant_licensed') <> 1 THEN
    RAISE EXCEPTION 'license retry duplicated the audit event';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenants
                 WHERE external_customer_id = 'trial-cycle-001' AND status = 'active') THEN
    RAISE EXCEPTION 'licensing did not reactivate the tenant';
  END IF;
END;
$$;

DO $$
BEGIN
  BEGIN
    PERFORM * FROM admira.transition_tenant_to_licensed(
      (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001'),
      'ADMIRA-DIFFERENT-LICENSE',
      'tenant-env://trial-cycle-001/GEMINI_API_KEY',
      repeat('a', 64),
      'lifecycle-fixture'
    );
    RAISE EXCEPTION 'a different license replaced the existing identity';
  EXCEPTION WHEN unique_violation THEN
    NULL;
  END;
  BEGIN
    PERFORM * FROM admira.issue_telegram_tenant_claim(
      'trial-cycle-001', 'Trial Cycle', repeat('c', 64), 1800
    );
    RAISE EXCEPTION 'an activated tenant received another initial claim';
  EXCEPTION WHEN object_not_in_prerequisite_state THEN
    NULL;
  END;
END;
$$;

-- Rotation retains unlimited retired history while keeping exactly one active
-- credential version.
SET ROLE admira_provisioner;
SELECT admira.record_tenant_provider_credential(
  :'lifecycle_tenant'::uuid, 'gemini', 'text',
  'tenant-env://trial-cycle-001/GEMINI_API_KEY', repeat('b', 64), 'customer'
);
SELECT admira.record_tenant_provider_credential(
  :'lifecycle_tenant'::uuid, 'gemini', 'text',
  'tenant-env://trial-cycle-001/GEMINI_API_KEY', repeat('b', 64), 'customer'
);
RESET ROLE;

UPDATE admira.tenant_entitlements
SET image_sponsorship_ends_at = now() - interval '1 second'
WHERE tenant_id = :'lifecycle_tenant'::uuid;
SET ROLE admira_runtime;
SELECT route AS personal_route
FROM admira.resolve_tenant_image_access(:'lifecycle_tenant'::uuid) \gset
RESET ROLE;

DO $$
BEGIN
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
      )) <> 'personal_chatgpt' THEN
    RAISE EXCEPTION 'expired sponsorship did not enable personal ChatGPT';
  END IF;
END;
$$;

UPDATE admira.tenants SET status = 'suspended'
WHERE id = :'lifecycle_tenant'::uuid;
SET ROLE admira_runtime;
SELECT route AS suspended_route
FROM admira.resolve_tenant_image_access(:'lifecycle_tenant'::uuid) \gset
RESET ROLE;

DO $$
BEGIN
  IF (SELECT route FROM admira.resolve_tenant_image_access(
        (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
      )) <> 'blocked' THEN
    RAISE EXCEPTION 'image route ignored sponsorship or tenant status';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_provider_credentials
      WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
        AND provider = 'gemini'
        AND purpose = 'text' AND status = 'active') <> 1
     OR (SELECT count(*) FROM admira.tenant_provider_credentials
         WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'trial-cycle-001')
           AND provider = 'gemini'
           AND purpose = 'text' AND status = 'retired') <> 1 THEN
    RAISE EXCEPTION 'provider rotation history is incorrect';
  END IF;
  IF has_table_privilege('admira_runtime', 'admira.tenant_provider_credentials', 'SELECT')
     OR has_table_privilege('admira_provisioner', 'admira.tenant_provider_credentials', 'SELECT') THEN
    RAISE EXCEPTION 'service role has direct provider-metadata table access';
  END IF;
END;
$$;

SELECT 'trial_lifecycle_validation=passed';
