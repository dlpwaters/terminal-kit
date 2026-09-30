from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from terminalkit.state import Conflict, fingerprint, write_json
from terminalkit.windows import remove_fragment


class WindowsFragmentRemovalTests(unittest.TestCase):
    def _owned_fragment(self, home):
        target = home / "mnt/c/Users/example/AppData/Local/Microsoft/Windows Terminal/Fragments/terminal-kit/terminal-kit.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"profiles": []}\n', encoding="utf-8")
        receipt = home / ".local/state/terminal-kit/windows-host.json"
        write_json(receipt, {"path": str(target), "installed": fingerprint(target), "distro": "Test"})
        return target, receipt

    def test_removes_only_receipted_owned_fragment(self):
        with tempfile.TemporaryDirectory(prefix="kit-remove-") as tmp:
            home = Path(tmp).resolve()
            target, receipt = self._owned_fragment(home)
            result = remove_fragment(home)
            self.assertEqual(result["status"], "removed")
            self.assertFalse(target.exists())
            self.assertFalse(receipt.exists())

    def test_edited_fragment_and_receipt_are_preserved(self):
        with tempfile.TemporaryDirectory(prefix="kit-remove-") as tmp:
            home = Path(tmp).resolve()
            target, receipt = self._owned_fragment(home)
            target.write_text('{"profiles": ["user edit"]}\n', encoding="utf-8")
            with self.assertRaisesRegex(Conflict, "edited"):
                remove_fragment(home)
            self.assertTrue(target.exists())
            self.assertTrue(receipt.exists())

    def test_receipt_path_outside_owned_fragment_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="kit-remove-") as tmp:
            home = Path(tmp).resolve()
            receipt = home / ".local/state/terminal-kit/windows-host.json"
            target = home / "important.json"
            target.write_text("safe\n", encoding="utf-8")
            write_json(receipt, {"path": str(target), "installed": fingerprint(target)})
            with self.assertRaisesRegex(Conflict, "outside"):
                remove_fragment(home)
            self.assertTrue(target.exists())

    def test_absent_receipt_is_a_noop(self):
        with tempfile.TemporaryDirectory(prefix="kit-remove-") as tmp:
            self.assertEqual(remove_fragment(Path(tmp))["status"], "absent")

    def test_redirected_localappdata_and_read_only_preflight(self):
        with tempfile.TemporaryDirectory(prefix="kit-remove-") as tmp:
            home = Path(tmp).resolve()
            root = home / "redirected Windows data"
            target = root / "Microsoft/Windows Terminal/Fragments/terminal-kit/terminal-kit.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}\n")
            write_json(home / ".local/state/terminal-kit/windows-host.json", {"path": str(target), "root": str(root), "installed": fingerprint(target)})
            self.assertEqual(remove_fragment(home, dry_run=True)["status"], "ready")
            self.assertTrue(target.exists())
            self.assertEqual(remove_fragment(home)["status"], "removed")


if __name__ == "__main__":
    unittest.main()
