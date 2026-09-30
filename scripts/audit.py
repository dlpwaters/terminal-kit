#!/usr/bin/env python3
"""Audit shipped runtime files; descriptions may name omitted Omarchy features."""
import re
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[1]
patterns = [r"/usr/share/omarchy", r"\.config/omarchy", r"\.local/state/omarchy", r"omarchy-[a-z]+", r"sk-[A-Za-z0-9_-]{20,}", r"gh[pousr]_[A-Za-z0-9]{30,}", r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"]
errors = []
for root in [repo / "lib", repo / "configs", repo / "bin", repo / "manifests"]:
    for path in root.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if root.name == "manifests":
                    patterns_here = patterns[-3:]
                else:
                    patterns_here = patterns
                if any(re.search(pattern, line) for pattern in patterns_here):
                    errors.append(f"{path.relative_to(repo)}:{number}: forbidden runtime reference or credential pattern")
if any("skills" in p.parts for p in (repo / "configs").rglob("*")):
    errors.append("Bundled skill directory found")
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("Runtime and credential-pattern audit passed")
