"""Bounded live checks; no provider calls or access to credential contents."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def live_checks(home, receipt, repo):
    from .tools import _CHECKS, _cmd_for, _version, _at_least
    checks = []
    minimums = json.loads((repo / "manifests/tools.json").read_text())["minimum_versions"]
    pm = receipt.get("platform", {}).get("pm")
    for item in receipt.get("results", []):
        name, path = item["name"], item.get("path")
        if item["status"] in ("failed", "unsupported"):
            checks.append({"name": name, "status": item["status"], "required": item.get("required", False), "detail": item["detail"]})
            continue
        if not path or Path(path).is_dir():
            continue
        command, args = _cmd_for(name, pm) if pm else _CHECKS.get(name, (name, ["--version"]))
        if name == "tmux":
            args = ["-V"]
        version, _ = _version(path, args)
        minimum = minimums.get(command)
        valid = bool(version) and _at_least(version, minimum)
        checks.append({"name": name, "status": "available" if valid else "failed", "required": item.get("required", False), "version": version, "path": path, "detail": "Executable version checked" if valid else f"Executable is missing, failed its version check, or is below {minimum or 'the required minimum'}"})
    if set(receipt.get("modules", [])) & {"agents", "pi", "opencode", "runtimes", "nvim"}:
        version, path = _version("npm", ["--version"])
        checks.append({"name": "npm", "status": "available" if version else "failed", "required": True, "version": version, "path": path, "detail": "Runtime launcher checked"})
    if "nvim" in receipt.get("modules", []):
        command = ["nvim", "--headless", '+lua assert(vim.g.mapleader == " "); assert(require("lazy.core.config").plugins.LazyVim); print("TERMINAL_KIT_STARTUP_OK")', "+qa"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=25)
            valid = result.returncode == 0 and "TERMINAL_KIT_STARTUP_OK" in result.stdout + result.stderr and "Error" not in result.stderr
        except (OSError, subprocess.TimeoutExpired):
            valid = False
        checks.append({"name": "nvim-startup", "status": "available" if valid else "failed", "required": True, "detail": "Headless LazyVim startup checked" if valid else "Headless startup failed; run nvim --headless +qa to inspect"})
    if set(receipt.get("modules", [])) & {"configs", "tmux"} and shutil.which("tmux"):
        with tempfile.TemporaryDirectory(prefix="terminal-kit-doctor-") as temporary:
            socket = str(Path(temporary) / "tmux.sock")
            prefix = ["tmux", "-S", socket]
            valid = False
            try:
                subprocess.run([*prefix, "-f", str(home / ".tmux.conf"), "new-session", "-d", "-s", "doctor"], check=True, capture_output=True, timeout=10)
                shell = subprocess.check_output([*prefix, "show-option", "-gqv", "default-shell"], text=True, timeout=5).strip()
                valid = shell == receipt.get("bash")
            except (OSError, subprocess.SubprocessError):
                pass
            finally:
                try:
                    subprocess.run([*prefix, "kill-server"], capture_output=True, timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            checks.append({"name": "tmux-config", "status": "available" if valid else "failed", "required": True, "detail": "Isolated server config and Bash selection checked" if valid else "Isolated server failed or default-shell is incorrect"})
    return checks
