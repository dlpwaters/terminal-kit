"""Seed locked plugin checkouts atomically, without resetting existing edits."""
from pathlib import Path
import subprocess
import tempfile

from .state import Conflict


def seed_plugin(destination: Path, url: str, commit: str, branch="main"):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise Conflict("Invalid plugin commit in lockfile")
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink():
            raise Conflict(f"Plugin path is a symlink: {destination}")
        head = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(destination), "status", "--porcelain", "--untracked-files=no"], text=True)
        if head != commit or dirty:
            raise Conflict(f"Existing {destination.name} differs from its lock or has edits; review it before updating")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    # An interrupted transfer can only leave a staging directory, never an
    # apparently installed plugin with an empty working tree.
    with tempfile.TemporaryDirectory(prefix=".terminal-kit-plugin-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "checkout"
        commands = [
            ["git", "init", "--quiet", str(stage)],
            ["git", "-C", str(stage), "remote", "add", "origin", url],
            ["git", "-C", str(stage), "fetch", "--depth", "1", "origin", commit],
            ["git", "-C", str(stage), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            ["git", "-C", str(stage), "update-ref", "refs/remotes/origin/" + branch, commit],
            ["git", "-C", str(stage), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + branch],
        ]
        for command in commands:
            subprocess.run(command, check=True, timeout=300, capture_output=True, text=True)
        stage.rename(destination)
