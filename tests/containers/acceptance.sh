#!/usr/bin/env bash
set -euo pipefail
./scripts/check.sh
tk_extra=()
if [ -r /etc/debian_version ] && [ "$(cut -d . -f 1 /etc/debian_version)" = 12 ]; then
  tk_extra=(--with treesitter-build)
fi
./install.sh --profile headless --unattended "${tk_extra[@]}"
export PATH="$HOME/.local/share/terminal-kit/bin:$HOME/.local/bin:$PATH"
terminal-kit doctor
for tk_agent in pi hermes opencode; do
  "$tk_agent" --version
done
test ! -e "$HOME/.hermes/gateway.pid"
test ! -e "$HOME/.config/systemd/user/hermes-gateway.service"
./install.sh --profile headless --unattended "${tk_extra[@]}"
bash --noprofile --norc -c '. "$HOME/.bashrc"; test -n "$(command -v pi)"'
TERMINAL_KIT_BASH_TEST=1 bash -lic '[[ $BASH_VERSINFO -ge 4 ]] && [[ $(type -t tdl) == function ]]' < /dev/null
nvim --headless '+lua assert(vim.g.mapleader == " "); assert(require("lazy.core.config").plugins.LazyVim)' +qa
tk_backup=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".local/state/terminal-kit/installation.json").read_text())["backup"])')
terminal-kit rollback "$tk_backup"
terminal-kit uninstall
test ! -e "$HOME/.local/bin/terminal-kit"
test -d "$HOME/.hermes"
printf 'Disposable acceptance passed: '
cat /etc/os-release
