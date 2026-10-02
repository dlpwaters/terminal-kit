# Project status

Snapshot: 2026-09-30. The public repository and [v0.1.0 release](https://github.com/dlpwaters/terminal-kit/releases/tag/v0.1.0) are published under `dlpwaters/terminal-kit`. The release source remains `bacafd2d1c66b6dd35a35278d22e9bbc66dff0f9`; later main-branch commits document the handoff without replacing its artifacts. Agent authentication is intentionally left to the user.

The CLI implementation includes the Omarchy v4.0.4 terminal baseline and independently pinned Omarchy Neovim package, user-owned configuration/recovery, required tools and all three agent CLIs. Debian 12 needs the explicit `treesitter-build` option. Intel macOS's `intel-build` path remains incomplete. Both opt-ins use isolated Rust 1.92.0 and preserve security/system-library boundaries.

| Check | Observed state |
| --- | --- |
| ShellCheck, Bash syntax, Bats | Passed; 8 Bats checks |
| Python regression tests | 88/88 on the host; container/macOS checks skip the Ghostty validator when the app is unavailable |
| Ubuntu 24.04.5 x86_64 | Fresh/repeat install, agents, locked LazyVim/parsers/language tools, doctor, scoped tool/config updates, rollback and uninstall passed |
| Debian 12 x86_64 | Local interrupted setup recovered; clean GitHub CI with `--with treesitter-build`, repeat/doctor/rollback/uninstall passed |
| Fedora 44 x86_64 | Fresh/repeat install, agents/editor, doctor, rollback and uninstall passed |
| Arch x86_64, image 20260927.0.600689 | Fresh/repeat install, agents/editor, doctor, rollback and uninstall passed; container allowed the official btop file capabilities |
| macOS 15.7.9 Apple Silicon | Real headless fresh/repeat install, agents/editor, doctor, rollback and uninstall passed |
| macOS 15.7.9 Intel | Regression checks passed; all agents/editor installed, including cryptography 50 from source. Latest real full-install attempt failed in the Homebrew outdated-dependency preflight, leaving tmux/btop unavailable; exit 1 correctly reported a partial install |
| Ghostty | Host 1.3.1 config validator passed; GUI/font/physical keyboard/clipboard checks remain manual |
| Windows/WSL and Linux ARM | Detection/config tests exist; real host installation/rendering remains unobserved |
| Release bootstrap | Actual published bootstrap bytes/archive/pins verified; anonymous convenient and immutable/checksum one-liners passed read-only live runs; downloaded artifact install/repeat/doctor/rollback/uninstall passed on isolated Ubuntu 24.04.5 |

All five jobs in the [release commit's Check run](https://github.com/dlpwaters/terminal-kit/actions/runs/36772940463) passed. [Platform acceptance](https://github.com/dlpwaters/terminal-kit/actions/runs/36772940262) completed: Apple Silicon passed, Intel failed. Desktop and Windows checks are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). No credential provisioning, paid model requests, host desktop settings, or live host services were changed during development.

## Debian 13 interactive package prompts

The `fix/debian-package-prompts` branch corrects a reproduced input failure in the published `v0.1.0` installer. Reopening `/dev/tty` for sudo caused Debian 13's checklist to draw while ignoring Tab/Enter and echoing the keys. Native package operations now inherit existing terminal input, or open the real terminal device when stdin is redirected. Apt operations, including the Python bootstrap, also defer `needrestart` service restarts for that operation.

- The unchanged release input path fails the actual needrestart/debconf checklist test on Debian 13 with sudo `1.9.16p2-3+deb13u2` and needrestart `3.11-1`; the corrected path passes.
- `scripts/check.sh` passes in Debian 12 and 13: 91 Python tests (the unavailable Ghostty validator is skipped), eight Bats checks, shell syntax, ShellCheck and runtime/credential-pattern audit.
- Four real sudo tests pass on both versions: the needrestart/debconf checklist, direct whiptail checklist, redirected-stdin fallback, and an explicit list-only mode override despite caller automatic mode. No test calls a service restart.
- Fresh/repeat headless installation, agent/editor checks, doctor, rollback and uninstall passed on Debian 12, Debian 13 and Ubuntu 24.04 in [GitHub CI](https://github.com/dlpwaters/terminal-kit/actions/runs/37044855757). All six jobs passed.
- The corrected source installer completed on the reported desktop. Its doctor output confirmed the core tools, all three agents, LazyVim startup and tmux configuration; it exposed the font-limit and Pi-ownership issues below. Remote reconnection remains manual.

The existing public bootstrap still downloads `v0.1.0`, which predates this fix. Use the corrected checkout only after the earlier apt/dpkg/installer processes have exited. The next release must include these changes before the pinned bootstrap can use them.

### Font and Pi preferences follow-up

The workstation font's pinned ZIP is 133,975,870 bytes and expands to 243,185,440 bytes; both exceeded the old limits. The follow-up retains the existing SHA-256 pin and bounded extraction, raising those limits to 160 MiB/300 MiB. The real archive installed into an isolated home with 96 font files and its OFL notice; Fontconfig recognized the regular Nerd Font family. Host fonts were not changed.

Pi settings are seeded once as user-owned preferences. Normal Pi edits no longer fail doctor, repeat installation or uninstall, including settings tracked by older kit installs. Invalid JSON and edits to actual kit-owned files still fail their checks. The required isolated suite passed: 96 Python tests (one unavailable Ghostty-validator skip), eight Bats checks, Bash syntax, ShellCheck and runtime/credential-pattern audit. Full local Debian 13 acceptance passed fresh/repeat installation with the real font, all four native sudo/dialog tests, doctor, agent/editor checks, rollback and uninstall while preserving edited Pi preferences. Updated GitHub CI remains pending. Debian 13 container acceptance now installs the real font; all container targets exercise edited Pi settings.

Apply the follow-up from the corrected source with `terminal-kit update --source PATH --apply`, then run `terminal-kit doctor`. Font rendering and the final doctor result on the affected desktop remain manual.

## Intel Mac follow-up

Further implementation/testing was deferred at the user's request. Start with the completed [Intel job and its log](https://github.com/dlpwaters/terminal-kit/actions/runs/36772940262/job/110083639561), using the release source above. This is a known partial installation, not accepted Intel support.

Confirmed latest failure:

```text
intel-build: brew outdated --formula --quiet <ordered dependency list>
             returned non-zero exit status 1
tmux:        brew install tmux exited with status 1
btop:        brew install --build-from-source btop exited with status 1
installer:   Partial installation: 3 required component(s) unavailable
```

`lib/terminalkit/tools.py`, function `_prepare_intel_builds`, calls `subprocess.check_output` for `brew outdated` before its ordered source-build loop. The nonzero status aborts that preflight. Subsequent normal installs encounter unavailable Intel bottles (tmux and bmake in this run). Pi 0.99.1, OpenCode 1.18.33, Hermes, the Bash configuration, locked LazyVim, parsers, language servers and formatters did install; the overall receipt correctly exited 1.

Earlier attempts hit a 30-minute build timeout and then outdated dependency/bottle failures. The current implementation already orders dependencies, limits targeted upgrades, bounds the native build phase and stops compiler child processes on interruption. Do not restart those approaches from scratch.

- [ ] Inspect Homebrew's documented `outdated` return-code behavior on Intel, capture stdout/stderr safely, and fix the preflight to distinguish outdated formulas from an actual query failure. Add a regression test for the observed nonzero/result combination before rerunning the expensive build.
- [ ] Verify ordered, explicit source installation of tmux/btop and their missing/outdated dependencies. Check for bmake/pkgconf availability and texinfo post-install conflicts; avoid global Homebrew upgrades or an implicit large application build.
- [ ] Run a real macOS Intel headless install with `bash install.sh --profile headless --with intel-build` in a disposable user/home. Then verify repeat install, doctor, tmux layouts on an isolated server, clean headless Neovim, all three agent executable checks without credentials, interrupted-build resume, rollback and uninstall. A detection mock or regression job is not this acceptance test.
- [ ] On a physical Intel Mac, validate stock Bash 3.2 entry, Homebrew prefix discovery, first-run Command Line Tools/OS authorization, Ghostty startup/font/clipboard and Bash in new tmux panes. Check Ctrl-Space/Ctrl-B, Option/Alt and Shift-Enter through the actual terminal/editor/SSH path.
- [ ] Recheck current Homebrew/Ghostty supported Intel OS versions before extending claims beyond the observed 15.7.9 runner. Preserve Hermes's cryptography security pin and isolated runtime strategy.

Useful pickup commands:

```bash
git clone https://github.com/dlpwaters/terminal-kit.git
cd terminal-kit
gh run view 36772940262 --repo dlpwaters/terminal-kit --job 110083639561 --log
bash install.sh --profile headless --with intel-build --dry-run
```

Use the dry run first; the real source build can take 20–90 minutes. The GUI/WSL/Linux ARM checklist is still open in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). Agent login and OS authorization remain user actions.
