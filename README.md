# Terminal Kit

Terminal Kit brings a consistent shell, editor, terminal, and coding-agent setup to supported Linux, macOS, and WSL2 hosts. It manages only its own configuration and user-local tools, preserves existing files for recovery, and leaves agent authentication under your control.

## Install with one command

Run this inside Bash as your normal user on a supported machine:

```bash
bash -c 'set -e; umask 077; d=$(mktemp -d "${TMPDIR:-/tmp}/terminal-kit-entry.XXXXXXXX"); trap "rm -rf -- \"\$d\"" EXIT; curl --proto "=https" --tlsv1.2 -fsSL --connect-timeout 10 --max-time 60 --max-filesize 65536 https://raw.githubusercontent.com/dlpwaters/terminal-kit/v0.1.0/bootstrap.sh -o "$d/bootstrap.sh"; head -n 1 "$d/bootstrap.sh" | grep -qx "#!/bin/bash"; bash -n "$d/bootstrap.sh"; bash "$d/bootstrap.sh" --transport curl -- "$@"' terminal-kit
```

The repository is public; installation needs no GitHub account. The command downloads the complete Bash bootstrap into a private temporary directory, checks its script header and syntax, then downloads and verifies the pinned `v0.1.0` release before running the installer. It never executes a partially downloaded stream.

Append options after the final `terminal-kit` in that same command:

| Option | When to use it |
| --- | --- |
| `--dry-run` | Preview without installing packages or changing configuration |
| `--profile headless` | CLI tools, editor and agents on a server or SSH host |
| `--profile workstation` | Request the CLI setup plus available Ghostty/font support |
| `--with treesitter-build` | Explicit parser-tool source build on Debian 12 / Ubuntu 22.04 |
| `--with extras` | Add tealdeer, ncdu and tree |
| `--unattended` | Fail clearly if a prerequisite needs human authorization |

