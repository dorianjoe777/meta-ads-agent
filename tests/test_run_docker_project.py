from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_DOCKER = ROOT / "scripts" / "run-docker.sh"


class RunDockerProjectSelectionTests(unittest.TestCase):
    """Exercise project selection without contacting Docker or the network."""

    def run_case(self, dotenv_value: str | None, explicit: str | None) -> str:
        with tempfile.TemporaryDirectory(prefix="admira-run-docker-") as raw:
            root = Path(raw)
            (root / "scripts").mkdir()
            shutil.copy2(RUN_DOCKER, root / "scripts" / "run-docker.sh")
            shutil.copy2(ROOT / "scripts" / "source_manifest.py", root / "scripts" / "source_manifest.py")
            (root / "VERSION").write_text("r-test\n", encoding="utf-8")
            (root / ".env.example").write_text("META_ADS_AGENT_VERSION=r-test\n", encoding="utf-8")
            if dotenv_value is not None:
                (root / ".env").write_text(
                    f"LICENSE_KEY=not-a-real-secret\nADMIRA_COMPOSE_PROJECT_NAME={dotenv_value}\n",
                    encoding="utf-8",
                )

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            (fake_bin / "git").write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"-C\" ]; then shift 2; fi\n"
                "case \"$1 $2\" in\n"
                "  'rev-parse --is-inside-work-tree') echo true ;;\n"
                "  'rev-parse HEAD') echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeef ;;\n"
                "  'ls-files -z') printf 'VERSION\\0.env.example\\0scripts/run-docker.sh\\0scripts/source_manifest.py\\0' ;;\n"
                "  *) exit 1 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            (fake_bin / "docker").write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = compose ] && [ \"$2\" = version ]; then exit 0; fi\n"
                "printf '%s\\n' \"$*\" > \"$ADMIRA_DOCKER_TEST_LOG\"\n",
                encoding="utf-8",
            )
            for command in (fake_bin / "git", fake_bin / "docker"):
                command.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["ADMIRA_HOST_LAN_IP"] = "127.0.0.1"
            env["ADMIRA_DOCKER_SKIP_BUILD"] = "true"
            env["ADMIRA_DOCKER_TEST_LOG"] = str(root / "docker.log")
            if explicit is None:
                env.pop("ADMIRA_COMPOSE_PROJECT_NAME", None)
            else:
                env["ADMIRA_COMPOSE_PROJECT_NAME"] = explicit
            result = subprocess.run(
                ["bash", str(root / "scripts" / "run-docker.sh")],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            return (root / "docker.log").read_text(encoding="utf-8")

    def test_explicit_environment_wins_over_dotenv(self):
        command = self.run_case("from-dotenv", "from-environment")
        self.assertIn("-p from-environment up", command)

    def test_dotenv_value_wins_over_default(self):
        command = self.run_case("from-dotenv", None)
        self.assertIn("-p from-dotenv up", command)

    def test_default_is_used_without_environment_or_dotenv_value(self):
        command = self.run_case(None, None)
        self.assertIn("-p admira-ia up", command)


if __name__ == "__main__":
    unittest.main()
