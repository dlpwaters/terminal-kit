"""Config ownership with write-ahead recovery, conflict detection, and backups."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid


class Conflict(RuntimeError):
    pass


def fingerprint(path):
    path = Path(path)
    if path.is_symlink():
        return {"type": "symlink", "target": os.readlink(path)}
    if not path.exists():
        return {"type": "absent"}
    if path.is_file():
        return {"type": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mode": path.stat().st_mode & 0o777}
    if path.is_dir():
        return {"type": "directory", "entries": {str(p.relative_to(path)): fingerprint(p) for p in sorted(path.iterdir())}}
    raise Conflict(f"Unsupported file type: {path}")


def atomic_write(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".terminal-kit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, data):
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())


@contextmanager
def lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Conflict("Another terminal-kit operation is running") from exc
        yield


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def copy_path(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        target.symlink_to(os.readlink(source))
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    elif source.is_file():
        shutil.copy2(source, target)


def restore_leaf(source, target):
    """Restore regular files and links atomically; absent originals are unlinked."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        temporary = target.parent / (".terminal-kit-restore-" + uuid.uuid4().hex)
        temporary.symlink_to(os.readlink(source))
        os.replace(temporary, target)
    elif source.is_file():
        atomic_write(target, source.read_bytes(), source.stat().st_mode & 0o777)
    elif not source.exists():
        remove(target)
    else:
        raise Conflict("Automatic directory restoration is unsupported")


