from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "deploy" / "contabo" / "db" / "migrations" / "002_telegram_ingress_control.sql"
INITIAL = ROOT / "deploy" / "contabo" / "db" / "migrations" / "001_initial_multitenant.sql"


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_is_additive_and_reuses_the_original_update_ledger():
    text = sql()
    assert INITIAL.exists() and MIGRATION.exists()
    assert "ALTER TABLE admira.tenant_telegram_updates" in text
    assert "CREATE TABLE IF NOT EXISTS admira.tenant_telegram_inbox" not in text
    assert "UNIQUE (bot_id, update_id)" in INITIAL.read_text(encoding="utf-8")
    assert "DROP TABLE" not in text.upper()


def test_outbox_uses_ordered_opaque_media_references():
    text = sql()
    assert "CREATE TABLE IF NOT EXISTS admira.tenant_telegram_outbox" in text
    assert "char_length(body) BETWEEN 1 AND 4000" in text
    assert "media_ref ~ '^[a-f0-9]{32,64}" in text
    assert "media_path" not in text
    assert "source_update_id" in text and "source_job_run_id" in text
    assert "earlier.telegram_chat_id = o.telegram_chat_id" in text
    assert "earlier.dispatch_order < o.dispatch_order" in text


def test_claims_are_fenced_serialized_and_transactional():
    text = sql()
    assert len(re.findall(r"FOR UPDATE(?: OF [a-z]+)? SKIP LOCKED", text)) >= 3
    assert "active.tenant_id = u.tenant_id" in text
    completion = text.split("FUNCTION admira.complete_telegram_update", 1)[1].split("CREATE OR REPLACE FUNCTION", 1)[0]
    assert "_enqueue_telegram_parts" in completion
    assert "status = 'processed'" in completion
    assert "lease_token" in completion


def test_chat_binding_checks_both_chat_and_user():
    resolver = sql().split("FUNCTION admira.resolve_telegram_chat", 1)[1].split("CREATE OR REPLACE FUNCTION", 1)[0]
    assert "b.telegram_chat_id = btrim(p_chat_id)" in resolver
    assert "b.telegram_user_id = btrim(p_user_id)" in resolver


def test_functions_are_not_public_and_roles_have_no_table_access():
    text = sql()
    for role in ("admira_ingress", "admira_runtime", "admira_delivery", "admira_scheduler"):
        assert f"CREATE ROLE {role} NOLOGIN" in text
    assert "CREATE ROLE admira_control_owner NOLOGIN BYPASSRLS" in text
    assert "OWNER TO admira_control_owner" in text
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA admira" in text
    for name in re.findall(r"CREATE OR REPLACE FUNCTION\s+(admira\.[^(]+)", text):
        assert f"REVOKE ALL ON FUNCTION {name}" in text


def test_no_bot_secret_and_no_volatile_partial_index():
    text = sql().lower()
    assert "bot_token" not in text and "telegram_bot_token" not in text
    for block in re.findall(r"create index.*?;", text, re.S):
        assert "where" not in block or "now()" not in block


def test_scheduler_sync_and_completion_are_durable():
    text = sql()
    assert "FUNCTION admira.sync_hermes_scheduled_jobs" in text
    assert "ON CONFLICT (tenant_id, job_key) DO UPDATE" in text
    assert "FUNCTION admira.claim_due_scheduled_jobs" in text
    assert "FUNCTION admira.complete_scheduled_job_run" in text
    assert "source_job_run_id" in text


def test_registration_is_separate_least_privilege_operator_path():
    registration = ROOT / "deploy" / "contabo" / "db" / "migrations" / "003_hosted_tenant_registration.sql"
    text = registration.read_text(encoding="utf-8")
    assert "FUNCTION admira.register_hosted_tenant" in text
    assert "admira_provisioner NOLOGIN" in text
    assert "telegram chat already belongs to another tenant" in text
    assert "FUNCTION admira.issue_telegram_tenant_claim" in text
    assert "FUNCTION admira.claim_telegram_tenant" in text
    assert "public.digest(convert_to(p_raw_token, 'UTF8'), 'sha256')" in text
    assert "GRANT EXECUTE ON FUNCTION admira.claim_telegram_tenant" in text
    assert "OWNER TO admira_control_owner" in text
    assert "bot_token" not in text.lower()


def test_service_role_passwords_strip_only_secret_file_line_endings():
    bootstrap = ROOT / "deploy" / "contabo" / "db" / "bootstrap_service_roles.sql"
    text = bootstrap.read_text(encoding="utf-8")
    assert "regexp_replace(pg_read_file(item.secret_path), E'[\\\\r\\\\n]+$', '', 'g')" in text
    assert "btrim(pg_read_file(item.secret_path))" not in text
