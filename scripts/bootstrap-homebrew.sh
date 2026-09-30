#!/bin/bash
# Compatible with macOS Bash 3.2; only the official installer provisions Brew.
set -euo pipefail
tk_brew_commit=f6632bc2e9afc0ba20cdee1f2d28bcd7672b3245
tk_brew_digest=fa4ed743b4ca38316c8f32fd6623baa5bbb928fd4a47ad9f49c2be78ea833449
tk_brew_tmp=$(mktemp -d "${TMPDIR:-/tmp}/terminal-kit-brew.XXXXXXXX")
trap 'rm -rf "$tk_brew_tmp"' EXIT HUP INT TERM
curl --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 180 \
  --output "$tk_brew_tmp/install.sh" "https://raw.githubusercontent.com/Homebrew/install/$tk_brew_commit/install.sh"
tk_brew_size=$(wc -c < "$tk_brew_tmp/install.sh")
if [ "$tk_brew_size" -lt 1000 ] || [ "$tk_brew_size" -gt 200000 ]; then
  echo 'terminal-kit: unexpected Homebrew installer size' >&2; exit 2
fi
tk_brew_actual=$(shasum -a 256 "$tk_brew_tmp/install.sh")
tk_brew_actual=${tk_brew_actual%% *}
[ "$tk_brew_actual" = "$tk_brew_digest" ] || { echo 'terminal-kit: Homebrew checksum mismatch' >&2; exit 2; }
/bin/bash -n "$tk_brew_tmp/install.sh"
echo 'Installing official Homebrew. Its installer may request macOS permissions or Command Line Tools.' >&2
if [ "${1:-}" = --unattended ]; then
  NONINTERACTIVE=1 /bin/bash "$tk_brew_tmp/install.sh"
elif [ -r /dev/tty ]; then
  /bin/bash "$tk_brew_tmp/install.sh" < /dev/tty
else
  echo 'terminal-kit: Homebrew needs a terminal for OS authorization; rerun interactively or provision Homebrew first.' >&2
  exit 2
fi