**Intel Mac is still a partial install.** The latest macOS 15.7.9 Intel run installed the agents and editor, but the Homebrew dependency preflight failed and left tmux/btop missing. The explicit `--with intel-build` module needs a fix and another real installation test. Its outstanding work and exact failure are saved in [the Intel handoff checklist](docs/STATUS.md#intel-mac-follow-up). Apple Silicon headless acceptance passed. Desktop rendering and Windows/WSL remain manual checks.

For a command pinned to an immutable source commit and independently recorded archive digest, use [INSTALL-PIN.md](docs/INSTALL-PIN.md).

### Install from a checkout

To inspect or customize the code first:

```bash
git clone https://github.com/dlpwaters/terminal-kit.git
cd terminal-kit
bash install.sh --dry-run
bash install.sh
```

You can rerun `bash install.sh` after an interrupted or partial installation. Compatible tools are reused, completed downloads are cached, and owned configuration is checked before replacement. Review the receipt: installed, reused, skipped, unsupported and failed components are reported separately. Exit `0` means no required component failed, `1` means a required component failed or installation is partial, and `2` covers unsupported hosts, invalid arguments or blocking prerequisites. Optional GUI support and pending authentication are reported separately.

**Debian 13 restart-prompt fix:** the published `v0.1.0` archive can display an apt service-restart checklist that ignores keyboard input. The `fix/debian-package-prompts` checkout preserves the terminal input expected by Debian's sudo and defers `needrestart` service restarts during kit package operations. Use that corrected checkout after the previous installer has exited; downloading `v0.1.0` again still uses the old code. See [recovery guidance](docs/TROUBLESHOOTING.md). No OS upgrade or terminal replacement is required for this fix.

That checkout also corrects the font archive limits and treats Pi's settings as user-owned preferences. Update an existing installation with `terminal-kit update --source /path/to/corrected-checkout --apply` to preserve its selected modules and retry the font. Existing Pi preferences remain intact.

### Prerequisites and profiles

The entry script works under stock macOS Bash 3.2 and installs/reexecutes modern Bash when needed. The CLI requires Bash 4+ and Python 3.9+. It reuses compatible runtimes and bootstraps missing prerequisites through the platform package manager; it does not replace the system Python. For a strictly read-only plan, those prerequisites must already be available.

Linux package operations need an authorized `sudo` account. On macOS, the official, pinned and checksum-verified Homebrew bootstrap may require OS authorization and Apple Command Line Tools. A new machine can therefore need an interactive terminal even though the installation starts with one command. `--unattended` requires preauthorized Linux package privileges and fails when first-run authorization cannot be completed. Do not run the entire installer with `sudo`.

| Profile | Included modules |
| --- | --- |
| `auto` (default) | Headless over SSH/no display; workstation when a display is available |
| `headless` | Core tools, runtimes, all three agents, Bash/tmux configuration, Omarchy/LazyVim Neovim |
| `workstation` | Headless modules plus Ghostty where supported and the Nerd Font |
| `minimal` | Core CLI tools and managed shell/tmux configuration; no required agents or Neovim plugin setup |

Core tools include Git, GitHub CLI, Bash completion, Neovim, tmux, fzf, ripgrep, fd, bat, eza, zoxide, Starship, Lazygit, Lazydocker, btop and jq. `minimal` still installs this core tool set. Pi, Hermes and OpenCode are actual installed CLIs in the normal profiles. Hermes is CLI-only; no gateway, scheduled job or login service is enabled.

`--with a,b` adds modules; `--modules a,b` replaces the profile's selection. Available modules are `cli,runtimes,agents,configs,nvim,ghostty,fonts,extras,python,pi,hermes,opencode,codex,claude,bash,tmux,treesitter-build,intel-build,docker`. Docker Engine requires the separate explicit action described below. Examples from a checkout:

```bash
bash install.sh --profile headless --with extras
bash install.sh --profile headless --with treesitter-build  # Debian 12 / Ubuntu 22.04
bash install.sh --profile workstation --with python
bash install.sh --modules cli,runtimes,configs,nvim,pi,opencode
bash install.sh --profile headless --unattended
```

`treesitter-build` compiles the pinned parser CLI using isolated Rust and may install libclang development headers. The incomplete Intel source-build route also uses isolated Rust for Hermes's security-pinned cryptography dependency; expect 20–90 minutes when resuming its validation. Expensive source builds are explicit. Exact supported targets, tested OS versions and per-component boundaries are in [SUPPORT.md](docs/SUPPORT.md); listing a target is not a claim that its desktop or every release has been tested.

### First run

Open a new Bash terminal (or `source ~/.bashrc` in an existing Bash session), then:

```bash
terminal-kit doctor
terminal-kit keys
terminal-kit auth pi
terminal-kit auth hermes
terminal-kit auth opencode
```

Authentication is optional during installation. Each auth command opens that agent's documented flow: Pi's `/login`, Hermes's `hermes model`, or OpenCode's `opencode auth login`. Choose your own provider/model, including OpenRouter where supported. The kit creates no shared auth file and makes no paid requests. Existing providers, credentials, sessions and user skills are preserved.

For headless/SSH hosts, the terminal emulator and font run on the client machine. Install the same CLI profile on the server and use your client terminal to connect. Bash and new tmux panes are configured independently; the account's login shell changes only through the explicit command below.

### Download trust

For reproducibility, pin the bootstrap's immutable commit URL/API reference and pass the release archive digest with `--sha256`. The release publishes `RELEASE.json` with both values. Tags and bundled checksums are convenient pins, but GitHub owners can replace them; keep an independently trusted digest for stronger verification.

`bootstrap.sh` downloads the complete archive before running it, checks its SHA-256 against the release's `SHA256SUMS` (or a separately supplied `--sha256` pin), bounds and inspects the tar archive, then executes `install.sh`. The bundled checksum and archive come from the same GitHub release, so this detects transfer or packaging mismatch but is not an independent signature. Verify the release through a separately trusted commit or digest before using it.

## Everyday commands

```text
terminal-kit doctor                 # status; credentials are never inspected
terminal-kit keys                   # keybinding and layout reference
terminal-kit auth pi|hermes|opencode
terminal-kit session list|new|attach|name|detach
terminal-kit layout tdl pi [hermes|opencode]
terminal-kit update --source PATH   # preview reviewed kit changes
terminal-kit update --source PATH --apply
terminal-kit update --tools         # preview kit-owned tool updates
terminal-kit update --tools --apply
terminal-kit rollback --list
terminal-kit rollback BACKUP_ID
terminal-kit uninstall
```

Use `terminal-kit theme NAME` to select a supported theme. Put personal edits in `~/.config/terminal-kit/local/`; see [keybindings and layouts](docs/KEYBINDINGS.md). Kit updates do not fetch new upstream configs automatically. Tool updates only replace tools Terminal Kit owns. Rollback restores managed configuration, not package versions. Uninstall restores backed-up files and removes owned config while retaining packages, runtimes, agent data, and local overrides.

Personal override files are `bash.sh`, `tmux.conf`, `ghostty.conf`, `starship.toml` and `nvim.lua` in that local directory; Neovim also loads specs from `local/nvim/plugins/`. Its editable plugin lock lives at `~/.local/state/terminal-kit/nvim-lazy-lock.json`. Put customizations there rather than editing the managed baseline.

To update kit configuration, clone or safely fast-forward your reviewed checkout, preview the changes, then apply them:

```bash
cd /path/to/terminal-kit
git status --short                  # commit or preserve your edits before pulling
git pull --ff-only
terminal-kit update --source "$PWD"
terminal-kit update --source "$PWD" --apply
```

`terminal-kit update --tools` is a separate preview/apply operation against the current manifest; it does not upgrade every system package or move the Omarchy baseline. A maintainer refreshes pinned upstream versions and configs deliberately in the repository. Before replacement, timestamped backup manifests record original files/symlinks and owned changes under `~/.local/state/terminal-kit/backups/`. Dirty managed files cause a conflict rather than silent replacement. Use `terminal-kit rollback --list` and `terminal-kit rollback BACKUP_ID` to restore a selected configuration backup, or `terminal-kit uninstall` to remove owned setup. Neither command downgrades packages or removes agent state. See [recovery guidance](docs/TROUBLESHOOTING.md) before resolving a conflict.

Ghostty and new tmux panes use modern Bash automatically. Changing the account login shell is separate: `terminal-kit login-shell` previews it; `terminal-kit login-shell --apply` registers Bash in `/etc/shells` if needed and runs `chsh`. Existing zsh/fish files are preserved. After installation, open a new Bash terminal or run `source ~/.bashrc` in an existing Bash session.

## Quick keyboard reference

- tmux prefix: **Ctrl-Space** (Ctrl-B also works); **h/v** split panes; **Alt-Enter** splits vertically; **Alt-Shift-Enter** splits horizontally; **Alt-Escape** closes a pane.
- Move panes with **Ctrl-Alt-Arrow**; add Shift to resize. **Alt-Left/Right** switches windows; **Alt-Up/Down** switches sessions.
- Ghostty copy/paste: **Ctrl-Insert** / **Shift-Insert**. **Alt-Enter** tmux splitting requires the configured Ghostty key mapping.
- `n` opens Neovim in the current directory (or passes its arguments through). `ga BRANCH` creates and enters a new worktree beside the repository; it refuses an existing branch/worktree and never deletes one.
- Neovim: **Space Space** finds files, **Space s g** searches text, **Space g g** opens Lazygit, **Space f t** opens a terminal, and **Space s k** discovers keymaps. **Ctrl-H/J/K/L** moves between editor windows.
- `tdl pi [hermes|opencode]`, `tds [agent]`, `tdlm pi [agent]`, and `tsl 4 pi` create explicit tmux layouts. Shell startup creates no tmux session by default.

Full mappings and layout details: [Keybindings and layouts](docs/KEYBINDINGS.md).

tmux sessions survive an SSH disconnect while the host remains running; a shutdown ends them. Session helpers do not provide persistence across reboot.

## Windows and Docker

On a fresh Windows machine, first enable/install WSL2, reboot if required, initialize a supported Linux distribution and create its Linux user. [windows/Bootstrap-WSL.ps1](windows/Bootstrap-WSL.ps1) guides that prerequisite stage. Run the Bash installation command inside that initialized distribution; a Bash one-liner cannot remove the Windows/reboot prerequisites. Keep projects under the WSL Linux home by default.

There is no official native Windows Ghostty build in the inspected upstream. Windows Terminal is the reliable host fallback and a separate explicit module: `terminal-kit windows-host` previews a WSL/Bash profile fragment; `terminal-kit windows-host --apply` writes that fragment while preserving existing profiles. Install the Nerd Font on Windows with [windows/Install-Font.ps1](windows/Install-Font.ps1). Linux/WSL font installation does not install a Windows font. Ghostty through WSLg needs available WSLg, a supported Linux package source and a real launch/rendering check; Windows interop/systemd are detected, not assumed.

Lazydocker is a client; it does not install Docker Engine. `terminal-kit docker` diagnoses reachability. Engine installation is an explicit opt-in with `terminal-kit docker --install-engine`; WSL and macOS use their host Docker solution instead.

## Recovery and support

Run `terminal-kit doctor` after installation. See [Troubleshooting](docs/TROUBLESHOOTING.md) for common recovery steps and [Manual checks](docs/MANUAL-CHECKS.md) for validation that needs a real desktop or host. Current test evidence and remaining work are recorded in [Status](docs/STATUS.md), including the deferred Intel build work.

Observed full CLI installation/recovery passed on Debian 12, Ubuntu 24.04.5, Fedora 44 and Arch x86_64, plus macOS 15.7.9 Apple Silicon. The host passed 88 regression tests and 8 Bats checks; release-commit CI passed all five jobs. Intel remains partial, and GUI/Windows/WSL/Linux ARM acceptance is unobserved. The release archive and both pinned installation paths are verified separately from these platform claims. Development/testing used isolated homes and disposable environments.

The Omarchy feature inventory, pinned commits, licenses, copied paths and portability decisions are in [INVENTORY.md](docs/INVENTORY.md) and [UPSTREAMS.md](docs/UPSTREAMS.md). No Omarchy desktop session, SSH/network/firewall changes or bundled agent skills are installed.