class State:
    def __init__(self, home):
        self.home = Path(home).absolute()
        self.root = self.home / ".local/state/terminal-kit"
        for parent in [self.root, *self.root.parents]:
            if parent == self.home:
                break
            if parent.is_symlink():
                raise Conflict(f"State directory symlink collision: {parent}")
        self.path = self.root / "ownership.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"schema": 1, "files": {}}
        self.transaction = None

    def save(self):
        write_json(self.path, self.data)

    def destination(self, relative):
        path = self.home / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise Conflict("Managed paths must be relative to HOME")
        # A symlink at the leaf is backed up; a directory link is a collision.
        for parent in path.parents:
            if parent == self.home:
                break
            if parent.is_symlink():
                raise Conflict(f"Directory symlink collision: {parent}; choose a real config directory")
        return path

    def begin(self, operation):
        identity = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        receipt = self.root / "installation.json"
        self.transaction = {"id": identity, "operation": operation, "status": "in-progress", "changes": [], "before_receipt": json.loads(receipt.read_text()) if receipt.exists() else None}
        directory = self.root / "backups" / identity
        directory.mkdir(parents=True, mode=0o700)
        self.journal()
        return identity

    def journal(self):
        write_json(self.root / "backups" / self.transaction["id"] / "manifest.json", self.transaction)

    def recover(self):
        if not (self.root / "backups").exists():
            return
        for manifest in sorted((self.root / "backups").glob("*/manifest.json")):
            txn = json.loads(manifest.read_text())
            if txn["status"] == "restoring":
                self._restore_transaction(txn, manifest)
                continue
            if txn["status"] != "in-progress":
                continue
            for change in txn["changes"]:
                actual = fingerprint(self.destination(change["path"]))
                if actual == change["after"]:
                    self.data["files"][change["path"]] = change["entry"]
                elif actual != change["before"]:
                    raise Conflict(f"Interrupted operation has a conflicting edit: {change['path']}")
            txn["status"] = "interrupted-recovered"
            write_json(manifest, txn)
        self.save()

    def apply(self, relative, content=None, mode=0o644, link=None, hook=False):
        path = self.destination(relative)
        before = fingerprint(path)
        previous = self.data["files"].get(relative)
        block_pattern = r"(?ms)^# >>> terminal-kit managed include >>>\n.*?^# <<< terminal-kit managed include <<<\n?"
        if previous and hook:
            actual_block = re.findall(block_pattern, path.read_text() if path.is_file() else "")
            if actual_block != [previous.get("block")]:
                raise Conflict(f"Managed include was edited: {path}")
        after = {"type": "symlink", "target": link} if link is not None else {"type": "file", "sha256": hashlib.sha256(content).hexdigest(), "mode": mode}
        if before == after:
            # Equal preexisting files are shared, unless already owned.
            return False
        if previous and before != previous["installed"] and not hook:
            raise Conflict(f"Local edits in managed file: {path}; move them to the local override layer")
        if path.is_dir() and not path.is_symlink():
            raise Conflict(f"Directory collision: {path}")
        index = len(self.transaction["changes"])
        saved = self.root / "backups" / self.transaction["id"] / str(index)
        copy_path(path, saved)
        origin = previous["origin"] if previous else {"transaction": self.transaction["id"], "index": index, "fingerprint": before}
        entry = {"installed": after, "origin": origin, "hook": hook}
        if hook:
            entry["block"] = re.search(block_pattern, content.decode()).group(0)
        change = {"path": relative, "before": before, "after": after, "before_entry": previous, "entry": entry, "index": index}
        self.transaction["changes"].append(change)
        self.journal()  # recovery can distinguish pre-write and post-write crashes
        path.parent.mkdir(parents=True, exist_ok=True)
        if link is not None:
            temporary = path.parent / (".terminal-kit-link-" + uuid.uuid4().hex)
            temporary.symlink_to(link)
            os.replace(temporary, path)
        else:
            atomic_write(path, content, mode)
        self.data["files"][relative] = entry
        self.save()
        return True

    def finish(self):
        self.transaction["status"] = "complete"
        receipt = self.root / "installation.json"
        self.transaction["after_receipt"] = json.loads(receipt.read_text()) if receipt.exists() else None
        self.journal()
        self.save()

    def rollback(self, identity):
        if "/" in identity or identity in (".", ".."):
            raise Conflict("Invalid backup ID")
        manifest = self.root / "backups" / identity / "manifest.json"
        if not manifest.exists():
            raise Conflict("Backup ID not found; run terminal-kit rollback --list")
        txn = json.loads(manifest.read_text())
        if txn["status"] not in ("complete", "interrupted-recovered") or txn["operation"] not in ("install", "theme"):
            raise Conflict("Only a completed configuration install/theme backup can be rolled back")
        # Check every path before touching any path.
        for change in txn["changes"]:
            if fingerprint(self.destination(change["path"])) != change["after"]:
                raise Conflict(f"Changed since this backup: {change['path']}; nothing restored")
        self.begin("rollback")
        restoration = self.transaction
        restoration.update(status="restoring", receipt=txn.get("before_receipt"), target=identity)
        for change in reversed(txn["changes"]):
            restoration["changes"].append({"path": change["path"], "before": change["after"], "after": change["before"], "source": str((manifest.parent / str(change["index"])).relative_to(self.root)), "entry": change["before_entry"]})
        self.journal()
        self._restore_transaction(restoration, self.root / "backups" / restoration["id"] / "manifest.json")

    def _restore_transaction(self, txn, manifest):
        for change in txn["changes"]:
            path = self.destination(change["path"])
            actual = fingerprint(path)
            if actual not in (change["before"], change["after"]):
                raise Conflict(f"Recovery conflict at {change['path']}; no further restoration performed")
        for change in txn["changes"]:
            path = self.destination(change["path"])
            if fingerprint(path) == change["before"]:
                restore_leaf(self.root / change["source"], path)
            if change["entry"] is None:
                self.data["files"].pop(change["path"], None)
            else:
                self.data["files"][change["path"]] = change["entry"]
            self.save()
        receipt = self.root / "installation.json"
        if txn.get("receipt") is None:
            receipt.unlink(missing_ok=True)
        else:
            write_json(receipt, txn["receipt"])
        if txn.get("target"):
            target = self.root / "backups" / txn["target"] / "manifest.json"
            old = json.loads(target.read_text())
            old["status"] = "rolled-back"
            write_json(target, old)
        txn["status"] = "restored"
        write_json(manifest, txn)

    def uninstall(self, strip_hook):
        plans = []
        for relative, entry in self.data["files"].items():
            path = self.destination(relative)
            actual = fingerprint(path)
            if entry["hook"] and actual != entry["installed"] and actual["type"] == "file":
                pattern = r"(?ms)^# >>> terminal-kit managed include >>>\n.*?^# <<< terminal-kit managed include <<<\n?"
                if re.findall(pattern, path.read_text()) != [entry.get("block")]:
                    raise Conflict(f"Edited managed include: {path}; uninstall made no changes")
                plans.append((relative, entry, strip_hook(path.read_text(), relative)))
            elif actual != entry["installed"]:
                raise Conflict(f"Edited owned file: {path}; uninstall made no changes")
            else:
                plans.append((relative, entry, None))
        self.begin("uninstall")
        restoration = self.transaction
        receipt = self.root / "installation.json"
        data = json.loads(receipt.read_text()) if receipt.exists() else {}
        data["status"] = "uninstalled"
        restoration.update(status="restoring", receipt=data)
        for index, (relative, entry, remaining) in enumerate(reversed(plans)):
            path = self.destination(relative)
            if remaining is not None:
                source = self.root / "backups" / restoration["id"] / ("remaining-" + str(index))
                atomic_write(source, remaining.encode(), path.stat().st_mode & 0o777)
            else:
                origin = entry["origin"]
                source = self.root / "backups" / origin["transaction"] / str(origin["index"])
            restoration["changes"].append({"path": relative, "before": fingerprint(path), "after": fingerprint(source), "source": str(source.relative_to(self.root)), "entry": None})
        self.journal()
        self._restore_transaction(restoration, self.root / "backups" / restoration["id"] / "manifest.json")
