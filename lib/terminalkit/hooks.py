"""Small guarded includes. Existing startup code stays in its original order."""
import re
from .state import Conflict

BEGIN = "# >>> terminal-kit managed include >>>"
END = "# <<< terminal-kit managed include <<<"


def strip_hook(text, relative=None):
    del relative
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise Conflict("Managed include was edited or duplicated; restore its markers before continuing")
    return re.sub(r"(?m)^" + re.escape(BEGIN) + r"\n.*?^" + re.escape(END) + r"\n?", "", text, flags=re.S)


def merge_hook(text, body):
    if BEGIN in text or END in text:
        text = strip_hook(text)
    block = BEGIN + "\n" + body.rstrip() + "\n" + END + "\n"
    return text + ("\n" if text and not text.endswith("\n") else "") + block


def hook_specs(home, modules):
    specs = []
    if "configs" in modules or "bash" in modules:
        env = '[ -r "$HOME/.config/terminal-kit/bash/env" ] && . "$HOME/.config/terminal-kit/bash/env"'
        rc = '[ -r "$HOME/.config/terminal-kit/bash/rc" ] && . "$HOME/.config/terminal-kit/bash/rc"'
        specs.append((".bashrc", env + "\n" + rc))
        # Bash reads the first existing login file, not all three.
        login = next((p for p in (".bash_profile", ".bash_login", ".profile") if (home / p).exists() or (home / p).is_symlink()), ".bash_profile")
        body = env + '\nif [ -n "${BASH_VERSION:-}" ] && [ -z "${_TERMINAL_KIT_RC_LOADED:-}" ]; then\n  case $- in *i*) [ -r "$HOME/.bashrc" ] && . "$HOME/.bashrc" ;; esac\nfi'
        specs.append((login, body))
    if "configs" in modules or "tmux" in modules:
        specs.append((".tmux.conf", 'source-file "~/.config/terminal-kit/tmux.conf"'))
    if "ghostty" in modules:
        specs.append((".config/ghostty/config", 'config-file = "~/.config/terminal-kit/ghostty.conf"'))
    return specs
