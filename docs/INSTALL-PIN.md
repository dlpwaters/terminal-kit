# Verified v0.1.0 installation

The public [v0.1.0 release](https://github.com/dlpwaters/terminal-kit/releases/tag/v0.1.0) was published and its actual bootstrap/archive downloads verified on 2026-09-30. No GitHub account is required. Run inside an initialized Bash-capable environment; Windows needs WSL2 and a Linux user beforehand.

This command fixes the bootstrap to immutable commit `bacafd2d1c66b6dd35a35278d22e9bbc66dff0f9` and checks the archive against the independently recorded SHA-256:

```bash
bash -c 'set -e; umask 077; d=$(mktemp -d "${TMPDIR:-/tmp}/terminal-kit-entry.XXXXXXXX"); trap "rm -rf -- \"\$d\"" EXIT; curl --proto "=https" --tlsv1.2 -fsSL --connect-timeout 10 --max-time 60 --max-filesize 65536 https://raw.githubusercontent.com/dlpwaters/terminal-kit/bacafd2d1c66b6dd35a35278d22e9bbc66dff0f9/bootstrap.sh -o "$d/bootstrap.sh"; head -n 1 "$d/bootstrap.sh" | grep -qx "#!/bin/bash"; bash -n "$d/bootstrap.sh"; bash "$d/bootstrap.sh" --transport curl --sha256 9798b83dba70fdfaee1ae386c9a3d20f33dbd36fbb059e52f6095d82a9652ca6 -- "$@"' terminal-kit
```

Append `--dry-run` for a read-only preview or `--profile headless` for an explicit CLI-only setup. Debian 12/Ubuntu 22.04 require `--with treesitter-build`. Intel's explicit `--with intel-build` path is incomplete; consult the [Intel handoff](STATUS.md#intel-mac-follow-up) before attempting it.

Both this command and the convenient tag-based command in the README passed live anonymous dry runs against the published release. The earlier authenticated transport also passed. The downloaded archive passed actual install/repeat/doctor/rollback/uninstall acceptance in an isolated Ubuntu 24.04.5 environment. The archive's GitHub-reported digest matches the independent build digest, and two independent archive builds were byte-for-byte identical.

The source commit, archive digest and bootstrap digest are published in `RELEASE.json`. This page lives in the repository after packaging so the archive does not contain a circular checksum of itself. HTTPS/GitHub account trust applies to transport; retain these pins independently if stronger protection against a replaced release is needed.
