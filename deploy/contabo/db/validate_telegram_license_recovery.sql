-- Destructive recovery fixture for a fresh disposable PostgreSQL database only.
-- Never execute this validator against the live control plane.
\set ON_ERROR_STOP on

SELECT gen_random_uuid() AS recovery_tenant \gset
INSERT INTO admira.tenants (id, external_customer_id, display_name, status)
VALUES (:'recovery_tenant', 'recovery-cycle-001', 'Recovery Cycle', 'active');
INSERT INTO admira.tenant_runtime_leases (tenant_id, runtime_key)
VALUES (:'recovery_tenant', 'recovery-cycle-001');
INSERT INTO admira.tenant_entitlements
  (tenant_id, plan, lifecycle_state, licensed_at, paid_through)
VALUES (:'recovery_tenant', 'paid', 'licensed', now(), now());

-- The operator registers metadata only; no email or license plaintext enters DB.
SET ROLE admira_provisioner;
SELECT admira.register_verified_license_contact(
  :'recovery_tenant', repeat('a', 64), repeat('b', 64),
  'secret://recovery-cycle-001/email', now(), 'fixture-operator'
) AS contact_registered;
RESET ROLE;

INSERT INTO admira.tenant_telegram_bindings
  (tenant_id, telegram_user_id, telegram_chat_id, bot_id, is_primary)
VALUES (:'recovery_tenant', '100', '200', '765432', true);

-- Incomplete recovery commands receive durable instructions without creating
-- a challenge or exposing any identity factor.
SET ROLE admira_recovery;
SELECT admira.enqueue_telegram_recovery_public_reply(
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid,
  '765432', '9900', '9900', 'recovery_instructions'
);
RESET ROLE;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM admira.telegram_recovery_chat_outbox
    WHERE request_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid
      AND template_code = 'recovery_instructions'
  ) THEN
    RAISE EXCEPTION 'recovery instructions were not durably queued';
  END IF;
END;
$$;

-- A valid request and its fixed generic pending chat reply.
SET ROLE admira_recovery;
CREATE TEMP TABLE recovery_begin_snapshot AS
SELECT request_id, public_outcome
FROM admira.begin_telegram_recovery(
  '11111111-1111-4111-8111-111111111111'::uuid, '765432', '9901', '9901',
  repeat('a', 64), repeat('b', 64), repeat('c', 64), decode(repeat('ab', 32), 'hex'), 'delivery-v1'
);
RESET ROLE;

DO $$
BEGIN
  IF (SELECT public_outcome FROM recovery_begin_snapshot) <> 'recovery_pending' THEN
    RAISE EXCEPTION 'valid recovery did not return uniform pending outcome';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_recovery_delivery_outbox) <> 1 THEN
    RAISE EXCEPTION 'valid recovery did not queue encrypted email intent';
  END IF;
  IF (SELECT count(*) FROM admira.telegram_recovery_chat_outbox
      WHERE template_code = 'recovery_pending') <> 1 THEN
    RAISE EXCEPTION 'valid recovery did not queue pending chat reply';
  END IF;
END;
$$;

-- The email worker receives only an opaque reference and encrypted envelope.
-- Its role has function execution but no direct table access, and a stale
-- lease token cannot acknowledge a newer claim.
SET ROLE admira_email_delivery;
CREATE TEMP TABLE recovery_email_claim AS
SELECT * FROM admira.claim_recovery_email_outbox('email-worker-001', 20, 120);
DO $$
BEGIN
  IF (SELECT count(*) FROM recovery_email_claim) <> 1 THEN
    RAISE EXCEPTION 'email outbox claim did not return the queued intent';
  END IF;
  IF (SELECT delivery_ref FROM recovery_email_claim) <> 'secret://recovery-cycle-001/email' THEN
    RAISE EXCEPTION 'email claim did not return the opaque delivery reference';
  END IF;
  IF (SELECT octet_length(encrypted_payload) FROM recovery_email_claim) < 32 THEN
    RAISE EXCEPTION 'email claim returned an invalid encrypted envelope';
  END IF;
  IF admira.ack_recovery_email_outbox(
       (SELECT outbox_id FROM recovery_email_claim), gen_random_uuid(), true) THEN
    RAISE EXCEPTION 'stale email lease token was accepted';
  END IF;
  IF NOT admira.ack_recovery_email_outbox(
       (SELECT outbox_id FROM recovery_email_claim),
       (SELECT lease_token FROM recovery_email_claim), true) THEN
    RAISE EXCEPTION 'valid email lease acknowledgement failed';
  END IF;
END;
$$;
RESET ROLE;

-- A wrong identity creates a decoy challenge and the same public response,
-- but cannot create an email delivery job.
SET ROLE admira_recovery;
SELECT public_outcome
FROM admira.begin_telegram_recovery(
  '22222222-2222-4222-8222-222222222222'::uuid, '765432', '9902', '9902',
  repeat('d', 64), repeat('e', 64), repeat('f', 64), decode(repeat('cd', 32), 'hex'), 'delivery-v1'
);
RESET ROLE;

-- A valid identity presented through another bot remains a decoy.
SET ROLE admira_recovery;
SELECT public_outcome
FROM admira.begin_telegram_recovery(
  '33333333-3333-4333-8333-333333333333'::uuid, '999999', '9003', '9003',
  repeat('a', 64), repeat('b', 64), repeat('1', 64), decode(repeat('ef', 32), 'hex'), 'delivery-v1'
);
RESET ROLE;
DO $$
BEGIN
  IF (SELECT tenant_id FROM admira.tenant_recovery_challenges
      WHERE request_id = '33333333-3333-4333-8333-333333333333'::uuid) IS NOT NULL THEN
    RAISE EXCEPTION 'different-bot recovery was not converted to a decoy';
  END IF;
  IF (SELECT count(*) FROM admira.tenant_recovery_delivery_outbox) <> 1 THEN
    RAISE EXCEPTION 'different-bot decoy created an email delivery';
  END IF;
