#!/usr/bin/env bash
set -euo pipefail
tk_failure_report() {
  tk_status=$?
  if [ "$tk_status" -ne 0 ]; then
    for tk_log in "$HOME/.local/state/terminal-kit/nvim-install.log" "$HOME/.local/state/nvim/mason.log"; do
      if [ -f "$tk_log" ]; then
        printf '\nInstallation diagnostic: %s\n' "$tk_log"
        cat "$tk_log"
      fi
    done
  fi
  exit "$tk_status"
}
trap tk_failure_report EXIT
./scripts/check.sh
python3 tests/containers/native_prompts.py
tk_extra=()
if [ -r /etc/debian_version ] && [ "$(cut -d . -f 1 /etc/debian_version)" = 12 ]; then
  tk_extra=(--with treesitter-build)
elif [ -r /etc/debian_version ] && [ "$(cut -d . -f 1 /etc/debian_version)" = 13 ]; then
  tk_extra=(--with fonts)
fi
./install.sh --profile headless --unattended "${tk_extra[@]}"
export PATH="$HOME/.local/share/terminal-kit/bin:$HOME/.local/bin:$PATH"
# Pi normally saves these preferences after startup or a theme change.
python3 -c 'import json,pathlib; p=pathlib.Path.home()/".pi/agent/settings.json"; s=json.loads(p.read_text()); s["theme"]="dark"; p.write_text(json.dumps(s)+"\n")'
if [ -r /etc/debian_version ] && [ "$(cut -d . -f 1 /etc/debian_version)" = 13 ]; then
  fc-scan --format='%{family}' "$HOME/.local/share/fonts/terminal-kit/JetBrainsMonoNerdFont-Regular.ttf" | grep -q 'JetBrainsMono Nerd Font'
fi
terminal-kit doctor
for tk_agent in pi hermes opencode; do
  "$tk_agent" --version
done
test ! -e "$HOME/.hermes/gateway.pid"
test ! -e "$HOME/.config/systemd/user/hermes-gateway.service"
./install.sh --profile headless --unattended "${tk_extra[@]}"
python3 -c 'import json,pathlib; assert json.loads((pathlib.Path.home()/".pi/agent/settings.json").read_text())["theme"]=="dark"'
bash --noprofile --norc -c '. "$HOME/.bashrc"; test -n "$(command -v pi)"'
TERMINAL_KIT_BASH_TEST=1 bash -lic '[[ $BASH_VERSINFO -ge 4 ]] && [[ $(type -t tdl) == function ]]' < /dev/null
nvim --headless '+lua assert(vim.g.mapleader == " "); assert(require("lazy.core.config").plugins.LazyVim)' +qa
tk_backup=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".local/state/terminal-kit/installation.json").read_text())["backup"])')
terminal-kit rollback "$tk_backup"
terminal-kit uninstall
test ! -e "$HOME/.local/bin/terminal-kit"
test -d "$HOME/.hermes"
python3 -c 'import json,pathlib; assert json.loads((pathlib.Path.home()/".pi/agent/settings.json").read_text())["theme"]=="dark"'
printf 'Disposable acceptance passed: '
cat /etc/os-release
