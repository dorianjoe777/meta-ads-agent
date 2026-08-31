from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "contabo" / "compose.yaml"


class ContaboComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = COMPOSE.read_text(encoding="utf-8")

    def test_control_plane_is_not_published_to_the_host(self):
        self.assertNotIn('"0.0.0.0:', self.text)
        self.assertIn('"127.0.0.1:${ADMIRA_OPERATOR_PORT:-8791}:8791"', self.text)
        self.assertEqual(self.text.count("    ports:\n"), 1)
        self.assertIn("internal: true", self.text)
        self.assertIn("no-new-privileges:true", self.text)

    def test_postgres_migration_directory_matches_repository(self):
        self.assertIn("./db/migrations:/docker-entrypoint-initdb.d:ro", self.text)
        self.assertNotIn("bootstrap_service_roles.sql:/control-bootstrap", self.text)
        self.assertTrue((COMPOSE.parent / "db" / "migrations" / "001_initial_multitenant.sql").is_file())
        apply_script = (COMPOSE.parent / "apply-control-plane.sh").read_text(encoding="utf-8")
        self.assertIn('< "$ROOT_DIR/db/bootstrap_service_roles.sql"', apply_script)

    def test_redis_runs_unprivileged_after_secret_staging(self):
        redis = self.text.split("  redis:\n", 1)[1].split("\n  # Docker secrets", 1)[0]
        self.assertIn('user: "999:999"', redis)
        self.assertIn("redis-init:\n        condition: service_completed_successfully", redis)
        self.assertIn("/run/redis-auth/redis_users.acl", redis)
        self.assertIn("redis_auth:/run/redis-auth:ro", redis)
        self.assertIn("cap_drop:\n      - ALL", redis)
        self.assertIn("read_only: true", redis)
        self.assertNotIn("cap_add:", redis)

    def test_redis_init_stages_acl_without_network_or_secret_env(self):
        init = self.text.split("\n  redis-init:\n", 1)[1].split("\n\nnetworks:\n", 1)[0]
        self.assertIn('network_mode: none', init)
        self.assertIn('user: "0:0"', init)
        self.assertIn("/run/secrets/redis_users_acl /redis-auth/redis_users.acl", init)
        self.assertIn("-m 0400 -o 999 -g 999", init)
        self.assertIn("chown -R 999:999 /data", init)
        self.assertIn("redis_auth:/redis-auth", init)
        self.assertNotIn("REDISCLI_AUTH", init)
        self.assertNotIn("-a ", init)
        self.assertNotIn("--requirepass", init)
        for capability in ("CHOWN", "DAC_OVERRIDE", "FOWNER"):
            self.assertIn(f"      - {capability}", init)
        for forbidden in ("NET_ADMIN", "SYS_ADMIN", "SYS_PTRACE"):
            self.assertNotIn(forbidden, init)

    def test_redis_healthcheck_does_not_expose_password_in_argv(self):
        redis = self.text.split("  redis:\n", 1)[1].split("\n  # Docker secrets", 1)[0]
        self.assertIn("REDISCLI_AUTH=", redis)
        self.assertNotIn('redis-cli --no-auth-warning -a', redis)

    def test_redis_auth_volume_is_declared(self):
        self.assertIn("  redis_auth:\n", self.text)

    def test_postgres_service_passwords_are_staged_without_network(self):
        init = self.text.split("\n  postgres-secrets-init:\n", 1)[1].split("\n\n  redis:\n", 1)[0]
        postgres = self.text.split("\n  postgres:\n", 1)[1].split("\n\n  postgres-secrets-init:\n", 1)[0]
        self.assertIn("network_mode: none", init)
        self.assertIn('user: "0:0"', init)
        self.assertIn("-m 0400 -o 999 -g 999", init)
        self.assertIn("postgres_auth:/postgres-auth", init)
        self.assertIn("postgres-secrets-init:\n        condition: service_completed_successfully", postgres)
        self.assertIn("postgres_auth:/run/admira-db-secrets:ro", postgres)
        self.assertNotIn("environment:", init)
        for capability in ("CHOWN", "DAC_OVERRIDE", "FOWNER"):
            self.assertIn(f"      - {capability}", init)

    def test_recovery_database_login_is_fail_closed_and_isolated(self):
        init = self.text.split("\n  postgres-secrets-init:\n", 1)[1].split("\n\n  redis:\n", 1)[0]
        postgres = self._service("postgres", "postgres-secrets-init")
        self.assertIn("recovery_db_password", postgres)
        self.assertIn("recovery_db_password", init)
        self.assertIn("recovery_db_password.txt", self.text)
        poller = self._service("telegram-poller", "runtime-worker")
        self.assertIn('ADMIRA_TELEGRAM_RECOVERY_READY: "${ADMIRA_TELEGRAM_RECOVERY_READY:-false}"', poller)
        self.assertIn("ADMIRA_RECOVERY_DB_USER: admira_recovery_login", poller)
        self.assertIn("recovery_db_password", poller)
        self.assertIn("recovery_hmac_key", poller)
        self.assertIn("recovery_delivery_key", poller)
        self.assertNotIn("recovery_db_password", self._service("runtime-worker", "telegram-delivery"))
        self.assertNotIn("recovery_db_password", self._service("central-image-broker", "telegram-poller"))
        bootstrap = (COMPOSE.parent / "bootstrap-control-plane.sh").read_text(encoding="utf-8")
        self.assertIn("recovery_db_password", bootstrap)
        roles = (COMPOSE.parent / "db" / "bootstrap_service_roles.sql").read_text(encoding="utf-8")
        self.assertIn("admira_recovery_login", roles)
        self.assertIn("'admira_recovery'", roles)
        self.assertIn("recovery_db_password", roles)

    def test_recovery_email_profile_has_no_telegram_or_tenant_authority(self):
        service = self._service("recovery-email", "scheduler-worker")
        self.assertIn('profiles: ["recovery-email"]', service)
        self.assertIn("ADMIRA_DB_USER: admira_email_delivery_login", service)
        self.assertIn("email_delivery_db_password", service)
        self.assertIn("recovery_delivery_key", service)
        self.assertIn("email_egress", service)
        for forbidden in (
            "telegram_bot_token", "runtime_broker_key", "recovery_hmac_key",
            "/srv/admira/tenants", "docker.sock",
        ):
            self.assertNotIn(forbidden, service)

    def test_recovery_control_modules_are_built_and_crypto_dependency_is_pinned(self):
        dockerfile = (COMPOSE.parent / "Control.Dockerfile").read_text(encoding="utf-8")
        requirements = (COMPOSE.parent / "app-requirements.txt").read_text(encoding="utf-8")
        for module in (
            "recovery_identity.py", "recovery_service.py",
            "recovery_email_worker.py", "recovery_smtp.py",
        ):
            self.assertIn(module, dockerfile)
        self.assertIn("cryptography==50.0.1", requirements)

    def test_bootstrap_stages_recovery_keys_and_empty_smtp_credentials(self):
        bootstrap = (COMPOSE.parent / "bootstrap-control-plane.sh").read_text(encoding="utf-8")
        self.assertIn("recovery_hmac_key", bootstrap)
        self.assertIn("recovery_delivery_key.txt", bootstrap)
        self.assertIn("openssl rand -base64 32", bootstrap)
        self.assertIn('touch "$SECRETS_DIR/smtp_username.txt" "$SECRETS_DIR/smtp_password.txt"', bootstrap)
        self.assertIn('chmod 600 "$SECRETS_DIR"/*.txt', bootstrap)

    def test_email_delivery_login_is_separate_and_email_egress_is_opt_in(self):
        roles = (COMPOSE.parent / "db" / "bootstrap_service_roles.sql").read_text(encoding="utf-8")
        self.assertIn("admira_email_delivery_login", roles)
        self.assertIn("admira_email_delivery", roles)
        self.assertIn("email_delivery_db_password", roles)
        self.assertNotIn("admira_email_delivery_login', 'admira_recovery'", roles)
        email = self._service("recovery-email", "scheduler-worker")
        self.assertIn('profiles: ["recovery-email"]', email)
        self.assertIn("- email_egress", email)
        self.assertNotIn("- telegram_egress", email)
        self.assertNotIn("- image_provider_egress", email)

    def _service(self, name: str, next_name: str | None = None) -> str:
        value = self.text.split(f"\n  {name}:\n", 1)[1]
        # A new opt-in service may be inserted between former neighbours.
        # Parse only this service block so an isolation assertion never
        # accidentally includes the following service's secrets/networks.
        import re
        return re.split(r"\n  [a-z][a-z0-9-]*:\n|\nnetworks:\n", value, maxsplit=1)[0]

    def test_buyer_services_are_opt_in_and_token_isolated(self):
        poller = self._service("telegram-poller", "runtime-worker")
        runtime = self._service("runtime-worker", "telegram-delivery")
        delivery = self._service("telegram-delivery", "recovery-email")
        scheduler = self._service("scheduler-worker")
        for service in (poller, runtime, delivery, scheduler):
            self.assertIn('profiles: ["buyers"]', service)
            self.assertIn("read_only: true", self.text.split("services:", 1)[0])
        for token_holder in (poller, delivery):
            self.assertIn("telegram_bot_token", token_holder)
            self.assertIn("telegram_egress", token_holder)
            self.assertNotIn("runtime_broker_key", token_holder)
            self.assertNotIn("admira-runtime-broker", token_holder)
        for runtime_holder in (runtime, scheduler):
            self.assertIn("runtime_broker_key", runtime_holder)
            self.assertIn("admira-runtime-broker", runtime_holder)
            self.assertNotIn("telegram_bot_token", runtime_holder)
            self.assertNotIn("telegram_egress", runtime_holder)
            self.assertIn("ADMIRA_BROKER_GID", runtime_holder)
        for spool_holder in (poller, delivery):
            self.assertIn("ADMIRA_SPOOL_GID", spool_holder)
        self.assertIn("scale: ${RUNTIME_WORKER_REPLICAS:-1}", runtime)
        self.assertNotIn("scale:", poller)
        self.assertNotIn("scale:", delivery)
        self.assertNotIn("scale:", scheduler)

    def test_capacity_preflight_is_read_only_and_does_not_touch_secrets(self):
        preflight = (COMPOSE.parent / "capacity-preflight.sh").read_text(encoding="utf-8")
        self.assertIn("docker stats --no-stream", preflight)
        self.assertIn("docker inspect --format", preflight)
        self.assertIn("MemAvailable", preflight)
        self.assertIn('$1 == "Mem:"', preflight)
        self.assertIn('$1 == "Swap:"', preflight)
        self.assertIn("memory_available_bytes=", preflight)
        self.assertIn("swap_free_bytes=", preflight)
        self.assertNotIn("NR==1 || NR==2 || NR==3", preflight)
        self.assertIn("swapon --show", preflight)
        self.assertIn("/proc/sys/vm/swappiness", preflight)
        self.assertNotIn("swapon -a", preflight)
        self.assertNotIn("docker compose up", preflight)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", preflight)

    def test_buyer_services_have_distinct_database_roles(self):
        expected = {
            "telegram-poller": "admira_ingress_login",
            "runtime-worker": "admira_runtime_login",
            "telegram-delivery": "admira_delivery_login",
            "scheduler-worker": "admira_scheduler_login",
        }
        names = list(expected)
        for index, name in enumerate(names):
            next_name = names[index + 1] if index + 1 < len(names) else None
            self.assertIn(f"ADMIRA_DB_USER: {expected[name]}", self._service(name, next_name))

    def test_central_image_service_is_dormant_and_credential_isolated(self):
        central = self._service("central-image-broker", "telegram-poller")
        self.assertIn('profiles: ["central-images"]', central)
        self.assertIn("image: ${CENTRAL_IMAGE_IMAGE:-admira-ia-hosted:r91-canary-000000000000}", central)
        self.assertNotIn("admira-ia:r91", central)
        self.assertIn("ADMIRA_DB_USER: admira_image_login", central)
        self.assertIn("image_db_password", central)
        self.assertIn("central-codex-auth", central)
        self.assertIn("ADMIRA_CENTRAL_CODEX_AUTH_ROOT", central)
        self.assertIn("ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS", central)
        self.assertIn("codex-auth-pool", central)
        self.assertIn("central-image-keys", central)
        self.assertIn("central-image-exchange", central)
        self.assertIn("image_provider_egress", central)
        self.assertIn("ADMIRA_CENTRAL_IMAGE_MAX_CLIENTS: ${ADMIRA_CENTRAL_IMAGE_MAX_CLIENTS:-32}", central)
        self.assertIn("read_only: true", central)
        self.assertIn('user: "${ADMIRA_SERVICE_UID:-1001}:${ADMIRA_CENTRAL_IMAGE_GID:-19093}"', central)
        self.assertNotIn("cap_add:", central)
        self.assertIn("cap_drop:\n      - ALL", central)
        for forbidden in ("telegram_bot_token", "runtime_broker_key", "/srv/admira/tenants", "docker.sock"):
            self.assertNotIn(forbidden, central)

    def test_central_image_preparation_never_starts_or_activates_service(self):
        script = (COMPOSE.parent / "prepare-central-image-broker.sh").read_text(encoding="utf-8")
        self.assertIn("/etc/admira/central-image-keys", script)
        self.assertIn("/srv/admira/shared/central-codex-auth", script)
        self.assertIn("2-8 accounts", script)
        self.assertIn('for account_id in "${account_ids[@]}"', script)
        self.assertIn('CENTRAL_IMAGE_GID="${ADMIRA_CENTRAL_IMAGE_GID:-19093}"', script)
        self.assertIn("groupadd --system --gid", script)
        self.assertIn('install -d -m "$mode" -o "$SERVICE_USER" -g "$CENTRAL_IMAGE_GROUP"', script)
        self.assertNotIn("docker compose up", script)
        self.assertNotIn("ADMIRA_CENTRAL_IMAGE_READY=true", script)

    def test_central_socket_group_is_documented_and_stable(self):
        env = (COMPOSE.parent / ".env.example").read_text(encoding="utf-8")
        self.assertIn("ADMIRA_CENTRAL_IMAGE_GID=19093", env)
        self.assertIn("ADMIRA_CENTRAL_IMAGE_MAX_CLIENTS=32", env)
        self.assertIn("ADMIRA_CENTRAL_IMAGE_GID", self.text)
        self.assertIn("ADMIRA_CENTRAL_CODEX_AUTH_ROOT=/app/runtime/hermes/codex-auth-pool", env)
        self.assertIn("ADMIRA_CENTRAL_CODEX_ACCOUNT_IDS=primary,secondary", env)

    def test_shared_control_image_has_one_build_owner(self):
        poller = self._service("telegram-poller", "runtime-worker")
        self.assertIn("build:\n      context: .\n      dockerfile: Control.Dockerfile", poller)
        self.assertEqual(self.text.count("dockerfile: Control.Dockerfile"), 1)

    def test_broker_installer_restarts_versioned_code(self):
        installer = (COMPOSE.parent / "install-runtime-broker.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl restart admira-runtime-broker.service", installer)
        self.assertNotIn("enable --now admira-runtime-broker.service", installer)
        self.assertIn("Environment=ADMIRA_MAX_ACTIVE_TENANTS=", installer)
        self.assertIn('done < "$ROOT_DIR/.env"', installer)
        self.assertNotIn("hosted_gemini_api_key.txt", installer)
        self.assertNotIn("/etc/admira/hosted-gemini-api-key", installer)
        bootstrap = (COMPOSE.parent / "bootstrap-control-plane.sh").read_text(encoding="utf-8")
        self.assertNotIn("hosted_gemini_api_key.txt", bootstrap)

    def test_apply_streams_migrations_from_the_exact_release(self):
        apply_script = (COMPOSE.parent / "apply-control-plane.sh").read_text(encoding="utf-8")
        self.assertIn('for migration in "$ROOT_DIR"/db/migrations/*.sql', apply_script)
        self.assertIn('< "$migration"', apply_script)
        self.assertNotIn('for migration in /docker-entrypoint-initdb.d/*.sql', apply_script)

    def test_tenants_and_control_services_never_mount_docker_socket(self):
        self.assertNotIn("/var/run/docker.sock", self.text)

    def test_external_networks_are_scoped_to_their_provider_services(self):
        self.assertIn("telegram_egress:", self.text)
        self.assertIn("email_egress:", self.text)
        self.assertIn("control_private:\n    internal: true", self.text)
        poller = self._service("telegram-poller", "runtime-worker")
        delivery = self._service("telegram-delivery", "recovery-email")
        email = self._service("recovery-email", "scheduler-worker")
        for service in (poller, delivery):
            self.assertIn("- telegram_egress", service)
            self.assertNotIn("- email_egress", service)
        self.assertIn("- email_egress", email)
        self.assertNotIn("- telegram_egress", email)


if __name__ == "__main__":
    unittest.main()
