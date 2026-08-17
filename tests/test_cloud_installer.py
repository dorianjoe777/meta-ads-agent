from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from product_config import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "installer" / "mac" / "admira-mac-cloud-engine.sh"
GATE = ROOT / "installer" / "mac" / "admira-cloud-access-gate.py"
RESET = ROOT / "installer" / "mac" / "admira-cloud-clean-reset.sh"


class MacCloudInstallerTests(unittest.TestCase):
    def test_jxa_json_is_safe_for_command_substitution(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn(
            "/usr/bin/osascript -l JavaScript 2>&1 <<'JXA'",
            source,
            "osascript emits console.log on stderr on macOS; the engine must merge it into stdout",
        )

    def test_digitalocean_ssh_key_endpoint_uses_current_account_keys_route(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("GET /account/keys?per_page=200", source)
        self.assertIn("POST /account/keys", source)
        self.assertNotIn("GET /ssh_keys", source)
        self.assertNotIn("POST /ssh_keys", source)

    def test_cloud_init_does_not_race_remote_docker_install(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("touch /var/lib/admira-cloud-init-ready", source)
        self.assertNotIn("package_update: true", source)
        self.assertNotIn("packages:\\n  - ca-certificates", source)
        self.assertIn("wait_for_package_manager", source)
        self.assertIn("dpkg --configure -a", source)

    def test_remote_wait_counter_is_not_expanded_on_the_mac(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn(r"attempts=\$((attempts + 1))", source)
        self.assertNotIn("attempts=$((attempts + 1))", source)

    def test_cloud_runtime_env_is_synchronized_before_dashboard_health_check(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("/app/runtime/.env", source)
        self.assertIn("exec -T meta-ads-agent python3", source)
        self.assertIn("restart meta-ads-agent", source)
        self.assertIn("LAN_ACCESS_ENABLED", source)
        self.assertIn("DIGITALOCEAN_DROPLET_ID", source)

    def test_dashboard_probe_reports_persistent_public_access_misconfiguration(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("dashboard-probe.html", source)
        self.assertIn("El dashboard respondió 403", source)
        self.assertIn("Acceso por Wi", source)

    def test_cloud_shortcut_includes_sanitized_buyer_email(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("email_label=", source)
        self.assertIn("Admira IA Dashboard - $email_label.webloc", source)
        self.assertIn("s/[^A-Za-z0-9@._+-]/_/g", source)

    def test_direct_cloud_installer_registers_a_protected_clean_reset_agent(self):
        source = ENGINE.read_text(encoding="utf-8")
        gate = GATE.read_text(encoding="utf-8")
        reset = RESET.read_text(encoding="utf-8")
        self.assertIn("CLOUD_INSTALL_ENDPOINT=\"/api/license/release\"", source)
        self.assertIn("action: 'cloud_install'", source)
        self.assertIn("admira-cloud-access-gate.py", source)
        self.assertIn("X-Admira-Cloud-Secret", gate)
        self.assertIn("/admin/reset-status", gate)
        self.assertIn("META_ACCESS_TOKEN", reset)
        self.assertIn("hermes-home", reset)
        self.assertIn("generated_images", reset)

    def test_persisted_dotenv_does_not_override_compose_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("LAN_ACCESS_ENABLED=false\nFROM_FILE=kept\n", encoding="utf-8")
            old_values = {key: os.environ.get(key) for key in ("LAN_ACCESS_ENABLED", "FROM_FILE")}
            try:
                os.environ["LAN_ACCESS_ENABLED"] = "true"
                os.environ.pop("FROM_FILE", None)
                load_dotenv(env_path)
                self.assertEqual(os.environ["LAN_ACCESS_ENABLED"], "true")
                self.assertEqual(os.environ["FROM_FILE"], "kept")
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_persisted_dotenv_recovers_values_from_blank_compose_placeholders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("TELEGRAM_BOT_TOKEN=durable-token\n", encoding="utf-8")
            previous = os.environ.get("TELEGRAM_BOT_TOKEN")
            try:
                # Compose emits empty optional variables even when the durable
                # runtime volume already contains the buyer's connection.
                os.environ["TELEGRAM_BOT_TOKEN"] = ""
                load_dotenv(env_path)
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "durable-token")
            finally:
                if previous is None:
                    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
                else:
                    os.environ["TELEGRAM_BOT_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
