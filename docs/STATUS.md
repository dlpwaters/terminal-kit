# Project status

Snapshot: 2026-09-30. The private repository is on GitHub at [dlpwaters/terminal-kit](https://github.com/dlpwaters/terminal-kit). Initial release packaging is awaiting final acceptance; authentication is intentionally left to the user.

The CLI implementation includes the Omarchy v4.0.4 terminal baseline and independently pinned Omarchy Neovim package, user-owned configuration/recovery, required tools and all three agent CLIs. Debian 12 needs the explicit `treesitter-build` option; Intel macOS needs `intel-build` with current upstream packages. Both use isolated Rust 1.92.0 and preserve security/system-library boundaries.

| Check | Observed state |
| --- | --- |
| ShellCheck, Bash syntax, Bats | Passed; 8 Bats checks |
| Python regression tests | 85/85 on the host; container/macOS checks skip the Ghostty validator when the app is unavailable |
| Ubuntu 24.04.5 x86_64 | Fresh/repeat install, agents, locked LazyVim/parsers/language tools, doctor, scoped tool/config updates, rollback and uninstall passed |
| Debian 12 x86_64 | Local interrupted setup recovered; clean GitHub CI with `--with treesitter-build`, repeat/doctor/rollback/uninstall passed |
| Fedora 44 x86_64 | Fresh/repeat install, agents/editor, doctor, rollback and uninstall passed |
| macOS 15.7.9 Apple Silicon | Real headless fresh/repeat install, agents/editor, doctor, rollback and uninstall passed |
| macOS 15 Intel | Regression checks passed; all agents/editor installed, including cryptography 50 from source; tmux/btop dependency build exceeded the old 30-minute bound. A revised bounded build is awaiting acceptance |
| Ghostty | Host 1.3.1 config validator passed; GUI/font/physical keyboard/clipboard checks remain manual |
| Windows/WSL and Linux ARM | Detection/config tests exist; real host installation/rendering remains unobserved |
| Release bootstrap | Publication/remote artifact acceptance pending |

CLI code acceptance is [Check](https://github.com/dlpwaters/terminal-kit/actions/workflows/check.yml); real Mac installs are [Platform acceptance](https://github.com/dlpwaters/terminal-kit/actions/workflows/workstation.yml). Desktop and Windows checks are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). No credential provisioning, paid model requests, host desktop settings, or live host services were changed during development.
