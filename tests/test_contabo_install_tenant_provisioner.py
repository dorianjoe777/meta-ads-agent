from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "contabo" / "install-tenant-provisioner.sh"


class TenantProvisionerInstallerTests(unittest.TestCase):
    def test_socket_runtime_directory_survives_daemon_restart_for_bind_mount(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("RuntimeDirectory=admira-tenant-provisioner", text)
        self.assertIn("RuntimeDirectoryMode=0750", text)
        self.assertIn("RuntimeDirectoryPreserve=yes", text)


if __name__ == "__main__":
    unittest.main()
