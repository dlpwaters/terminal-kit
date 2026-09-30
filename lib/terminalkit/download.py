"""Bounded, checked transport and archive extraction."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


class DownloadError(RuntimeError):
    pass


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise DownloadError("Refusing a redirect away from HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, dest, sha256=None, max_bytes=500 * 1024 * 1024):
    """Cache only complete verified files. An absent hash is an explicit trust choice."""
    dest = Path(dest)
    if urllib.parse.urlsplit(url).scheme != "https":
        raise DownloadError("Only HTTPS downloads are allowed")
    if sha256 and (len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256)):
        raise DownloadError("Invalid SHA-256 pin")
    if dest.is_file() and sha256 and hashlib.sha256(dest.read_bytes()).hexdigest() == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".download-", dir=dest.parent)
    digest = hashlib.sha256()
    count = 0
    try:
        opener = urllib.request.build_opener(HTTPSRedirect())
        request = urllib.request.Request(url, headers={"User-Agent": "terminal-kit/0.1"})
        for attempt in range(2):
            try:
                response = opener.open(request, timeout=45)
                break
            except urllib.error.HTTPError as exc:
                exc.close()
                if attempt or exc.code not in (429, 500, 502, 503, 504):
                    # URLs and headers can contain signed credentials.
                    raise DownloadError(f"Download server returned HTTP {exc.code}") from exc
                time.sleep(1)
        with response, os.fdopen(fd, "wb") as output:
            fd = None
            expected = response.headers.get("Content-Length")
            if expected and int(expected) > max_bytes:
                raise DownloadError("Download exceeds size limit")
            if "text/html" in response.headers.get("Content-Type", "").lower():
                raise DownloadError("Server returned an HTML page")
            while True:
                block = response.read(64 * 1024)
                if not block:
                    break
                count += len(block)
                if count > max_bytes:
                    raise DownloadError("Download exceeds size limit")
                if count == len(block) and block.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                    raise DownloadError("Server returned HTML instead of an artifact")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
            if not count or (expected and count != int(expected)):
                raise DownloadError("Empty or truncated download")
        if sha256 and digest.hexdigest() != sha256:
            raise DownloadError("SHA-256 verification failed")
        os.replace(tmp, dest)
        return dest
    except Exception as exc:
        if isinstance(exc, DownloadError):
            raise
        raise DownloadError(f"Download failed: {type(exc).__name__}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)


def validate_script(path, bash="/bin/bash"):
    content = Path(path).read_bytes()
    if not content or len(content) > 2 * 1024 * 1024:
        raise DownloadError("Invalid script size")
    if not content.startswith(b"#!/") or b"\x00" in content:
        raise DownloadError("Downloaded file is not a shell script")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DownloadError("Downloaded script is not UTF-8") from exc
    if subprocess.run([bash, "-n", str(path)], capture_output=True).returncode:
        raise DownloadError("Downloaded script failed Bash syntax validation")


def _target(dest, name):
    path = PurePosixPath(name)
    if not name or "\\" in name or "\x00" in name or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise DownloadError("Unsafe archive member")
    target = dest.joinpath(*path.parts)
    if not target.resolve().is_relative_to(dest.resolve()):
        raise DownloadError("Archive path escapes destination")
    return target


def safe_extract(archive, dest, max_bytes=2 * 1024 * 1024 * 1024, max_files=60000):
    """Never follow an archive-created link while writing subsequent members."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    count = total = 0
    links = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                count += 1
                total += member.file_size
                if count > max_files or total > max_bytes:
                    raise DownloadError("Archive exceeds extraction limits")
                target = _target(dest, member.filename)
                mode = member.external_attr >> 16
                if mode & 0o170000 == 0o120000:
                    links.append((target, source.read(member).decode(), False))
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as inp, target.open("xb") as out:
                        shutil.copyfileobj(inp, out)
                    target.chmod(mode & 0o777 or 0o644)
    else:
        with tarfile.open(archive) as source:
            for member in source:
                count += 1
                total += member.size
                if count > max_files or total > max_bytes:
                    raise DownloadError("Archive exceeds extraction limits")
                target = _target(dest, member.name)
                if member.issym() or member.islnk():
                    links.append((target, member.linkname, member.islnk()))
                elif member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as inp, target.open("xb") as out:
                        shutil.copyfileobj(inp, out)
                    target.chmod(member.mode & 0o777)
                else:
                    raise DownloadError("Refusing special archive files")
    for target, link, hard in links:
        link_path = _target(dest, link) if hard else target.parent / link
        if not link_path.resolve().is_relative_to(dest.resolve()):
            raise DownloadError("Archive link escapes destination")
        _target(dest, str(target.relative_to(dest)))
        target.parent.mkdir(parents=True, exist_ok=True)
        if hard:
            os.link(link_path, target)
        else:
            os.symlink(link, target)
