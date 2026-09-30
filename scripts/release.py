#!/usr/bin/env python3
"""Build a reproducible release from the exact committed tree."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tarfile
import tempfile
import gzip
import json

parser = argparse.ArgumentParser()
parser.add_argument("--version", default="v0.1.0")
parser.add_argument("--output", default=".artifacts")
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
if subprocess.check_output(["git", "status", "--porcelain"], cwd=repo):
    raise SystemExit("Commit the reviewed tree before building release artifacts")
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=True)
artifact = out / f"terminal-kit-{args.version}.tar.gz"
with tempfile.TemporaryDirectory(prefix="terminal-kit-release-") as tmp:
    archive = Path(tmp) / "release.tar"
    subprocess.run(["git", "archive", "--format=tar", "--prefix=terminal-kit/", "-o", str(archive), "HEAD"], cwd=repo, check=True)
    with archive.open("rb") as inp, artifact.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            while block := inp.read(1024 * 1024):
                compressed.write(block)
checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
(out / "SHA256SUMS").write_text(f"{checksum}  {artifact.name}\n")
(out / "RELEASE.json").write_text(json.dumps({
    "version": args.version,
    "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
    "archive": artifact.name,
    "sha256": checksum,
    "bootstrap_sha256": hashlib.sha256((repo / "bootstrap.sh").read_bytes()).hexdigest(),
}, indent=2) + "\n")
print(f"{artifact}\n{checksum}")
