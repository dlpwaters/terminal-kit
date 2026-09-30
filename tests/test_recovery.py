import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from terminalkit.state import State, write_json
from terminalkit.hooks import strip_hook


class RestorationTests(unittest.TestCase):
    def test_rollback_interruption_restores_remaining_files_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "a").write_text("old a")
            (home / "b").write_text("old b")
            state = State(home)
            write_json(state.root / "installation.json", {"theme": "old"})
            identity = state.begin("install")
            state.apply("a", b"new a")
            state.apply("b", b"new b")
            write_json(state.root / "installation.json", {"theme": "new"})
            state.finish()
            with patch.object(state, "save", side_effect=OSError("power loss after atomic restore")):
                with self.assertRaises(OSError):
                    state.rollback(identity)
            recovered = State(home)
            recovered.recover()
            self.assertEqual((home / "a").read_text(), "old a")
            self.assertEqual((home / "b").read_text(), "old b")
            self.assertEqual(json.loads((state.root / "installation.json").read_text())["theme"], "old")
            self.assertFalse(recovered.data["files"])

    def test_uninstall_interruption_resumes_and_marks_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = State(home)
            state.begin("install")
            state.apply("a", b"new a")
            state.apply("b", b"new b")
            write_json(state.root / "installation.json", {"theme": "kit"})
            state.finish()
            with patch.object(state, "save", side_effect=OSError("interrupted uninstall")):
                with self.assertRaises(OSError):
                    state.uninstall(strip_hook)
            recovered = State(home)
            recovered.recover()
            self.assertFalse((home / "a").exists())
            self.assertFalse((home / "b").exists())
            self.assertEqual(json.loads((state.root / "installation.json").read_text())["status"], "uninstalled")
            self.assertFalse(recovered.data["files"])


if __name__ == "__main__":
    unittest.main()
