# Project status

**Snapshot: 2026-09-30.** Terminal Kit's implementation and support documentation are in an unpublished private repository. Release `v0.1.0` and its authenticated bootstrap are not yet available; use a reviewed checkout with `./install.sh`.

Debian 12 x86_64 passed interrupted-install recovery, explicit `--with treesitter-build`, parser/LSP and agent checks, doctor, rollback, and uninstall. The optional build pins tree-sitter-cli `0.26.1` source commit `8a3dcc6155a9faae677544303b6bc0caf1aef296` (source archive SHA-256 `ca739fcb6fdb9cf2312d687332282040f088ea5c517a65ea98f980a861babc27`) and Rust `1.92.0`; locked dependencies require this newer compiler, while all Rust/Cargo data remains in Terminal Kit's managed runtime. It requests the native libclang development package and uses `cargo install --locked --jobs 2`; it does not update core libraries. Pi `0.99.1`, Hermes `0.21.5` (release tag `2026.9.24`), and OpenCode `1.18.33` were verified. A clean Debian 12 check without the opt-in is still pending; that run should report partial Tree-sitter availability honestly.

| Check | State |
| --- | --- |
| ShellCheck and Bash syntax | Passed |
| Python unit tests | Host: 76/76 passed. Container: 75 passed, 1 skipped because Ghostty is unavailable (the host Ghostty validator test passed). |
| Bats integration checks | 8 passed |
| Isolated tmux layout | Passed in container |
| Debian 12 x86_64 full install/recovery | Interrupted setup recovered; explicit Tree-sitter build, parsers/LSPs/agents, doctor, rollback, uninstall passed |
| Debian 12 clean default profile | Pending; should expose missing glibc-compatible Tree-sitter CLI as a partial result without the explicit source build |
| Ubuntu 24.04.5 | Fresh install, repeat doctor, rollback, uninstall passed |
| Fedora 44 | Fresh install, repeat doctor, rollback, uninstall passed |
| macOS CI | Not run |
| Native GUI / Windows WSL physical acceptance | Pending |
| Private release publication and bootstrap | Pending |

Next: run clean Debian 12 default-profile CI, macOS CI, then complete native desktop/Windows WSL checks from [Manual checks](MANUAL-CHECKS.md). Update this table only with observed results.
