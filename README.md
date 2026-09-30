# Terminal Kit

Terminal Kit brings a consistent shell, editor, terminal, and coding-agent setup to supported Linux, macOS, and WSL2 hosts. It manages only its own configuration and user-local tools, preserves existing files for recovery, and leaves agent authentication under your control.

## Install

From a reviewed checkout, run:

```bash
./install.sh
```

This selects `auto`: headless over SSH or without a display, workstation when a display is available. Preview the plan with `./install.sh --dry-run`. Choose explicitly with `./install.sh --profile headless` or `--profile workstation`; `minimal` is available for a smaller CLI/config setup. `--modules a,b` replaces a profile's module set, while `--with a,b` adds modules. `--unattended` requires already-authorized package installation privileges on Linux.

The normal headless and workstation setups include the editor, shell and tmux configuration, core terminal tools, and Pi, Hermes, and OpenCode CLIs. Workstation adds Ghostty and fonts. Agent installation does not log in or send requests to a provider. Use `terminal-kit auth pi`, `terminal-kit auth hermes`, or `terminal-kit auth opencode` when you choose to configure an account. Codex and Claude clients are optional modules if already used on the host. On older glibc systems such as Debian 12, use `./install.sh --with treesitter-build` to build the pinned Tree-sitter CLI using kit-isolated Rust; this may install the native libclang development package and downloads Rust crates.

The installer needs Python 3.9+ and Bash 4+. Linux package operations use the native package manager and normal sudo authorization. On macOS, Apple’s stock Bash 3.2 can run the installer. If Homebrew is absent, the installer downloads the official Homebrew installer at a pinned commit, verifies its SHA-256, then runs it; Homebrew may request OS authorization or Command Line Tools and needs an interactive terminal. `--unattended` can fail when these steps need human authorization. Supported OS versions and platform-specific gaps are in [Support](docs/SUPPORT.md).

## One-command private installation

This repository defaults to private. On the new machine, install GitHub CLI and run `gh auth login` for an account with repository access, then run this single command inside Bash:

```bash
bash -c 'set -e; d=$(mktemp -d "${TMPDIR:-/tmp}/terminal-kit-entry.XXXXXXXX"); trap "rm -rf -- \"\$d\"" EXIT; gh api "repos/dlpwaters/terminal-kit/contents/bootstrap.sh?ref=v0.1.0" -H "Accept: application/vnd.github.raw+json" > "$d/bootstrap.sh"; bash -n "$d/bootstrap.sh"; bash "$d/bootstrap.sh" --transport gh -- "$@"' terminal-kit
```

Append installer arguments after `terminal-kit`, for example `--profile headless`, `--dry-run`, or `--with treesitter-build` on Debian 12/Ubuntu 22.04. The entry script and release archive are fully downloaded before execution. A public repository can use the same bootstrap with `--transport curl`; private GitHub authentication remains a prerequisite here.

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

Ghostty and new tmux panes use modern Bash automatically. Changing the account login shell is separate: `terminal-kit login-shell` previews it; `terminal-kit login-shell --apply` registers Bash in `/etc/shells` if needed and runs `chsh`. Existing zsh/fish files are preserved. After installation, open a new Bash terminal or run `source ~/.bashrc` in an existing Bash session.

For first-run authentication, Pi opens its CLI where `/login` selects a provider; Hermes uses its documented `hermes model` setup; OpenCode runs `opencode auth login`. Choose your own provider, including OpenRouter where supported. The kit never selects a paid model or stores a shared auth file.

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

On Windows, install a supported Linux distribution under WSL2 and install Terminal Kit inside that Linux user environment. Windows Terminal is a separate host layer: `terminal-kit windows-host` previews a profile fragment; `--apply` writes that separate fragment while preserving existing profiles. Install the Nerd Font on Windows with `windows/Install-Font.ps1`. Linux/WSL font installation does not install a Windows font, and Ghostty under WSLg needs its own live check.

Lazydocker is a client; it does not install Docker Engine. `terminal-kit docker` diagnoses reachability. Engine installation is an explicit opt-in with `terminal-kit docker --install-engine`; WSL and macOS use their host Docker solution instead.

## Recovery and support

Run `terminal-kit doctor` after installation. See [Troubleshooting](docs/TROUBLESHOOTING.md) for common recovery steps and [Manual checks](docs/MANUAL-CHECKS.md) for validation that needs a real desktop or host. Current test evidence and remaining work are recorded in [Status](docs/STATUS.md). The release bootstrap requires GitHub access. Desktop and Windows/WSL acceptance remains explicitly separate from CLI test results.
