# Manual checks

These checks require a real host session. A unit test or successful package command does not prove desktop rendering, authentication, or host integration.

## Linux headless / SSH

- [ ] On each supported distribution and architecture, run `./install.sh --dry-run`, then install as a normal user and review the receipt with `terminal-kit doctor`.
- [ ] Confirm Neovim opens, LazyVim restores from the recorded lock, and expected language tooling starts.
- [ ] Confirm Pi, Hermes, and OpenCode launch without authentication being initiated automatically; configure provider login only when wanted.
- [x] Debian 12 x86_64: explicit `treesitter-build` installed pinned CLI 0.26.1; parsers/LSPs, agents, doctor, rollback and uninstall passed after recovering from an interrupted installation. An earlier real default-profile CI run confirmed that omitting the opt-in reports partial Tree-sitter availability honestly.
- [ ] On Ubuntu 22.04 and other older-glibc hosts, exercise `treesitter-build`; verify the pinned source build uses isolated mise Rust and leaves system libraries unchanged.
- [ ] Disconnect SSH with a named tmux session attached, reconnect, and verify it remains while the machine is running. Reboot behavior is intentionally not persistence.
- [ ] Verify rollback restores a changed managed config and uninstall restores pre-existing files without removing agent data or shared packages.

## Desktop Linux and macOS

- [ ] Open Ghostty, verify the selected theme and font, paste/copy with the documented shortcuts, and check the configured tmux bindings.
- [ ] Confirm the Nerd Font renders in the terminal. Check clipboard behavior from the actual desktop session.
- [ ] On macOS, test both Apple Silicon and Intel within the documented OS floors. Confirm the pinned official Homebrew bootstrap checksum, OS-authorization/Command Line Tools path, and expected failure when unattended setup requires a person.

## Windows / WSL2

- [ ] Install in a WSL2 distribution, open the separate Terminal Kit profile from Windows Terminal, and verify shell startup and colors.
- [ ] Install the font on Windows using `windows/Install-Font.ps1`, then check glyph rendering in Windows Terminal.
- [ ] Test Ghostty through WSLg separately if desired; Linux install success alone does not prove WSLg launch.
- [ ] Confirm existing Windows Terminal defaults and profiles remain intact after fragment installation and after its rollback/uninstall path.

## Current execution record

As of 2026-09-30, Debian 12 x86_64, Ubuntu 24.04.5, Fedora 44, Arch image 20260927.0.600689, and macOS 15.7.9 Apple Silicon headless full-install/recovery checks passed. Automated and container checks are recorded in [Status](STATUS.md). Real desktop, macOS authorization, Windows Terminal/WSL font rendering, and physical disconnect/reboot acceptance remain separate.

The Arch reproduction uses `docker build -f tests/containers/Dockerfile.arch -t terminal-kit-arch-test .` followed by `docker run --rm --cap-add DAC_READ_SEARCH --cap-add PERFMON terminal-kit-arch-test`. The official base image inspected was `sha256:b21322c663be387c0ed9cbc7bbbfe18e41633ad4e7b7c77cfad45f128be20040`. Those container capabilities allow execution of Arch's native btop package; they do not validate its live monitor UI or grant host access.
