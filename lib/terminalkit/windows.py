"""Explicit Windows-host integration using a Terminal settings fragment."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from .platforms import detect
from .state import Conflict, atomic_write, fingerprint, write_json


def terminal_fragment(distro, bash):
    # list2cmdline implements Windows command-line quoting; never invoke a shell.
    command = subprocess.list2cmdline(["wsl.exe", "--distribution", distro, "--cd", "~", "--exec", bash, "-l", "-i"])
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, "terminal-kit/wsl/" + distro))
    return {"profiles": [{"guid": "{" + identity + "}", "name": "terminal-kit (" + distro + ")", "commandline": command, "font": {"face": "JetBrainsMono Nerd Font"}, "colorScheme": "terminal-kit Tokyo Night"}], "schemes": [{"name": "terminal-kit Tokyo Night", "background": "#1A1B26", "foreground": "#A9B1D6", "cursorColor": "#C0CAF5", "black": "#32344A", "red": "#F7768E", "green": "#9ECE6A", "yellow": "#E0AF68", "blue": "#7AA2F7", "purple": "#AD8EE6", "cyan": "#449DAB", "white": "#787C99", "brightBlack": "#444B6A", "brightRed": "#FF7A93", "brightGreen": "#B9F27C", "brightYellow": "#FF9E64", "brightBlue": "#7DA6FF", "brightPurple": "#BB9AF7", "brightCyan": "#0DB9D7", "brightWhite": "#ACB0D0"}]}


def configure(args):
    facts = detect()
    if facts["wsl"] != 2 or not facts["windows_interop"] or not shutil.which("powershell.exe"):
        raise Conflict("Windows host integration requires WSL2 with enabled Windows interop and PowerShell")
    from .cli import select_bash
    distro = os.environ.get("WSL_DISTRO_NAME")
    if not distro:
        raise Conflict("WSL_DISTRO_NAME is unavailable; select the intended distribution explicitly")
    if args.settings:
        raise Conflict("Direct settings.json modification is intentionally unsupported. This module installs a separate fragment preserving existing settings and profiles.")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", '[Environment]::GetFolderPath("LocalApplicationData")'], capture_output=True, text=True, timeout=10, check=True)
    windows_root = result.stdout.strip()
    mount = subprocess.run(["wslpath", "-u", windows_root], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    target = Path(mount) / "Microsoft/Windows Terminal/Fragments/terminal-kit/terminal-kit.json"
    content = (json.dumps(terminal_fragment(distro, select_bash()), indent=2) + "\n").encode()
    print(f"Windows Terminal fragment: {target}\nDistribution: {distro}. Existing defaults/profiles remain in place.")
    print("Windows Terminal and font rendering require a host-side launch check; WSLg is a separate optional Ghostty path.")
    if not args.apply:
        print("Apply with terminal-kit windows-host --apply. Install the Nerd Font on Windows using windows/Install-Font.ps1.")
        return 0
    receipt = Path.home() / ".local/state/terminal-kit/windows-host.json"
    before = fingerprint(target)
    previous = json.loads(receipt.read_text()) if receipt.exists() else None
    if previous and before != previous["installed"]:
        raise Conflict("Windows Terminal kit fragment was edited; no Windows settings changed")
    if before["type"] != "absent" and not previous:
        raise Conflict("An unowned Windows Terminal fragment already exists; move it aside before applying")
    atomic_write(target, content, 0o644)
    write_json(receipt, {"path": str(target), "root": mount, "installed": fingerprint(target), "distro": distro})
    print("Fragment installed. Open Windows Terminal and choose its terminal-kit profile.")
    return 0


def remove_fragment(home, dry_run=False):
    """Remove the owned Windows Terminal fragment when its receipt still matches.

    This is a callable uninstall helper; importing the module or installing
    terminal-kit never invokes it. An edited fragment is left untouched.
    """
    home = Path(home).absolute()
    receipt = home / ".local/state/terminal-kit/windows-host.json"
    if not receipt.exists():
        return {"status": "absent", "detail": "No Windows host fragment receipt"}
    try:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        target = Path(record["path"])
        installed = record["installed"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Conflict("Windows fragment receipt is invalid; no files were removed") from exc

    expected_tail = ("Microsoft", "Windows Terminal", "Fragments", "terminal-kit", "terminal-kit.json")
    if not target.is_absolute() or ".." in target.parts or tuple(target.parts[-len(expected_tail):]) != expected_tail:
        raise Conflict("Windows fragment receipt points outside the owned Terminal fragment; no files were removed")
    root = record.get("root")
    if root:
        root_path = Path(root)
        if not root_path.is_absolute() or ".." in root_path.parts or target != root_path.joinpath(*expected_tail):
            raise Conflict("Windows fragment does not match its recorded LocalAppData root")
    elif tuple(target.parts[-len(expected_tail)-2:-len(expected_tail)]) != ("AppData", "Local"):
        raise Conflict("Legacy Windows fragment has no validated LocalAppData root")
    if any(parent.is_symlink() for parent in target.parents):
        raise Conflict("Windows fragment path contains a symlink; no files were removed")
    actual = fingerprint(target)
    if actual == {"type": "absent"}:
        if not dry_run:
            receipt.unlink()
        return {"status": "absent", "path": str(target), "detail": "Fragment was already absent; receipt removed"}
    if actual != installed:
        raise Conflict("Windows Terminal kit fragment was edited; no files were removed")
    if dry_run:
        return {"status": "ready", "path": str(target), "detail": "Owned Windows fragment can be removed safely"}
    target.unlink()
    receipt.unlink()
    return {"status": "removed", "path": str(target), "detail": "Owned Windows Terminal fragment removed"}
