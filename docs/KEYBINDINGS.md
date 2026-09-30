# Terminal keybindings and layouts

Terminal Kit keeps the Omarchy terminal muscle memory in user-owned files while
removing Omarchy runtime paths:

- tmux prefix: Ctrl-Space; Ctrl-B remains a secondary prefix.
- h splits vertically and v splits horizontally.
- Alt-Enter and Alt-Shift-Enter split vertically and horizontally; Alt-Escape
  closes the current pane.
- Ctrl-Alt-Arrow keys move between panes; add Shift to resize the focused pane.
- c opens a window in the current directory; r renames it; x kills the current pane.
- Alt-Left and Alt-Right switch windows. Alt-Up and Alt-Down switch sessions.
- Copy mode uses vi keys: v begins a selection and y copies it.
- Ghostty maps Shift-Insert to paste, Ctrl-Insert to copy, and sends
  Shift-Enter using CSI-u for terminal applications.

Development layouts are explicit commands; starting a shell does not create or
attach to a tmux session unless `TERMINAL_KIT_AUTO_TMUX=1` is explicitly set
in the environment. terminal-kit layout tdl pi [hermes|opencode] makes
an editor pane and one or two selected agent panes. terminal-kit layout tds
[pi|hermes|opencode] makes an editor, a local refreshing git diff HEAD, a
terminal, and one selected agent pane. The diff view uses local Git and refreshes
once per second. terminal-kit layout tdlm pi [hermes|opencode] makes one tdl
window per visible child directory. terminal-kit layout tsl 4 pi tiles the
selected agent across four panes.

Session helpers are under terminal-kit session: list, new [name],
attach name, name name, and detach. Session names are limited to letters,
digits, dot, underscore, and dash.

## Neovim

The leader is **Space**, with LazyVim's which-key discovery menus. These mappings come from the pinned LazyVim setup and the adapted Omarchy config:

| Keys | Action |
| --- | --- |
| Space Space / Space f f | Find project files |
| Space s g / Space / | Search project text |
| Space f c | Find Terminal Kit configuration files |
| Space e / Space E | Neo-tree file browser at project root / current directory |
| Space , | Select a buffer |
| Shift-H / Shift-L | Previous / next buffer |
| Ctrl-H/J/K/L | Move between editor windows |
| Space - / Space \| | Split below / right |
| Space g g | Lazygit at the project root |
| Space f t / Ctrl-/ | Project terminal / focus terminal |
| Space c f | Format current file or selection |
| [d / ]d | Previous / next diagnostic |
| Space s k | Discover current keymaps |
| Space q q | Quit all windows |

Python, Bash, JSON/YAML, and JavaScript/TypeScript servers and formatters are installed explicitly. Normal editor startup does not install missing packages. Use local plugin specs to add languages, then run a deliberate kit/config install to prepare dependencies. `:Lazy update` changes the mutable user lock; kit updates preserve it. Review and refresh the repository lock separately when maintaining the baseline.

## Bash and terminal delivery

`n` opens the editor; `lazygit` and `lazydocker` open the Git and Docker TUIs. `cd` uses the Omarchy-style `zd` wrapper around zoxide and normal directory navigation. fzf provides Ctrl-R history search and Ctrl-T file selection. The prompt, completion, history, and input bindings load only for interactive shells.

Ctrl-Space can be intercepted by host input methods; use the secondary Ctrl-B prefix or change the host shortcut. macOS Option is configured as Alt in Ghostty. Desktop/global Omarchy shortcuts are omitted. Key delivery through a real terminal, SSH client, and Windows Terminal needs the checks in [MANUAL-CHECKS.md](MANUAL-CHECKS.md); isolated tmux tests verify the tmux bindings and layouts, not physical host interception.

The managed files live under ~/.config/terminal-kit. Put hand edits in
~/.config/terminal-kit/local: Bash startup uses bash.sh, tmux sources tmux.conf,
Ghostty includes ghostty.conf, Starship uses starship.toml, and Neovim loads
nvim.lua plus Lua specs from nvim/plugins/. Neovim's mutable Lazy lock is stored
at ~/.local/state/terminal-kit/nvim-lazy-lock.json.
