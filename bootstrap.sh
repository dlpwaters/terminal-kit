#!/bin/bash
# Download completely, verify, inspect the archive, then execute. Bash 3.2 safe.
set -euo pipefail
tk_repo=dlpwaters/terminal-kit
tk_ref=v0.1.0
tk_transport=auto
tk_sha=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo|--ref|--transport|--sha256)
      [ "$#" -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      case "$1" in --repo) tk_repo=$2 ;; --ref) tk_ref=$2 ;; --transport) tk_transport=$2 ;; --sha256) tk_sha=$2 ;; esac
      shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
case "$tk_repo" in *[!a-zA-Z0-9_./-]*|/*|*..*|*/*/*) echo 'Invalid GitHub repository' >&2; exit 2 ;; esac
case "$tk_ref" in ''|-*|*[!a-zA-Z0-9._-]*|*..*) echo 'Invalid release name' >&2; exit 2 ;; esac
case "$tk_transport" in auto|curl|gh) ;; *) echo 'Transport must be auto, curl or gh' >&2; exit 2 ;; esac
if [ -n "$tk_sha" ]; then
  [ "${#tk_sha}" -eq 64 ] || { echo 'Invalid SHA-256 pin' >&2; exit 2; }
  case "$tk_sha" in *[!0-9a-f]*) echo 'Invalid SHA-256 pin' >&2; exit 2 ;; esac
fi
if [ "$tk_transport" = auto ]; then
  if command -v gh >/dev/null 2>&1; then tk_transport=gh; else tk_transport=curl; fi
fi
umask 077
tk_tmp=$(mktemp -d "${TMPDIR:-/tmp}/terminal-kit.XXXXXXXX")
trap 'rm -rf "$tk_tmp"' EXIT HUP INT TERM
tk_archive="terminal-kit-$tk_ref.tar.gz"
if [ "$tk_transport" = gh ]; then
  command -v gh >/dev/null 2>&1 || { echo 'Private bootstrap requires gh and gh auth login on this machine.' >&2; exit 2; }
  gh release download "$tk_ref" --repo "$tk_repo" --pattern "$tk_archive" --dir "$tk_tmp"
  if [ -z "$tk_sha" ]; then gh release download "$tk_ref" --repo "$tk_repo" --pattern SHA256SUMS --dir "$tk_tmp"; fi
else
  command -v curl >/dev/null 2>&1 || { echo 'Install curl before running this bootstrap.' >&2; exit 2; }
  tk_base="https://github.com/$tk_repo/releases/download/$tk_ref"
  curl --proto '=https' --tlsv1.2 --fail --location --connect-timeout 10 --max-time 120 --max-filesize 20971520 --output "$tk_tmp/$tk_archive" "$tk_base/$tk_archive"
  if [ -z "$tk_sha" ]; then
    curl --proto '=https' --tlsv1.2 --fail --location --connect-timeout 10 --max-time 30 --max-filesize 4096 --output "$tk_tmp/SHA256SUMS" "$tk_base/SHA256SUMS"
  fi
fi
[ "$(wc -c < "$tk_tmp/$tk_archive")" -le 20971520 ] || { echo 'Compressed release exceeds size limit.' >&2; exit 1; }
if [ -z "$tk_sha" ]; then
  tk_sha=$(awk -v file="$tk_archive" '$2 == file || $2 == "*" file { print $1 }' "$tk_tmp/SHA256SUMS")
  [ "${#tk_sha}" -eq 64 ] || { echo 'Release checksum is missing or malformed.' >&2; exit 1; }
  case "$tk_sha" in *[!0-9a-f]*) echo 'Release checksum is invalid.' >&2; exit 1 ;; esac
fi
if command -v sha256sum >/dev/null 2>&1; then
  tk_actual=$(sha256sum "$tk_tmp/$tk_archive" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
  tk_actual=$(shasum -a 256 "$tk_tmp/$tk_archive" | awk '{print $1}')
else
  echo 'A SHA-256 utility (sha256sum or shasum) is required.' >&2; exit 2
fi
[ "$tk_actual" = "$tk_sha" ] || { echo 'Release archive SHA-256 mismatch; nothing executed.' >&2; exit 1; }
# Bound decompression as well as the compressed transfer. No links in our release.
if ! gzip -dc "$tk_tmp/$tk_archive" | head -c 134217729 > "$tk_tmp/release.tar"; then
  echo 'Release decompression failed or exceeded the size limit.' >&2
  exit 1
fi
tk_size=$(wc -c < "$tk_tmp/release.tar" | tr -d ' ')
[ "$tk_size" -le 134217728 ] || { echo 'Release exceeds extraction size limit.' >&2; exit 1; }
tar -tf "$tk_tmp/release.tar" > "$tk_tmp/members"
awk 'BEGIN { ok=1 } !/^terminal-kit\// || /(^|\/)\.\.(\/|$)/ || /\\/ || /[[:cntrl:]]/ { ok=0 } END { if (NR == 0 || NR > 5000) ok=0; exit !ok }' "$tk_tmp/members" || { echo 'Unsafe release archive paths.' >&2; exit 1; }
LC_ALL=C tar -tvf "$tk_tmp/release.tar" > "$tk_tmp/types"
awk 'substr($0,1,1) != "-" && substr($0,1,1) != "d" { exit 1 }' "$tk_tmp/types" || { echo 'Archive contains links or special files.' >&2; exit 1; }
tar -xf "$tk_tmp/release.tar" -C "$tk_tmp"
[ -s "$tk_tmp/terminal-kit/install.sh" ] && [ -s "$tk_tmp/terminal-kit/lib/terminalkit/cli.py" ] || { echo 'Release is incomplete.' >&2; exit 1; }
head -n 1 "$tk_tmp/terminal-kit/install.sh" | LC_ALL=C grep -q '^#!/.*bash' || { echo 'Installer is not a Bash script.' >&2; exit 1; }
/bin/bash -n "$tk_tmp/terminal-kit/install.sh"
echo "Verified $tk_repo $tk_ref ($tk_sha)"
/bin/bash "$tk_tmp/terminal-kit/install.sh" "$@"
