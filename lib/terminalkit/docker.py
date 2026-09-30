"""Docker is an opt-in host decision; Lazydocker alone is a client."""
import os
from pathlib import Path
import shutil
import subprocess
from .platforms import detect
from .state import Conflict


def configure(args):
    facts = detect()
    client = shutil.which("docker")
    working = False
    if client:
        try:
            check = subprocess.run([client, "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=5)
            working = check.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    if working:
        print("Existing Docker daemon/context is reachable; preserving its configuration.")
        return 0
    if facts["os"] == "macos":
        print("Use a host solution such as Docker Desktop for Mac. Install/open it yourself, then rerun terminal-kit docker.")
        return 2 if args.install_engine else 0
    if facts["wsl"]:
        print("WSL: first check Docker Desktop's integration for this distribution. Do not install a competing Linux daemon.")
        if args.install_engine:
            raise Conflict("Automatic Engine installation in WSL is unavailable; use your existing Windows host solution or follow the documented explicit Linux Engine setup")
        return 0
    if not args.install_engine:
        print("Docker Engine is not reachable. To install from native repositories: terminal-kit docker --install-engine\nNo Docker group membership or socket privileges are granted by terminal-kit.")
        return 0
    if client or Path("/var/run/docker.sock").exists():
        raise Conflict("Existing Docker installation/socket detected; repair or start it before adding another daemon")
    if not facts["supported"]:
        raise Conflict(facts["reason"])
    from .tools import _run_native
    package = {"apt": "docker.io", "dnf": "moby-engine", "pacman": "docker"}.get(facts["pm"])
    if not package:
        raise Conflict("No native Docker Engine package is configured on this platform")
    commands = {"apt": ["apt-get", "install", "-y", package], "dnf": ["dnf", "install", "-y", package], "pacman": ["pacman", "-S", "--needed", *( ["--noconfirm"] if args.unattended else []), package]}
    print("Installing native Docker Engine. Its package scripts may start the daemon; no user/group or remote-access configuration will be changed.", flush=True)
    check = _run_native(commands[facts["pm"]], facts["pm"], args.unattended)
    if check.returncode:
        raise Conflict("Native Engine installation failed; review package-manager output")
    print("Engine package installed. An administrator may need to start docker.service. Keep privileged access explicit; terminal-kit does not add you to the docker group.")
    return 0
