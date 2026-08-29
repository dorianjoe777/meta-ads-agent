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
        self.assertNotIn("ports:", self.text)
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

    def _service(self, name: str, next_name: str | None = None) -> str:
        value = self.text.split(f"\n  {name}:\n", 1)[1]
        return value.split("\nnetworks:\n", 1)[0] if next_name is None else value.split(f"\n  {next_name}:\n", 1)[0]

    def test_buyer_services_are_opt_in_and_token_isolated(self):
        poller = self._service("telegram-poller", "runtime-worker")
        runtime = self._service("runtime-worker", "telegram-delivery")
        delivery = self._service("telegram-delivery", "scheduler-worker")
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
        self.assertIn("/etc/admira/hosted-gemini-api-key", installer)
        self.assertIn("rm -f /etc/admira/hosted-gemini-api-key", installer)

    def test_apply_streams_migrations_from_the_exact_release(self):
        apply_script = (COMPOSE.parent / "apply-control-plane.sh").read_text(encoding="utf-8")
        self.assertIn('for migration in "$ROOT_DIR"/db/migrations/*.sql', apply_script)
        self.assertIn('< "$migration"', apply_script)
        self.assertNotIn('for migration in /docker-entrypoint-initdb.d/*.sql', apply_script)

    def test_tenants_and_control_services_never_mount_docker_socket(self):
        self.assertNotIn("/var/run/docker.sock", self.text)

    def test_only_telegram_services_receive_external_network(self):
        self.assertIn("telegram_egress:", self.text)
        self.assertIn("control_private:\n    internal: true", self.text)


if __name__ == "__main__":
    unittest.main()
