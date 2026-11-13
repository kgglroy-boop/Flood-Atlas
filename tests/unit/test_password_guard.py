"""Exercise the real POSIX startup guard before any image initializer can run."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/require-password.sh"
WINDOWS_BASH = Path("C:/Program Files/Git/bin/bash.exe")
SHELL = str(WINDOWS_BASH) if WINDOWS_BASH.exists() else shutil.which("sh")


class PasswordGuardTests(unittest.TestCase):
    def run_guard(self, name, value):
        self.assertTrue(GUARD.is_file(), "startup credential guard is missing")
        self.assertIsNotNone(SHELL, "POSIX shell is required for this startup test")
        environment = os.environ.copy()
        environment.pop(name, None)
        if value is not None:
            environment[name] = value
        return subprocess.run(
            [SHELL, str(GUARD), name, "/bin/sh", "-c",
             'printf "DELEGATED:%s" "$1"', "--", "argument with spaces"],
            env=environment, capture_output=True, text=True, timeout=10,
        )

    def test_unset_empty_and_whitespace_passwords_never_delegate(self):
        for name in ("POSTGRES_PASSWORD", "GEOSERVER_ADMIN_PASSWORD"):
            for value in (None, "", "   ", "\t\n"):
                with self.subTest(name=name, value=value):
                    result = self.run_guard(name, value)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("DELEGATED", result.stdout)

    def test_placeholder_passwords_never_delegate(self):
        for name in ("POSTGRES_PASSWORD", "GEOSERVER_ADMIN_PASSWORD"):
            with self.subTest(name=name):
                result = self.run_guard(name, "CHANGE_ME")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("DELEGATED", result.stdout)

    def test_valid_password_preserves_arguments_without_logging_password(self):
        secret = "test-only $ # & ' password"
        for name in ("POSTGRES_PASSWORD", "GEOSERVER_ADMIN_PASSWORD"):
            with self.subTest(name=name):
                result = self.run_guard(name, secret)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "DELEGATED:argument with spaces")
                self.assertNotIn(secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
