# Supported hosts and installed tools

The installer supports x86_64 Ubuntu 22.04, 24.04, and 26.04; Debian 12 and
13; Fedora 42, 43, and 44; and rolling Arch Linux. Debian, Ubuntu, and Fedora
also support aarch64 using official release binaries; Arch ARM remains outside
the support matrix. WSL 2 is a supported Linux host, while WSL 1 is rejected.
The detection floor is macOS 13 on Intel and 15 on Apple Silicon. Full Intel installation is currently incomplete; see the [known failure and follow-up](STATUS.md#intel-mac-follow-up). Intel Macs also carry a
Homebrew support-tier caveat; Homebrew's current [Tier 1 Apple Silicon range](https://docs.brew.sh/Support-Tiers)
starts at macOS 15. Other distributions are reported as unsupported rather
than receiving guessed package names or third-party repositories. Headless
and SSH sessions remain supported; display availability is recorded separately
for optional desktop features.

| Component | Supported install targets | Platform boundary |
| --- | --- | --- |
| Core CLI, shell, agents, editor | Supported Linux matrix above on x86_64; Debian/Ubuntu/Fedora on aarch64; macOS 13+ Intel and 15+ Apple Silicon; WSL2 uses its supported Linux distribution | Native packages and pinned binaries vary by target. Arch ARM, WSL1, unknown Linux releases, and Windows-native install are unsupported. A missing optional GUI component does not by itself fail CLI installation. |
| Ghostty | Arch Linux, macOS with Homebrew cask, Ubuntu 26.04+ official apt source | Other supported Linux versions and Windows have no kit-managed native Ghostty install. WSLg launch needs separate host validation. |
| Nerd Font | Linux and macOS user font directories | Windows Terminal must use the separate Windows font installer. WSL's Linux-side font path does not install on Windows. |
| Tree-sitter CLI | Official binary where its runtime ABI matches; source fallback is opt-in | On older glibc hosts use `./install.sh --with treesitter-build`. It compiles pinned 0.26.1 with isolated mise Rust and requires native libclang development headers; it does not update system libraries. |
| Intel macOS build dependencies | Explicit `--with intel-build`; currently incomplete | Latest real Intel install failed in Homebrew's outdated-dependency preflight; tmux/btop remained missing. Agents/editor installed, including Hermes with isolated Rust 1.92.0 and its unchanged cryptography 50.0.0 security pin. See the [Intel handoff](STATUS.md#intel-mac-follow-up); no full Intel acceptance is claimed. |
| Extras (`tealdeer`, `ncdu`, `tree`) | Native apt, dnf, pacman, and Homebrew package mappings | Optional `--with extras`; availability remains package-manager specific. |

The base tool set comes from the host's native package manager. Existing
commands are checked and reused, and the installer reports their version and
path. Missing or old Neovim, fzf, eza, zoxide, Starship, lazygit, and lazydocker
can use pinned official release assets with SHA-256 checks, installed below
`~/.local/share/terminal-kit/tools` and exposed through the kit-owned `bin`
directory. It does not run a full system upgrade. Native package installation uses
the normal sudo authorization path on Linux; unattended runs require existing
`sudo -n` authorization. Homebrew package operations use Homebrew; its first-run
official bootstrap may require macOS authorization or Command Line Tools.
Intel Macs use Homebrew's explicit source-build flag for small native dependencies such as Bash, completion, btop, jq, GNU tar and unzip. This is announced for the required Bash bootstrap and shown in dry-run plans. Neovim and the Rust/Go terminal tools, including ripgrep/fd/bat, use bottle-only attempts followed by pinned upstream release binaries; mise also has verified macOS release binaries. Missing bottles do not trigger an implicit Neovim or Rust application source build.
`--dry-run` only reports package commands and does not bootstrap Homebrew.

Package availability and versions vary by distribution. The manifest records
minimum versions for the core command interfaces and release asset hashes
checked while building this support matrix. If an installed executable falls
below its minimum, terminal-kit prefers a pinned upstream binary where
available; it does not compile arbitrary source or silently add a repository.
The optional `extras` module adds `tealdeer`, `ncdu`, and `tree`; Git TUIs are part of the required core. Docker Engine installation is a separate explicit opt-in; installing the Lazydocker client never grants group membership.

Pi and OpenCode use isolated npm prefixes and a compatible Node/npm runtime; when no suitable runtime exists, the kit installs pinned Node through mise. The optional `python` module installs Python through the same kit-managed mise data directory. Hermes uses its official installer pinned to the inspected commit and keeps its normal user data at `~/.hermes`. It uses Hermes's supported managed uv/Python flow, disables setup, browser and computer-use stages, and never runs the gateway stage. Existing Hermes data is preserved, and an incompatible existing Hermes-managed Node is reported instead of removed. Authentication stays with the user. The desktop profile installs JetBrainsMono Nerd Font from its pinned
release archive and retains the included license notice. Windows Terminal fonts
must be installed on Windows. Graphical WSL installs also install the Linux-side font for Ghostty's Linux client; headless WSL reports that Windows font installation is a separate host action.

Ghostty is installed only from a supported native package source: Arch,
Homebrew, or Ubuntu 26.04's official repository. No community repository or
source build is added automatically. A successful package install does not
prove that Ghostty launches through WSLg; that remains a host-level check.

WSL detection and Windows interop are reported independently from Linux
support. Linux-side font installation does not configure Windows Terminal, and
the WSL distribution having a display variable does not prove that a GUI
application can launch. Those desktop paths need separate live validation.

## Evidence boundary

| Check | Current evidence (2026-09-30) |
| --- | --- |
| ShellCheck and Bash syntax | Passed |
| Python unit tests | Host: 88/88 passed. Container: 87 passed, 1 skipped because Ghostty is unavailable (the host Ghostty validator test passed). |
| Bats checks | 8 passed |
| Isolated tmux layout | Passed in container |
| Debian 12 x86_64 | Clean CI and local recovery with explicit `--with treesitter-build`, parsers/LSPs/agents, doctor, rollback, and uninstall passed. Without the opt-in, older-glibc Tree-sitter availability is reported as partial. |
| Ubuntu 24.04.5 | Fresh install, repeated doctor, rollback, and uninstall passed |
| Fedora 44 | Fresh install, repeated doctor, rollback, and uninstall passed |
| Arch x86_64 | Official base image `20260927.0.600689`, tested 2026-09-30: fresh/repeat, agents/editor, doctor, rollback and uninstall passed. Docker needed `DAC_READ_SEARCH` and `PERFMON` for the native btop file capabilities; no host files/process namespace were shared. |
| macOS CI | Regression checks passed on macOS 15 Apple Silicon and Intel. Real Apple Silicon 15.7.9 headless fresh/repeat/doctor/rollback/uninstall passed. Latest Intel 15.7.9 attempt failed in `brew outdated` preflight and left tmux/btop missing; agents/editor installed. Further Intel work is deferred, with exact failure and acceptance checks in [Status](STATUS.md#intel-mac-follow-up). |
| Native desktop / Windows WSL physical checks | Pending |
| Release bootstrap | Public `v0.1.0` published; anonymous live one-liners, exact artifact/bootstrap pins and downloaded archive's Ubuntu install/recovery passed |

The platform and tool unit tests exercise normalized host metadata, support
decisions, dry-run behavior, and reuse logic. They do not install packages or
prove that every listed OS release is currently available. Current test and
host observations are in the table above; see [project status](STATUS.md).
Homebrew support tiers were checked against its official table on 2026-09-30.
Release and artifact pins are recorded in `manifests/tools.json`.
