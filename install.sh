#!/bin/bash
# This entry point is intentionally compatible with Apple's Bash 3.2.
set -euo pipefail
tk_root=$(cd -P "$(dirname "$0")" && pwd)
tk_dry=0
tk_unattended=0
for tk_arg in "$@"; do
  case "$tk_arg" in --dry-run) tk_dry=1 ;; --unattended) tk_unattended=1 ;; esac
done
if [ "$(id -u)" -eq 0 ] && [ "$tk_dry" -eq 0 ]; then
  echo 'terminal-kit: run as your normal user, not root. Elevation is limited to package operations.' >&2
  exit 2
fi
tk_brew=$(command -v brew || true)
if [ -z "$tk_brew" ] && [ "$(uname -s)" = Darwin ]; then
  for tk_candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$tk_candidate" ]; then tk_brew=$tk_candidate; break; fi
  done
  if [ -z "$tk_brew" ] && [ "$tk_dry" -eq 0 ]; then
    if [ "$tk_unattended" -eq 1 ]; then
      /bin/bash "$tk_root/scripts/bootstrap-homebrew.sh" --unattended
    else
      /bin/bash "$tk_root/scripts/bootstrap-homebrew.sh"
    fi
    tk_brew=$(command -v brew || true)
    for tk_candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      if [ -z "$tk_brew" ] && [ -x "$tk_candidate" ]; then tk_brew=$tk_candidate; fi
    done
    [ -n "$tk_brew" ] || { echo 'Homebrew installation did not provide brew; inspect its output and rerun.' >&2; exit 2; }
  fi
fi
if [ -n "$tk_brew" ]; then
  tk_prefix=$("$tk_brew" --prefix)
  export PATH="$tk_prefix/bin:$tk_prefix/sbin:$PATH"
  export HOMEBREW_NO_AUTO_UPDATE=1
fi
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3,9))' 2>/dev/null; then
  if [ "$tk_dry" -eq 1 ]; then
    echo 'Dry run: Python 3.9+ is required to inspect the installation plan; no changes made.'
    exit 2
  fi
  if [ "$(uname -s)" = Darwin ]; then
    if [ -z "$tk_brew" ]; then
      echo 'Install Homebrew and Apple Command Line Tools first: https://brew.sh . Then rerun this command.' >&2
      exit 2
    fi
    "$tk_brew" install --force-bottle python
  else
    if ! command -v sudo >/dev/null 2>&1; then
      echo 'Ask an administrator to install Python 3.9+ and sudo, then rerun as your normal user.' >&2
      exit 2
    fi
    if [ "$tk_unattended" -eq 1 ]; then
      sudo -n true || { echo 'Python bootstrap requires pre-authorized sudo -n.' >&2; exit 2; }
    fi
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get install -y python3
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y python3
    elif command -v pacman >/dev/null 2>&1; then
      sudo pacman -S --needed --noconfirm python
    else
      echo 'Unsupported package manager; install Python 3.9+ yourself.' >&2; exit 2
    fi
  fi
fi
# Bootstrap modern Bash before using a newer shell. Do not change login shells.
if [ "${BASH_VERSINFO[0]}" -lt 4 ] && [ "$tk_dry" -eq 0 ]; then
  if [ -z "$tk_brew" ]; then
    echo 'Bash 4+ is required; install modern Bash with your package manager.' >&2; exit 2
  fi
  tk_bash="$tk_prefix/bin/bash"
  if [ ! -x "$tk_bash" ]; then
    echo 'Installing modern Bash with Homebrew; Intel Macs may build this small shell dependency from source.'
    case "$(uname -m)" in
      x86_64) "$tk_brew" install --build-from-source bash ;;
      *) "$tk_brew" install bash ;;
    esac
  fi
  exec "$tk_bash" "$tk_root/install.sh" "$@"
fi
exec "$tk_root/bin/terminal-kit" install "$@"
