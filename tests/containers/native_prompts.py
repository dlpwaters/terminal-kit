"""Exercise package authorization and terminal input only in the test container."""

import fcntl
import json
import os
import pty
import select
import signal
import struct
import sys
import termios
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from terminalkit import tools


@unittest.skipUnless(os.environ.get("TERMINAL_KIT_TEST_CONTAINER") == "1", "Disposable container only")
class NativePromptTests(unittest.TestCase):
    def test_sudo_receives_list_only_mode_despite_callers_automatic_mode(self):
        command = [sys.executable, "-c",
                   "import os; assert os.environ.get('NEEDRESTART_MODE') == 'l'"]
        with patch.dict(os.environ, {"NEEDRESTART_MODE": "a"}):
            result = tools._run_native(command, "apt", True, timeout=5)
        self.assertEqual(result.returncode, 0)

    def test_interactive_checklist_accepts_no_services_through_sudo(self):
        self.assert_checklist_accepts_no_services(
            ["whiptail", "--checklist", "Leave services running", "10", "70", "2",
             "NetworkManager.service", "", "off", "sddm.service", "", "off"],
            b"Leave services running",
        )

    def test_redirected_stdin_uses_the_actual_terminal_device(self):
        self.assert_checklist_accepts_no_services(
            ["whiptail", "--checklist", "Leave services running", "10", "70", "2",
             "NetworkManager.service", "", "off", "sddm.service", "", "off"],
            b"Leave services running", redirected_stdin=True,
        )

    def test_debconf_needrestart_checklist_accepts_no_services_through_sudo(self):
        # Debconf relaunches its client by filename; perl -e cannot be used.
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "needrestart-checklist.pl"
            script.write_text(
                '#!/usr/bin/perl\nuse NeedRestart::UI::Debconf;\n'
                'my $ui = NeedRestart::UI::Debconf->new(1); '
                '$ui->query_pkgs("Leave services running", 1, '
                '{"NetworkManager.service" => 1, "sddm.service" => 1}, {}, '
                'sub { die "Unexpected service restart"; }, 0);\n'
            )
            script.chmod(0o755)
            self.assert_checklist_accepts_no_services(
                [str(script)], b"Which services should be restarted?",
            )

    def assert_checklist_accepts_no_services(self, command, prompt, *, redirected_stdin=False):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 25, 110, 0, 0))
            if redirected_stdin:
                with open(os.devnull, "rb") as null:
                    os.dup2(null.fileno(), 0)
            code = 1
            try:
                result = tools._run_native(command, "apt", False, timeout=5)
                print("\nNATIVE_RESULT=" + json.dumps(result.returncode), flush=True)
                code = result.returncode
            finally:
                os._exit(code)

        output = bytearray()
        sent = False
        status = None
        done = 0
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if prompt in output and not sent:
                    os.write(fd, b"\t\r")
                    sent = True
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                if not done:
                    done, status = os.waitpid(pid, os.WNOHANG)
            if not done:
                done, status = os.waitpid(pid, os.WNOHANG)
                if not done:
                    os.kill(pid, signal.SIGTERM)
                    _, status = os.waitpid(pid, 0)
        finally:
            os.close(fd)
        self.assertTrue(sent, "The checklist never appeared: " + output.decode(errors="replace"))
        self.assertIn(b"NATIVE_RESULT=0", output, output.decode(errors="replace"))
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
