from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from terminalkit.plugins import seed_plugin
from terminalkit.state import Conflict


class PluginSeedTests(unittest.TestCase):
    def test_atomic_seed_reuses_exact_commit_and_preserves_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "upstream"
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "init.lua").write_text("return {}\n")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
            destination = root / "plugins/LazyVim"
            seed_plugin(destination, str(source), commit)
            seed_plugin(destination, str(source), commit)
            self.assertTrue((destination / "init.lua").is_file())
            self.assertEqual(subprocess.check_output(["git", "-C", str(destination), "symbolic-ref", "refs/remotes/origin/HEAD"], text=True).strip(), "refs/remotes/origin/main")
            (destination / "init.lua").write_text("my edits")
            with self.assertRaises(Conflict):
                seed_plugin(destination, str(source), commit)
            self.assertEqual((destination / "init.lua").read_text(), "my edits")

    def test_failed_transfer_does_not_publish_incomplete_plugin(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "plugins/LazyVim"
            with patch("terminalkit.plugins.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 300)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    seed_plugin(destination, "https://github.com/LazyVim/LazyVim.git", "a" * 40)
            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.iterdir()), [])
