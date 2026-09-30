import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from terminalkit.hooks import merge_hook, strip_hook
from terminalkit.state import Conflict, State, fingerprint, lock


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="terminal kit home ")
        self.home = Path(self.tmp.name)
        self.state = State(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def begin(self):
        return self.state.begin("install")

    def test_fresh_repeat_and_uninstall(self):
        self.begin()
        self.state.apply(".config/tool", b"ours")
        self.state.finish()
        self.begin()
        self.assertFalse(self.state.apply(".config/tool", b"ours"))
        self.state.finish()
        self.state.uninstall(strip_hook)
        self.assertFalse((self.home / ".config/tool").exists())

    def test_existing_file_rollback(self):
        path = self.home / ".bashrc"
        path.write_text("custom\n")
        identity = self.begin()
        self.state.apply(".bashrc", b"managed\n")
        self.state.finish()
        self.state.rollback(identity)
        self.assertEqual(path.read_text(), "custom\n")

    def test_original_symlink_restored(self):
        original = self.home / "original bash"
        original.write_text("original")
        (self.home / ".bashrc").symlink_to(original)
        self.begin()
        self.state.apply(".bashrc", b"managed")
        self.state.finish()
        self.state.uninstall(strip_hook)
        self.assertEqual(os.readlink(self.home / ".bashrc"), str(original))
        self.assertEqual(original.read_text(), "original")

    def test_dirty_file_prevents_update_and_rollback(self):
        identity = self.begin()
        self.state.apply("config", b"kit")
        self.state.finish()
        (self.home / "config").write_text("user edit")
        self.begin()
        with self.assertRaises(Conflict):
            self.state.apply("config", b"update")
        with self.assertRaises(Conflict):
            self.state.rollback(identity)
        with self.assertRaises(Conflict):
            self.state.uninstall(strip_hook)
        self.assertEqual((self.home / "config").read_text(), "user edit")

    def test_outside_hook_edits_survive_uninstall(self):
        path = self.home / ".bashrc"
        path.write_text("before\n")
        self.begin()
        self.state.apply(".bashrc", merge_hook(path.read_text(), "source kit").encode(), hook=True)
        self.state.finish()
        path.write_text(path.read_text() + "after\n")
        self.state.uninstall(strip_hook)
        self.assertEqual(path.read_text(), "before\nafter\n")

    def test_hook_edits_refused(self):
        self.begin()
        text = merge_hook("", "source kit")
        self.state.apply(".bashrc", text.encode(), hook=True)
        self.state.finish()
        (self.home / ".bashrc").write_text(text.replace("source kit", "my stuff"))
        self.begin()
        with self.assertRaises(Conflict):
            self.state.apply(".bashrc", text.encode(), hook=True)
        with self.assertRaises(Conflict):
            self.state.uninstall(strip_hook)

    def test_parent_symlink_collision(self):
        target = self.home / "elsewhere"
        target.mkdir()
        (self.home / ".config").symlink_to(target)
        self.begin()
        with self.assertRaises(Conflict):
            self.state.apply(".config/foo", b"data")
        self.assertFalse((target / "foo").exists())

    def test_interruption_after_write_recovers_and_resumes(self):
        self.begin()
        with mock.patch.object(self.state, "save", side_effect=OSError("interruption")):
            with self.assertRaises(OSError):
                self.state.apply("config", b"kit")
        resumed = State(self.home)
        resumed.recover()
        self.assertEqual(resumed.data["files"]["config"]["installed"], fingerprint(self.home / "config"))
        resumed.begin("resume")
        self.assertFalse(resumed.apply("config", b"kit"))
        resumed.finish()
        resumed.uninstall(strip_hook)
        self.assertFalse((self.home / "config").exists())

    def test_lock_excludes_parallel_installer(self):
        with lock(self.state.root):
            with self.assertRaises(Conflict):
                with lock(self.state.root):
                    pass

    def test_path_traversal_refused(self):
        self.begin()
        for path in ("../outside", "/tmp/outside"):
            with self.assertRaises(Conflict):
                self.state.apply(path, b"no")


if __name__ == "__main__":
    unittest.main()
