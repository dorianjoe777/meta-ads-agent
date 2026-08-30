from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "contabo" / "install-runtime-broker.sh"


class RuntimeBrokerInstallerTests(unittest.TestCase):
    def test_installs_private_docker_cli_config_for_broker_user(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("DOCKER_CONFIG_DIR=/run/admira-runtime-broker/docker-config", text)
        self.assertIn('install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DOCKER_CONFIG_DIR"', text)
        self.assertIn('printf \'%s\\n\' \'{}\' | install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" /dev/stdin "$DOCKER_CONFIG_DIR/config.json"', text)
        self.assertIn("Environment=DOCKER_CONFIG=$DOCKER_CONFIG_DIR", text)

    def test_systemd_unit_retains_home_protection_and_no_secret_output(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("ProtectHome=true", text)
        self.assertNotIn("cat \"$BROKER_KEY_SOURCE\"", text)
        self.assertNotIn("docker login", text)

    def test_systemd_unit_propagates_bounded_adaptive_capacity(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("ADMIRA_NORMAL_ACTIVE_TENANTS", text)
        self.assertIn("ADMIRA_HARD_MAX_ACTIVE_TENANTS", text)
        self.assertIn("ADMIRA_BURST_MIN_AVAILABLE_MB", text)
        self.assertIn("HARD_MAX_ACTIVE_TENANTS > 8", text)

    def test_optional_central_image_reference_is_strictly_pinned(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("CENTRAL_IMAGE_IMAGE", text)
        self.assertIn("admira-ia-hosted:r91-canary-[0-9a-f]{12}", text)
        self.assertNotIn("docker pull", text)
        self.assertNotIn("docker build", text)


if __name__ == "__main__":
    unittest.main()
