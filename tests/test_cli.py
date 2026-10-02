from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from terminalkit import cli
from terminalkit.state import State

FACTS = {"os": "linux", "distro": "debian", "version": "12", "arch": "x86_64", "pm": "apt", "supported": True, "display": False, "ssh": False, "wsl": 0}


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="terminal kit ")
        self.home = Path(self.tmp.name) / "home with spaces"
        self.home.mkdir()
        self.env = patch.dict(os.environ, {"HOME": str(self.home)}, clear=False)
        self.env.start()
        self.platform = patch.object(cli, "detect", return_value=FACTS.copy())
        self.platform.start()
        self.user = patch("os.geteuid", return_value=1000)
        self.user.start()
        self.tools = patch("terminalkit.tools.install_tools", return_value=[])
        self.tools_mock = self.tools.start()

    def tearDown(self):
        self.tools.stop()
        self.user.stop()
        self.platform.stop()
        self.env.stop()
        self.tmp.cleanup()

    def run_cli(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return cli.main(list(args))

    def test_fresh_repeat_uninstall_preserves_existing_configs_and_overrides(self):
        bashrc = self.home / ".bashrc"
        bashrc.write_text("export MY_OLD_SETTING=1\n")
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        override = self.home / ".config/terminal-kit/local/bash.sh"
        override.write_text("export MY_LOCAL=1\n")
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        self.assertEqual(bashrc.read_text().count("# >>> terminal-kit"), 1)
        self.assertEqual(override.read_text(), "export MY_LOCAL=1\n")
        self.assertEqual(self.run_cli("uninstall"), 0)
        self.assertEqual(bashrc.read_text(), "export MY_OLD_SETTING=1\n")
        self.assertEqual(override.read_text(), "export MY_LOCAL=1\n")

    def test_selected_bash_keeps_stable_homebrew_link_across_upgrades(self):
        prefix = self.home / "homebrew"
        binary = prefix / "Cellar/bash/5.3/bin/bash"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        stable = prefix / "bin/bash"
        stable.parent.mkdir()
        stable.symlink_to(binary)
        with patch.object(cli.shutil, "which", return_value=str(stable)):
            self.assertEqual(cli.select_bash(), str(stable.absolute()))
            upgraded = prefix / "Cellar/bash/5.4/bin/bash"
            upgraded.parent.mkdir(parents=True)
            upgraded.write_bytes(binary.read_bytes())
            upgraded.chmod(0o755)
            stable.unlink()
            stable.symlink_to(upgraded)
            self.assertEqual(cli.select_bash(), str(stable.absolute()))

    def test_dry_run_does_not_create_state_or_hooks(self):
        self.assertEqual(self.run_cli("install", "--dry-run"), 0)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_partial_failure_keeps_management_available(self):
        self.tools_mock.return_value = [{"name": "pi", "status": "failed", "required": True, "detail": "download failure"}]
        self.assertEqual(self.run_cli("install", "--modules", "configs,agents"), 1)
        self.assertTrue((self.home / ".local/bin/terminal-kit").is_file())
        self.assertEqual(self.run_cli("doctor"), 1)
        self.assertEqual(self.run_cli("doctor", "--json"), 1)

    def test_doctor_detects_missing_hook_but_allows_outside_edits(self):
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        path = self.home / ".bashrc"
        original = path.read_text()
        with patch("terminalkit.checks.live_checks", return_value=[]):
            path.write_text("export CUSTOM=1\n" + original)
            self.assertEqual(self.run_cli("doctor"), 0)
            path.write_text("export CUSTOM=1\n")
            self.assertEqual(self.run_cli("doctor"), 1)

    def test_pi_preferences_are_user_owned_and_survive_repeat_rollback_uninstall(self):
        self.assertEqual(self.run_cli("install", "--modules", "pi"), 0)
        receipt = cli.read_install(self.home)
        path = self.home / ".pi/agent/settings.json"
        self.assertEqual(json.loads(path.read_text())["shellPath"], receipt["bash"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        preferences = json.dumps({"shellPath": receipt["bash"], "theme": "dark", "lastChangelogVersion": "1.0.0"})
        path.write_text(preferences)
        with patch("terminalkit.checks.live_checks", return_value=[]):
            self.assertEqual(self.run_cli("doctor"), 0)
        self.assertEqual(self.run_cli("install", "--modules", "pi"), 0)
        receipt = cli.read_install(self.home)
        self.assertEqual(self.run_cli("rollback", receipt["backup"]), 0)
        self.assertEqual(self.run_cli("uninstall"), 0)
        self.assertEqual(path.read_text(), preferences)

    def legacy_pi_preferences(self):
        self.assertEqual(self.run_cli("install", "--modules", "pi"), 0)
        path = self.home / ".pi/agent/settings.json"
        path.unlink()
        state = State(self.home)
        state.data["files"].pop(".pi/agent/settings.json", None)
        state.begin("install")
        state.apply(".pi/agent/settings.json", b'{"shellPath":"/bin/bash"}\n', 0o600)
        state.finish()
        preferences = '{"shellPath":"/bin/bash","theme":"dark"}\n'
        path.write_text(preferences)
        return path, preferences

    def test_legacy_pi_preferences_are_preserved_by_doctor_repeat_and_uninstall(self):
        path, preferences = self.legacy_pi_preferences()
        with patch("terminalkit.checks.live_checks", return_value=[]):
            self.assertEqual(self.run_cli("doctor"), 0)
        self.assertEqual(self.run_cli("install", "--modules", "pi"), 0)
        self.assertNotIn(".pi/agent/settings.json", State(self.home).data["files"])
        self.assertEqual(self.run_cli("uninstall"), 0)
        self.assertEqual(path.read_text(), preferences)

    def test_uninstall_preserves_edited_legacy_pi_preferences_without_reinstall(self):
        path, preferences = self.legacy_pi_preferences()
        self.assertEqual(self.run_cli("uninstall"), 0)
        self.assertEqual(path.read_text(), preferences)

    def test_doctor_still_rejects_invalid_pi_json_without_replacing_it(self):
        self.assertEqual(self.run_cli("install", "--modules", "pi"), 0)
        path = self.home / ".pi/agent/settings.json"
        path.write_text("invalid json\n")
        with patch("terminalkit.checks.live_checks", return_value=[]):
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["doctor"]), 1)
            self.assertIn("JSON syntax", output.getvalue())
            self.assertNotIn("invalid json", output.getvalue())
        self.assertEqual(path.read_text(), "invalid json\n")

    def test_minimal_preserves_existing_neovim_entry(self):
        path = self.home / ".config/nvim/init.lua"
        path.parent.mkdir(parents=True)
        path.write_text("-- My own editor\n")
        self.assertEqual(self.run_cli("install", "--profile", "minimal"), 0)
        self.assertEqual(path.read_text(), "-- My own editor\n")

    def test_repeat_retains_selected_theme(self):
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        self.assertEqual(self.run_cli("theme", "rose-pine"), 0)
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        self.assertEqual(cli.read_install(self.home)["theme"], "rose-pine")

    def test_unknown_module_fails_without_writes(self):
        self.assertEqual(self.run_cli("install", "--modules", "made-up"), 2)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_noninteractive_startup_is_quiet(self):
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        result = subprocess.run(["bash", "--noprofile", "--norc", "-c", '. "$HOME/.bashrc"; printf ready'], env=os.environ, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "ready")
        self.assertEqual(result.stderr, "")

    def test_login_precedence_existing_bash_login(self):
        (self.home / ".bash_login").write_text("export PRESERVED=1\n")
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        self.assertFalse((self.home / ".bash_profile").exists())
        self.assertIn("terminal-kit", (self.home / ".bash_login").read_text())

    def test_rollback_install_restores_custom_dotfile(self):
        (self.home / ".tmux.conf").write_text("set -g mouse off\n")
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        receipt = cli.read_install(self.home)
        self.assertEqual(self.run_cli("rollback", receipt["backup"]), 0)
        self.assertEqual((self.home / ".tmux.conf").read_text(), "set -g mouse off\n")

    def test_dirty_managed_file_fails_preserving_edit(self):
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 0)
        path = self.home / ".config/terminal-kit/bash/aliases"
        path.write_text("local edit\n")
        self.assertEqual(self.run_cli("install", "--modules", "configs"), 1)
        self.assertEqual(path.read_text(), "local edit\n")
        with patch("terminalkit.checks.live_checks", return_value=[]):
            self.assertEqual(self.run_cli("doctor"), 1)


if __name__ == "__main__":
    unittest.main()
