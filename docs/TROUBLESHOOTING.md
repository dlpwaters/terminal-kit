# Troubleshooting

Start with `terminal-kit doctor`. It checks the installation receipt, executable availability, managed-file edits, shell syntax, selected JSON files, and reports display, SSH, clipboard, and Docker status. It never reads provider credentials or tests authentication.

## Install stops before setup

- **Python or Bash missing:** install Python 3.9+ and Bash 4+. On macOS, the installer bootstraps Homebrew through the official pinned script when absent; its first run may need Command Line Tools, OS authorization, or a real terminal. If that step stops for a human action, complete it interactively and rerun `./install.sh`.
- **Unsupported OS or architecture:** check [Support](SUPPORT.md). The installer does not guess package names or add third-party repositories. Keep the diagnostic and use a supported host or install the required tool from its official source.
- **Package authorization failed:** rerun interactively as your normal user and approve only the native package operation. `--unattended` works only when noninteractive sudo is already authorized. Never run the entire installer as root.
- **An existing config conflicts:** inspect the named path and the backup list with `terminal-kit rollback --list`. Preserve local edits; use `~/.config/terminal-kit/local/` for customizations. Do not delete the kit state directory to force a retry.

## Neovim or plugin setup fails

The plugin lock is mutable user state at `~/.local/state/terminal-kit/nvim-lazy-lock.json`; reviewed kit updates retain it. Inspect the reported install log under `~/.local/state/terminal-kit/`, then retry the restore directly:

```bash
nvim --headless '+Lazy! restore' +qa
terminal-kit doctor
```

If the lock was intentionally changed, retain it and investigate the plugin's own error. Do not replace it with an unreviewed baseline just to make the installer green.

On Debian 12 and other older-glibc Linux hosts, the upstream Tree-sitter executable may require newer glibc than the OS supplies. Run `./install.sh --with treesitter-build` to use the pinned 0.26.1 source build with kit-isolated Rust. It requires native libclang development headers (`libclang-dev` on apt-based hosts), can download several hundred MiB of Rust crates, and may take 10–30 minutes. The build does not update system libraries.

## Agent CLI or authentication

Use `terminal-kit auth pi`, `terminal-kit auth hermes`, or `terminal-kit auth opencode` to enter the tool's interactive login flow. Pi uses `/login` inside Pi. Authentication is user-managed; `doctor` does not inspect credentials or verify provider access. If the command is missing, check the install receipt and rerun the selected agent module from a reviewed checkout.

## Ghostty, fonts, and WSL

Ghostty availability depends on a supported native package source. The installer does not add a community repository or build it from source. WSL2 is supported as a Linux environment; WSLg launch and Windows Terminal rendering are separate host checks. Install Windows Terminal fonts on Windows with `windows/Install-Font.ps1`; installing them inside WSL is not sufficient.

If clipboard reports unavailable, check `terminal-kit doctor` for the detected backend and ensure the host clipboard tool/session is present. SSH and headless sessions do not imply a desktop clipboard or GUI.

## Docker and persistence

Lazydocker is only a client. On WSL, first check Docker Desktop integration; on macOS, use a host engine such as Docker Desktop. Native Linux Engine installation is explicit and does not add your account to the privileged `docker` group. A tmux session survives a network disconnect only while its host remains running; shutdown ends it.

## Undo and update

List configuration transactions with `terminal-kit rollback --list`, then restore a selected backup using `terminal-kit rollback ID`. This does not downgrade system packages or runtimes. `terminal-kit uninstall` restores original managed files and removes kit-owned configuration while retaining shared packages, runtimes, agent data, and local overrides.

Review kit changes first with `terminal-kit update --source PATH`; apply with `--apply`. Tool updates are separately previewed with `terminal-kit update --tools` and applied with `--tools --apply`; only kit-owned tools are candidates, and system packages remain with their package manager.