END;
$$;

-- Confirming the real OTP atomically removes the active binding, records its
-- history, inserts the new binding, invalidates siblings and queues success.
SET ROLE admira_recovery;
CREATE TEMP TABLE recovery_confirm_snapshot AS
SELECT completed, public_outcome
FROM admira.confirm_telegram_recovery(
  '11111111-1111-4111-8111-111111111111'::uuid, '765432', '9901', '9901', repeat('c', 64)
);
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM recovery_confirm_snapshot
    WHERE public_outcome = 'recovery_completed' AND completed
  ) THEN
    RAISE EXCEPTION 'valid OTP did not complete recovery';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings
                 WHERE tenant_id = (SELECT id FROM admira.tenants
                                    WHERE external_customer_id = 'recovery-cycle-001')
                   AND bot_id = '765432' AND telegram_chat_id = '9901') THEN
    RAISE EXCEPTION 'new Telegram binding was not installed';
  END IF;
  IF EXISTS (SELECT 1 FROM admira.tenant_telegram_bindings
             WHERE tenant_id = (SELECT id FROM admira.tenants
                                WHERE external_customer_id = 'recovery-cycle-001')
               AND telegram_chat_id = '200') THEN
    RAISE EXCEPTION 'old Telegram binding was not removed';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM admira.tenant_telegram_binding_history
                 WHERE tenant_id = (SELECT id FROM admira.tenants
                                    WHERE external_customer_id = 'recovery-cycle-001')
                   AND old_chat_id = '200' AND new_chat_id = '9901') THEN
    RAISE EXCEPTION 'binding history was not recorded';
  END IF;
  IF (SELECT identity_version FROM admira.tenant_license_contacts
      WHERE tenant_id = (SELECT id FROM admira.tenants
                         WHERE external_customer_id = 'recovery-cycle-001')) <> 2 THEN
    RAISE EXCEPTION 'identity version was not bumped';
  END IF;
  IF (SELECT count(*) FROM admira.telegram_recovery_chat_outbox
      WHERE request_id = '11111111-1111-4111-8111-111111111111'::uuid
        AND template_code = 'recovery_completed') <> 1 THEN
    RAISE EXCEPTION 'success chat reply was not queued';
  END IF;
END;
$$;

-- Replay and wrong/expired OTPs are uniformly failed and cannot rebind.
SET ROLE admira_recovery;
SELECT completed, public_outcome
FROM admira.confirm_telegram_recovery(
  '11111111-1111-4111-8111-111111111111'::uuid, '765432', '9901', '9901', repeat('c', 64)
);
SELECT completed, public_outcome
FROM admira.confirm_telegram_recovery(
  '22222222-2222-4222-8222-222222222222'::uuid, '765432', '9902', '9902', repeat('f', 64)
);
RESET ROLE;

DO $$
BEGIN
  IF (SELECT count(*) FROM admira.tenant_telegram_bindings
      WHERE tenant_id = (SELECT id FROM admira.tenants
                         WHERE external_customer_id = 'recovery-cycle-001')) <> 1 THEN
    RAISE EXCEPTION 'replay or decoy confirmation changed binding state';
  END IF;
  IF has_table_privilege('admira_ingress', 'admira.tenant_license_contacts', 'SELECT')
     OR has_table_privilege('admira_ingress', 'admira.telegram_recovery_chat_outbox', 'SELECT')
     OR has_function_privilege(
       'admira_ingress',
       'admira.begin_telegram_recovery(uuid,text,text,text,text,text,text,bytea,text)',
       'EXECUTE'
     )
     OR NOT has_function_privilege(
       'admira_recovery',
       'admira.begin_telegram_recovery(uuid,text,text,text,text,text,text,bytea,text)',
       'EXECUTE'
     )
     OR NOT has_function_privilege(
       'admira_recovery',
       'admira.enqueue_telegram_recovery_public_reply(uuid,text,text,text,text)',
       'EXECUTE'
     )
     OR NOT has_function_privilege(
       'admira_delivery',
       'admira.claim_recovery_chat_outbox(text,integer,integer)',
       'EXECUTE'
     ) THEN
    RAISE EXCEPTION 'recovery roles are not least privilege';
  END IF;
  IF NOT (
    (SELECT relrowsecurity FROM pg_class WHERE oid = 'admira.tenant_recovery_rate_limits'::regclass)
    AND (SELECT relforcerowsecurity FROM pg_class WHERE oid = 'admira.tenant_recovery_rate_limits'::regclass)
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'admira' AND tablename = 'tenant_recovery_rate_limits'
      AND policyname = 'recovery_owner_only'
  ) THEN
    RAISE EXCEPTION 'recovery rate limits are missing fail-closed RLS';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'admira.tenant_telegram_binding_history'::regclass
      AND tgname = 'tenant_telegram_binding_history_immutable'
      AND NOT tgisinternal
  ) THEN
    RAISE EXCEPTION 'recovery binding history is missing immutable trigger';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'admira'
      AND table_name IN ('tenant_license_contacts', 'tenant_recovery_challenges',
                         'tenant_recovery_delivery_outbox')
      AND column_name ~ '(email|license|otp|password|token)'
      AND column_name NOT IN ('email_hmac', 'license_hmac', 'otp_hash', 'otp_ciphertext',
                              'request_id', 'lease_token')
  ) THEN
    RAISE EXCEPTION 'recovery schema contains a plaintext identity or credential column';
  END IF;
END;
$$;

SELECT 'telegram_license_recovery_validation=passed';
