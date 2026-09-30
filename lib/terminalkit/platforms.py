"""Host detection and support policy for terminal-kit."""

from __future__ import annotations

import os
import platform as _platform
import re
import sys
from pathlib import Path


_SUPPORTED_DISTROS = {
    "ubuntu": ("22.04", "24.04", "26.04"),
    "debian": ("12", "13"),
    "fedora": ("42", "43", "44"),
    "arch": ("rolling",),
}


def _os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key] = value
    except OSError:
        pass
    return values


def _arch(machine: str) -> str:
    return {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine.lower(), machine.lower())


def detect(env: dict[str, str] | None = None, *, os_release: dict[str, str] | None = None) -> dict:
    """Return normalized host facts and a conservative support decision.

    `env` and `os_release` may be supplied by tests; host defaults inspect only
    standard OS metadata and environment flags.
    """
    env = os.environ if env is None else env
    facts = _os_release() if os_release is None else os_release
    system = _platform.system().lower()
    if system == "darwin":
        os_name, distro, version, pm = "macos", "macos", _platform.mac_ver()[0], "brew"
    elif system == "linux":
        distro = facts.get("ID", "linux").lower()
        if distro != "arch" and "arch" in facts.get("ID_LIKE", "").lower().split():
            distro = "arch"
            # Arch derivatives roll continuously; their own image version is
            # not an Arch repository release number.
            facts = {**facts, "VERSION_ID": ""}
        version = facts.get("VERSION_ID", "")
        os_name = "linux"
        pm = {"ubuntu": "apt", "debian": "apt", "fedora": "dnf", "arch": "pacman"}.get(distro)
    else:
        os_name, distro, version, pm = system or "unknown", system or "unknown", "", None

    machine = _arch(_platform.machine())
    release = _platform.release().lower()
    wsl = int(env.get("WSL_INTEROP", "") != "")
    if not wsl and "microsoft" in release:
        wsl = 1
    if wsl and "wsl2" in release:
        wsl = 2
    display = bool(env.get("WAYLAND_DISPLAY") or env.get("DISPLAY") or (os_name == "macos" and env.get("TERM_PROGRAM")))
    ssh = bool(env.get("SSH_CONNECTION") or env.get("SSH_CLIENT") or env.get("SSH_TTY"))
    supported = False
    reason = "unsupported operating system"
    if os_name == "macos":
        # The installer supports recent macOS with official binaries. On Intel,
        # Homebrew is Tier 3; Apple Silicon 15+ is in Homebrew's current CI tier.
        try:
            major = int(version.split(".", 1)[0])
        except ValueError:
            major = 0
        floor = 13 if machine == "x86_64" else 15
        supported = machine in ("x86_64", "aarch64") and major >= floor
        reason = ("supported; Intel macOS has a Homebrew support-tier caveat" if supported and machine == "x86_64" else "supported") if supported else f"macOS {floor}+ on {machine} is required"
    elif os_name == "linux":
        allowed = _SUPPORTED_DISTROS.get(distro, ())
        normalized_version = version
        if distro == "arch":
            normalized_version = "rolling"
        arch_supported = machine == "x86_64" or (machine == "aarch64" and distro in ("ubuntu", "debian", "fedora"))
        supported = arch_supported and pm is not None and normalized_version in allowed and wsl != 1
        if wsl == 1:
            reason = "WSL 1 is unsupported; use WSL 2"
        else:
            reason = "supported" if supported else f"unsupported Linux target: {distro} {version or 'unknown'} on {machine}"

    return {
        "os": os_name,
        "distro": distro,
        "version": version,
        "arch": machine,
        "pm": pm,
        "supported": supported,
        "reason": reason,
        "wsl": wsl,
        "display": display,
        "ssh": ssh,
        "interactive_terminal": bool(sys.stdin.isatty() and sys.stdout.isatty()),
        "display_protocol": "wayland" if env.get("WAYLAND_DISPLAY") else ("x11" if env.get("DISPLAY") else ("macos" if os_name == "macos" and display else None)),
        "service_manager": "systemd" if os_name == "linux" and Path("/run/systemd/system").exists() else ("launchd" if os_name == "macos" else None),
        "windows_interop": bool(wsl and (Path("/mnt/c/Windows/System32").exists() or env.get("COMSPEC"))),
    }
