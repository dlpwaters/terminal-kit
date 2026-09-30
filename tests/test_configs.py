import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from terminalkit import configs, layouts


REPO = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_build_configs_returns_portable_home_relative_files(self):
        with tempfile.TemporaryDirectory(prefix="terminal kit ") as home:
            files = configs.build_configs(REPO, Path(home), "/usr/bin/bash", {"os": "linux"})
        by_path = {path: (content, mode) for path, content, mode in files}
        self.assertEqual(by_path[".config/terminal-kit/ghostty.conf"][1], 0o644)
        self.assertIn(b'command = "/usr/bin/bash --login --interactive"', by_path[".config/terminal-kit/ghostty.conf"][0])
        self.assertLess(by_path[".config/terminal-kit/ghostty.conf"][0].index(b"background ="), by_path[".config/terminal-kit/ghostty.conf"][0].index(b"config-file = ?~/.config/terminal-kit/local/ghostty.conf"))
        self.assertIn(b"set -g default-shell /usr/bin/bash", by_path[".config/terminal-kit/tmux.conf"][0])
        self.assertIn(".config/terminal-kit/nvim/lazy-lock.json", by_path)
        self.assertTrue(all(not Path(path).is_absolute() and ".." not in Path(path).parts for path in by_path))
        self.assertTrue(all(b"/usr/share/omarchy" not in content for content, _ in by_path.values()))
        self.assertTrue(all(mode == 0o644 for _, mode in by_path.values()))

    def test_ghostty_quotes_bash_paths_with_spaces_and_palette_is_dynamic(self):
        files = dict((target, content) for target, content, _ in configs.build_configs(
            REPO, Path("/tmp"), "/opt/Portable Bash/bin/bash", {}, "catppuccin"
        ))
        ghostty = files[".config/terminal-kit/ghostty.conf"]
        self.assertIn(b"command = \"'/opt/Portable Bash/bin/bash' --login --interactive\"", ghostty)
        self.assertIn(b"palette = 1=#f38ba8", ghostty)
        self.assertNotIn(b"palette = 1=#f7768e", ghostty)

    def test_user_terminfo_describes_both_terminal_layers(self):
        with tempfile.TemporaryDirectory(prefix="terminal kit ") as temporary:
            home = Path(temporary)
            for relative, content, _ in configs.build_configs(REPO, home, "/bin/bash", {}):
                if relative.startswith(".terminfo/"):
                    path = home / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            for terminal in ("tmux-256color", "xterm-ghostty"):
                result = subprocess.run(
                    ["infocmp", "-A", str(home / ".terminfo"), terminal],
                    capture_output=True, text=True, check=True,
                )
                self.assertIn(terminal, result.stdout)
                self.assertIn("colors#", result.stdout)

    def test_installed_ghostty_validates_generated_config_without_user_home(self):
        ghostty = shutil.which("ghostty")
        if not ghostty:
            self.skipTest("Ghostty is not installed")
        files = dict((target, content) for target, content, _ in configs.build_configs(REPO, Path("/tmp"), "/usr/bin/bash", {"os": "linux"}))
        result = configs.validate_ghostty_config(files[".config/terminal-kit/ghostty.conf"], ghostty)
        self.assertEqual(result["status"], "valid", result)

    def test_wslg_launch_probe_reports_unsupported_without_wslg(self):
        result = configs.validate_wslg_ghostty_launch(
            Path("/not/a/config"), {"os": "linux", "wsl": 0, "display": True}, "/usr/bin/ghostty"
        )
        self.assertEqual(result["status"], "unsupported")

    def test_palette_generation_and_unknown_theme(self):
        tokyo = dict((target, data) for target, data, _ in configs.build_configs(REPO, Path("/tmp"), "/bin/bash", {}, "tokyo-night"))
        rose = dict((target, data) for target, data, _ in configs.build_configs(REPO, Path("/tmp"), "/bin/bash", {}, "rose-pine"))
        self.assertNotEqual(tokyo[".config/terminal-kit/ghostty.conf"], rose[".config/terminal-kit/ghostty.conf"])
        self.assertIn(b'colorscheme = "aether"', tokyo[".config/terminal-kit/nvim/lua/plugins/theme.lua"])
        self.assertIn(b"#1a1b26", tokyo[".config/terminal-kit/nvim/lua/plugins/theme.lua"])
        with self.assertRaisesRegex(ValueError, "Unknown theme"):
            configs.build_configs(REPO, Path("/tmp"), "/bin/bash", {}, "does-not-exist")

    def test_bash_syntax_and_noninteractive_startup_are_quiet(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is not available")
        with tempfile.TemporaryDirectory(prefix="terminal kit ") as home:
            home = Path(home)
            for relative, content, _ in configs.build_configs(REPO, home, bash, {"os": "linux"}):
                path = home / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            rc = home / ".config/terminal-kit/bash/rc"
            subprocess.run([bash, "-n", str(rc)], check=True)
            result = subprocess.run(
                [bash, "--noprofile", "--norc", "-c", f"source {shlex.quote(str(rc))}; printf ready"],
                env={**os.environ, "HOME": str(home)}, text=True, capture_output=True, check=True,
            )
            self.assertEqual(result.stdout, "ready")
            self.assertEqual(result.stderr, "")
            env_result = subprocess.run(
                [bash, "--noprofile", "--norc", "-c", f"source {shlex.quote(str(home / '.config/terminal-kit/bash/env'))}; printf '%s' \"$PATH\""],
                env={**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"},
                text=True, capture_output=True, check=True,
            )
            self.assertEqual(env_result.stdout.split(":")[:2], [
                str(home / ".local/share/terminal-kit/bin"), str(home / ".local/bin")
            ])

    def test_layout_rejects_shell_injection_and_builds_safe_commands(self):
        with self.assertRaisesRegex(layouts.LayoutError, "Unsupported agent"):
            layouts._validate_agents(["pi; touch /tmp/nope"])
        with self.assertRaisesRegex(layouts.LayoutError, "Session names"):
            layouts._validate_name("../unsafe")
        commands = []
        pane_number = 1

        def fake_run(command, **kwargs):
            nonlocal pane_number
            commands.append(command[command.index("-L") + 2 :])
            stdout = ""
            if "-P" in command:
                pane_number += 1
                stdout = f"%{pane_number}\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory(prefix="project with spaces ") as cwd:
            old_cwd = Path.cwd
            try:
                Path.cwd = lambda: Path(cwd)
                old_run = layouts.subprocess.run
                layouts.subprocess.run = fake_run
                old_socket = os.environ.get("TERMINAL_KIT_TMUX_SOCKET")
                old_pane = os.environ.get("TMUX_PANE")
                old_tmux = os.environ.get("TMUX")
                os.environ["TERMINAL_KIT_TMUX_SOCKET"] = "terminal-kit-test-only"
                os.environ["TMUX_PANE"] = "%1"
                os.environ["TMUX"] = "isolated"
                layouts._run_agent_layout("tdl", ["pi", "hermes"])
                self.assertIn(["send-keys", "-t", "%2", "-l", "pi"], commands)
                self.assertIn(["send-keys", "-t", "%3", "-l", "hermes"], commands)
                self.assertEqual(commands[-1], ["select-pane", "-t", "%1"])
            finally:
                layouts.subprocess.run = old_run
                Path.cwd = old_cwd
                for key, value in (("TERMINAL_KIT_TMUX_SOCKET", old_socket), ("TMUX_PANE", old_pane), ("TMUX", old_tmux)):
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_layout_works_against_isolated_tmux_server_when_sandbox_allows_sockets(self):
        tmux = shutil.which("tmux")
        if not tmux:
            self.skipTest("tmux is not available")
        with tempfile.TemporaryDirectory(prefix="terminal kit ") as tmp:
            root = Path(tmp)
            socket = "tk-test-" + uuid.uuid4().hex[:10]
            started = subprocess.run(
                [tmux, "-L", socket, "new-session", "-d", "-s", "test", "-c", str(root), "-x", "140", "-y", "45"],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if started.returncode and b"Operation not permitted" in started.stderr:
                self.skipTest("sandbox blocks tmux isolated Unix sockets")
            self.assertEqual(started.returncode, 0, started.stderr.decode(errors="replace"))
            try:
                pane = subprocess.run(
                    [tmux, "-L", socket, "display-message", "-p", "-t", "test", "#{pane_id}"],
                    check=True, text=True, capture_output=True,
                ).stdout.strip()
                env = {**os.environ, "TMUX": "isolated", "TMUX_PANE": pane, "TERMINAL_KIT_TMUX_SOCKET": socket}
                subprocess.run([tmux, "-L", socket, "set-option", "-g", "remain-on-exit", "on"], check=True)
                result = subprocess.run(
                    [sys.executable, "-c", "from terminalkit.layouts import _run_agent_layout; _run_agent_layout('tdl',['pi','hermes'])"],
                    cwd=REPO, env={**env, "PYTHONPATH": str(REPO / "lib")}, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                panes = subprocess.run(
                    [tmux, "-L", socket, "list-panes", "-t", "test", "-F", "#{pane_id}"],
                    check=True, text=True, capture_output=True,
                ).stdout.splitlines()
                self.assertEqual(len(panes), 4)
            finally:
                subprocess.run([tmux, "-L", socket, "kill-server"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
