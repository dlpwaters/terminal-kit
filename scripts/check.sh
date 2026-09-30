#!/usr/bin/env bash
set -euo pipefail
tk_repo=$(cd "$(dirname "$0")/.." && pwd)
cd "$tk_repo"
export PYTHONPATH="$tk_repo/lib"
python3 -m unittest discover -s tests -v
while IFS= read -r tk_script; do
  bash -n "$tk_script"
done < <(find bin scripts -type f -name '*.sh'; printf '%s\n' bootstrap.sh install.sh bin/terminal-kit)
shellcheck -S warning bootstrap.sh install.sh bin/terminal-kit scripts/*.sh
bats tests/bootstrap.bats
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git diff --check; fi
python3 scripts/audit.py
