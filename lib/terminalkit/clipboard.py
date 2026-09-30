"""Clipboard access with bounded headless behavior."""
import base64
import os
import shutil
import subprocess
import sys


def backend(env=None):
    env = os.environ if env is None else env
    if env.get("SSH_CONNECTION") or env.get("SSH_TTY"):
        return "osc52"
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        return "macos"
    if env.get("WAYLAND_DISPLAY") and shutil.which("wl-copy") and shutil.which("wl-paste"):
        return "wayland"
    if env.get("DISPLAY") and shutil.which("xclip"):
        return "x11"
    if env.get("WSL_INTEROP") and shutil.which("clip.exe") and shutil.which("powershell.exe"):
        return "windows"
    return "osc52"


def main(action):
    kind = backend()
    commands = {"macos": (["pbcopy"], ["pbpaste"]), "wayland": (["wl-copy"], ["wl-paste", "--no-newline"]), "x11": (["xclip", "-selection", "clipboard"], ["xclip", "-selection", "clipboard", "-o"]), "windows": (["clip.exe"], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"])}
    if kind == "osc52":
        if action == "paste":
            print("Clipboard paste is unavailable here; paste through your terminal client.", file=sys.stderr)
            return 2
        data = sys.stdin.buffer.read(100001)
        if len(data) > 100000:
            print("OSC 52 copy is limited to 100 KB", file=sys.stderr)
            return 2
        sequence = b"\033]52;c;" + base64.b64encode(data) + b"\a"
        if os.environ.get("TMUX"):
            try:
                # Let tmux address its attached client using that client's
                # advertised clipboard capability; no global passthrough.
                result = subprocess.run(["tmux", "load-buffer", "-w", "-"], input=data, capture_output=True, timeout=3)
                return result.returncode
            except (OSError, subprocess.TimeoutExpired):
                print("tmux clipboard unavailable or timed out", file=sys.stderr)
                return 2
        try:
            with open("/dev/tty", "wb", buffering=0) as tty:
                tty.write(sequence)
        except OSError:
            print("OSC 52 copy requires a controlling terminal", file=sys.stderr)
            return 2
        return 0
    command = commands[kind][0 if action == "copy" else 1]
    data = None if action == "paste" else sys.stdin.buffer.read()
    if kind == "windows" and data is not None:
        data = data.decode("utf-8").encode("utf-16le")
    try:
        result = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3)
        if action == "paste":
            sys.stdout.buffer.write(result.stdout)
        return result.returncode
    except (OSError, subprocess.TimeoutExpired):
        print("Clipboard backend unavailable or timed out", file=sys.stderr)
        return 2
