import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/contabo/db/migrations/009_telegram_license_recovery.sql").read_text()
VALIDATOR = (ROOT / "deploy/contabo/db/validate_telegram_license_recovery.sql").read_text()


class TelegramLicenseRecoveryMigrationTests(unittest.TestCase):
    def test_disposable_validator_uses_a_non_colliding_destination(self):
        # validate_control_plane.sql reserves (123456, 9001) for its buyer
        # fixture. Recovery must use its own bot/chat so the test exercises a
        # real rebind instead of correctly rejecting a cross-tenant theft.
        self.assertIn("'765432', true", VALIDATOR)
        self.assertIn("'765432', '9901', '9901'", VALIDATOR)
        self.assertNotIn("'123456', '9001', '9001'", VALIDATOR)

    def test_is_transactional_and_keeps_active_binding_contract(self):
        self.assertIn("BEGIN;", SQL)
        self.assertIn("COMMIT;", SQL)
        self.assertIn("CREATE TABLE IF NOT EXISTS admira.tenant_telegram_binding_history", SQL)
        self.assertNotRegex(SQL, r"DROP CONSTRAINT.*tenant_telegram_bindings")
        self.assertNotRegex(SQL, r"ALTER TABLE admira\.tenant_telegram_bindings")
        self.assertNotIn("tenant_license_contacts_active_email_uq", SQL)
        self.assertIn("tenant_license_contacts_active_license_uq", SQL)

    def test_never_stores_raw_identity_or_otp(self):
        self.assertIn("email_hmac bytea", SQL)
        self.assertIn("license_hmac bytea", SQL)
        self.assertIn("otp_hash bytea", SQL)
        self.assertIn("encrypted_payload bytea", SQL)
        self.assertIn("delivery_ref text", SQL)
        executable = re.sub(r"--[^\n]*|/\*.*?\*/", "", SQL, flags=re.S).lower()
        self.assertNotRegex(executable, r"\b(email|license|otp)\s+(address|value|code)\s+(text|varchar)")
        self.assertNotIn("p_email text", executable)
        self.assertNotIn("p_otp text", executable)

    def test_real_or_decoy_and_uniform_chat_reply(self):
        begin = SQL.split("CREATE OR REPLACE FUNCTION admira.begin_telegram_recovery", 1)[1]
        begin = begin.split("CREATE OR REPLACE FUNCTION admira.claim_recovery_chat_outbox", 1)[0]
        self.assertIn("public_outcome := 'recovery_pending'", begin)
        self.assertIn("resolved_tenant := NULL", begin)
        self.assertIn("_enqueue_recovery_chat_reply", begin)
        self.assertIn("recovery_pending", SQL)
        self.assertIn("UNIQUE (request_id, template_code)", SQL)

    def test_incomplete_commands_get_durable_instructions_without_success_forgery(self):
        self.assertIn("'recovery_instructions'", SQL)
        self.assertIn("CREATE OR REPLACE FUNCTION admira.enqueue_telegram_recovery_public_reply", SQL)
        public_reply = SQL.split(
            "CREATE OR REPLACE FUNCTION admira.enqueue_telegram_recovery_public_reply", 1
        )[1].split("CREATE OR REPLACE FUNCTION admira._recovery_rate_allowed", 1)[0]
        self.assertIn("('recovery_instructions', 'recovery_failed')", public_reply)
        self.assertNotIn("recovery_completed')", public_reply)
        self.assertIn(
            "admira.enqueue_telegram_recovery_public_reply(uuid, text, text, text, text) TO admira_recovery",
            SQL,
        )

    def test_atomic_rebind_and_immutable_history(self):
        confirm = SQL.split("CREATE OR REPLACE FUNCTION admira.confirm_telegram_recovery", 1)[1]
        self.assertIn("FOR UPDATE", confirm)
        self.assertIn("DELETE FROM admira.tenant_telegram_bindings", confirm)
        self.assertIn("ON CONFLICT DO NOTHING", confirm)
        self.assertIn("prevent_recovery_history_mutation", SQL)
        self.assertIn("BEFORE UPDATE OR DELETE", SQL)
        self.assertNotIn("SET tenant_id = EXCLUDED.tenant_id", confirm)
        self.assertIn("FOR old_binding IN", confirm)
        self.assertIn("tenant_telegram_binding_history", confirm)
        self.assertIn("identity_version = identity_version + 1", confirm)
        self.assertIn("status = CASE WHEN id = challenge.id THEN 'consumed' ELSE 'invalidated' END", confirm)
        self.assertIn("recovery_completed", confirm)
        self.assertIn("recovery_failed", confirm)

    def test_rate_limits_and_fenced_chat_outbox(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS admira.tenant_recovery_rate_limits", SQL)
        self.assertIn("scope IN ('chat', 'email', 'license')", SQL)
        self.assertIn("claim_recovery_chat_outbox", SQL)
        self.assertIn("FOR UPDATE SKIP LOCKED", SQL)
        self.assertIn("status = 'sending' AND lease_token = p_lease_token", SQL)
        self.assertIn("telegram_rate_limited", SQL)
        self.assertIn("ALTER TABLE admira.tenant_recovery_rate_limits ENABLE ROW LEVEL SECURITY", SQL)
        self.assertIn("ALTER TABLE admira.tenant_recovery_rate_limits FORCE ROW LEVEL SECURITY", SQL)
        self.assertIn("CREATE POLICY recovery_owner_only ON admira.tenant_recovery_rate_limits", SQL)

    def test_provider_neutral_email_outbox_is_fenced_and_bounded(self):
        self.assertIn("CREATE OR REPLACE FUNCTION admira.claim_recovery_email_outbox", SQL)
        self.assertIn("CREATE OR REPLACE FUNCTION admira.ack_recovery_email_outbox", SQL)
        self.assertIn("encrypted_payload bytea", SQL)
        self.assertIn("delivery_ref text", SQL)
        email_claim = SQL.split("CREATE OR REPLACE FUNCTION admira.claim_recovery_email_outbox", 1)[1]
        email_claim = email_claim.split("CREATE OR REPLACE FUNCTION admira.ack_recovery_email_outbox", 1)[0]
        self.assertIn("challenge.request_id", email_claim)
        self.assertIn("FOR UPDATE SKIP LOCKED", email_claim)
        self.assertIn("status = 'sending' AND o.leased_until <= now()", email_claim)
        email_ack = SQL.split("CREATE OR REPLACE FUNCTION admira.ack_recovery_email_outbox", 1)[1]
        email_ack = email_ack.split("CREATE OR REPLACE FUNCTION admira.confirm_telegram_recovery", 1)[0]
        self.assertIn("status = 'sending' AND lease_token = p_lease_token", email_ack)
        self.assertIn("attempt_count >= p_max_attempts", email_ack)
        self.assertIn("provider_unavailable", email_ack)
        self.assertIn("p_retry_after_seconds NOT BETWEEN 1 AND 86400", email_ack)

    def test_email_delivery_role_is_execute_only(self):
        self.assertIn("CREATE ROLE admira_email_delivery NOLOGIN NOBYPASSRLS", SQL)
        self.assertIn("ALTER ROLE admira_email_delivery NOLOGIN NOBYPASSRLS", SQL)
        self.assertIn("GRANT USAGE ON SCHEMA admira TO admira_email_delivery", SQL)
        self.assertIn("REVOKE ALL ON TABLE admira.tenant_recovery_delivery_outbox FROM admira_email_delivery", SQL)
        self.assertIn("TO admira_email_delivery", SQL)
        self.assertRegex(SQL, r"GRANT EXECUTE ON FUNCTION admira\.claim_recovery_email_outbox\(text, integer, integer\),")
        self.assertIn("admira.ack_recovery_email_outbox(uuid, uuid, boolean, text, integer, integer) TO admira_email_delivery;", SQL)
        self.assertNotRegex(SQL, r"GRANT .* ON TABLE .*tenant_recovery_delivery_outbox.* TO admira_email_delivery")

    def test_chat_outbox_claim_qualifies_return_columns(self):
        chat_claim = SQL.split("CREATE OR REPLACE FUNCTION admira.claim_recovery_chat_outbox", 1)[1]
        chat_claim = chat_claim.split("CREATE OR REPLACE FUNCTION admira.ack_recovery_chat_outbox", 1)[0]
        self.assertIn("SELECT claimed.id, claimed.request_id, claimed.bot_id", chat_claim)
        self.assertNotIn("SELECT id, request_id, bot_id, chat_id", chat_claim)

    def test_recovery_requires_an_existing_binding_for_the_requester_bot(self):
        begin = SQL.split("CREATE OR REPLACE FUNCTION admira.begin_telegram_recovery", 1)[1]
        begin = begin.split("CREATE OR REPLACE FUNCTION admira.claim_recovery_chat_outbox", 1)[0]
        self.assertIn("tenant_telegram_bindings existing_binding", begin)
        self.assertIn("existing_binding.bot_id = btrim(p_bot_id)", begin)

    def test_rls_roles_and_grants(self):
        self.assertGreaterEqual(SQL.count("ENABLE ROW LEVEL SECURITY"), 5)
        self.assertGreaterEqual(SQL.count("FORCE ROW LEVEL SECURITY"), 5)
        self.assertIn("REVOKE ALL ON TABLE admira.tenant_license_contacts", SQL)
        self.assertIn("TO admira_provisioner", SQL)
        self.assertIn("CREATE ROLE admira_recovery NOLOGIN NOBYPASSRLS", SQL)
        self.assertIn("TO admira_recovery", SQL)
        self.assertNotRegex(
            SQL,
            r"GRANT EXECUTE ON FUNCTION admira\.begin_telegram_recovery[\s\S]*?TO admira_ingress",
        )
        self.assertIn("TO admira_delivery", SQL)
        self.assertIn("ALTER TABLE admira.telegram_recovery_chat_outbox OWNER TO admira_control_owner", SQL)
        self.assertNotRegex(SQL, r"GRANT .* ON TABLE .* TO admira_(ingress|runtime|delivery|scheduler|provisioner)")


if __name__ == "__main__":
    unittest.main()
