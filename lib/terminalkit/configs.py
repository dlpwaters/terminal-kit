"""Build the portable, generated configuration set installed by terminal-kit."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time


_DEFAULTS = {
    "accent": "#7aa2f7",
    "selection": "#292e42",
    "muted": "#414868",
    "background": "#1a1b26",
    "dark_background": "#13141c",
    "darker_background": "#0e0e14",
    "lighter_background": "#24283b",
    "foreground": "#a9b1d6",
    "dark_foreground": "#565f89",
    "light_foreground": "#b4bee6",
    "bright_foreground": "#c0caf5",
    "cursor": "#c0caf5",
    "red": "#f7768e",
    "yellow": "#e0af68",
    "orange": "#eb927b",
    "green": "#9ece6a",
    "cyan": "#449dab",
    "blue": "#7aa2f7",
    "magenta": "#ad8ee6",
    "brown": "#75493d",
    "bright_red": "#ff7a93",
    "bright_yellow": "#ff9e64",
    "bright_green": "#b9f27c",
    "bright_cyan": "#0db9d7",
    "bright_blue": "#7da6ff",
    "bright_magenta": "#bb9af7",
}


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _render(path: Path, values: dict[str, str]) -> bytes:
    content = path.read_text(encoding="utf-8")
    for key, value in values.items():
        content = content.replace(f"@{key.upper()}@", value).replace(f"@{key}@", value)
    return content.encode()


def _safe_ghostty_word(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("Bash path cannot contain a newline")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _bash_completion_file(platform: dict) -> str:
    candidates: list[Path] = []
    if platform.get("os") == "macos":
        brew = shutil.which("brew")
        if brew:
            for formula in ("bash-completion@2", "bash-completion"):
                try:
                    result = subprocess.run([brew, "--prefix", formula], capture_output=True, text=True, timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if result.returncode == 0 and result.stdout.strip():
                    prefix = Path(result.stdout.strip())
                    candidates.extend((
                        prefix / "etc/profile.d/bash_completion.sh",
                        prefix / "etc/bash_completion",
                        prefix / "share/bash-completion/bash_completion",
                    ))
    candidates.append(Path("/usr/share/bash-completion/bash_completion"))
    return str(next((path for path in candidates if path.is_file()), ""))


def validate_ghostty_config(content: bytes, ghostty: str | None = None, timeout: float = 12.0) -> dict:
    """Validate rendered Ghostty bytes without reading or changing real user config."""
    executable = ghostty or shutil.which("ghostty")
    if not executable:
        return {"status": "unsupported", "detail": "Ghostty executable is unavailable"}
    with tempfile.TemporaryDirectory(prefix="terminal-kit-ghostty-validate-") as temporary:
        root = Path(temporary)
        config = root / "ghostty.conf"
        config.write_bytes(content)
        env = dict(__import__("os").environ)
        env.update({"HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"), "XDG_STATE_HOME": str(root / "state")})
        try:
            result = subprocess.run(
                [executable, "+validate-config", f"--config-file={config}"],
                capture_output=True, text=True, timeout=timeout, env=env, check=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "detail": f"Ghostty config validation exceeded {timeout:g}s"}
        except OSError as exc:
            return {"status": "unsupported", "detail": str(exc)}
        return {
            "status": "valid" if result.returncode == 0 else "invalid",
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }


def validate_wslg_ghostty_launch(
    config: Path,
    platform: dict,
    ghostty: str | None = None,
    observe_seconds: float = 2.0,
    stop_timeout: float = 3.0,
) -> dict:
    """Launch a bounded WSLg Ghostty probe, then report actual process evidence.

    This proves that Ghostty started and remained alive for an observation
    window; it cannot prove that Windows displayed a usable window.
    """
    if platform.get("os") != "linux" or platform.get("wsl") != 2 or not platform.get("display"):
        return {"status": "unsupported", "detail": "WSLg requires Linux under WSL2 with a detected display"}
    if not os.environ.get("WAYLAND_DISPLAY"):
        return {"status": "unsupported", "detail": "WSLg Wayland display is unavailable in this process"}
    executable = ghostty or shutil.which("ghostty")
    if not executable:
        return {"status": "unsupported", "detail": "Ghostty executable is unavailable"}
    config = Path(config)
    if not config.is_file():
        return {"status": "unsupported", "detail": f"Rendered Ghostty config is missing: {config}"}

    child_home = tempfile.TemporaryDirectory(prefix="terminal-kit-wslg-probe-")
    root = Path(child_home.name)
    env = dict(os.environ)
    env.update({"HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"), "XDG_STATE_HOME": str(root / "state")})
    log_path = root / "ghostty.log"
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [executable, f"--config-file={config}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                env=env, start_new_session=True,
            )
            deadline = time.monotonic() + max(0.0, observe_seconds)
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=max(0.1, stop_timeout))
                    cleanup = "terminated"
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait()
                    cleanup = "killed-after-timeout"
                status = "started"
                returncode = None
            else:
                cleanup = "already-exited"
                status = "exited"
                returncode = process.returncode
            log.flush()
        stderr = log_path.read_bytes()[:4000].decode(errors="replace").strip()
        return {"status": status, "returncode": returncode, "pid": process.pid, "alive_seconds": max(0.0, observe_seconds) if status == "started" else 0, "cleanup": cleanup, "stderr": stderr}
    except OSError as exc:
        return {"status": "launch-failed", "detail": str(exc)}
    finally:
        child_home.cleanup()


def build_configs(
    repo: Path,
    home: Path,
    bash: str,
    platform: dict,
    theme: str = "tokyo-night",
) -> list[tuple[str, bytes, int]]:
    """Return generated files as HOME-relative targets, bytes, and permission bits.

    The managed baseline is separated from hand-edited files below
    ~/.config/terminal-kit/local. The bundled Neovim lockfile is the immutable
    seed; the installer should seed the mutable state lock only when absent.
    """
    repo = Path(repo)
    home = Path(home)
    if not bash or "\n" in bash or "\r" in bash:
        raise ValueError("Bash must be a non-empty executable path")

    theme = theme.strip().lower().replace("_", "-")
    palettes = json.loads((repo / "configs/themes.json").read_text(encoding="utf-8"))
    if theme not in palettes:
        raise ValueError(f"Unknown theme {theme!r}; available themes are: {', '.join(sorted(palettes))}")
    colors = dict(_DEFAULTS)
    colors.update(palettes[theme])
    colors.setdefault("selection_foreground", colors["foreground"])
    colors.setdefault("selection_background", colors["selection"])

    base = repo / "configs"
    files: list[tuple[str, bytes, int]] = []

    def add(target: str, source: str, mode: int = 0o644) -> None:
        files.append((target, _read(base / source), mode))

    for name in ("rc", "aliases", "inputrc"):
        add(f".config/terminal-kit/bash/{name}", f"bash/{name}")
    environment = _read(base / "bash/env")
    environment += ("\n# Terminal applications inherit the selected execution shell.\nexport SHELL=" + shlex.quote(bash) + "\n").encode()
    brew = shutil.which("brew") if platform.get("os") == "macos" else None
    if brew:
        prefix = subprocess.check_output([brew, "--prefix"], text=True, timeout=10).strip()
        if not prefix.startswith("/") or "\n" in prefix:
            raise ValueError("Homebrew returned an invalid prefix")
        paths = " ".join(shlex.quote(str(Path(prefix) / part)) for part in ("bin", "sbin"))
        environment += ("\n# GUI applications may start without Homebrew in PATH.\nfor _tk_brew_path in " + paths + '; do\n  case ":$PATH:" in *":$_tk_brew_path:"*) ;; *) PATH="$PATH:$_tk_brew_path" ;; esac\ndone\nexport PATH\nunset _tk_brew_path\n').encode()
    files.append((".config/terminal-kit/bash/env", environment, 0o644))
    completion_values = {"bash_completion_file": shlex.quote(_bash_completion_file(platform))}
    files.append((
        ".config/terminal-kit/bash/completions",
        _render(base / "bash/completions", completion_values),
        0o644,
    ))

    ghostty = _render(base / "ghostty.conf.tmpl", {
        **{key: value for key, value in colors.items()},
        "bash_command": _safe_ghostty_word(f"{shlex.quote(bash)} --login --interactive"),
    })
    files.append((".config/terminal-kit/ghostty.conf", ghostty, 0o644))

    tmux_values = {
        **{key: value for key, value in colors.items()},
        "bash_word": shlex.quote(bash),
    }
    tmux_template = (base / "tmux.conf.tmpl").read_text(encoding="utf-8")
    for key, value in tmux_values.items():
        tmux_template = tmux_template.replace(f"@{key.upper()}@", value)
    files.append((".config/terminal-kit/tmux.conf", tmux_template.encode(), 0o644))
    prompt = (base / "starship.toml").read_text()
    for color in ("blue", "green", "red", "yellow"):
        prompt = prompt.replace("bold " + color, "bold " + colors[color]).replace('"' + color + '"', '"' + colors[color] + '"')
    prompt = prompt.replace("bold purple", "bold " + colors["magenta"])
    files.append((".config/terminal-kit/starship.toml", prompt.encode(), 0o644))
    tic = shutil.which("tic")
    if not tic:
        raise ValueError("tic is missing; install the native ncurses tools to compile user terminfo")
    with tempfile.TemporaryDirectory(prefix="terminal-kit-terminfo-") as temporary:
        target = Path(temporary)
        for description in sorted((base / "terminfo").glob("*.terminfo")):
            subprocess.run([tic, "-x", "-o", str(target), str(description)], check=True, capture_output=True, timeout=10)
        for compiled in target.rglob("*"):
            if compiled.is_file():
                files.append((".terminfo/" + compiled.relative_to(target).as_posix(), compiled.read_bytes(), 0o644))

    for source in sorted((base / "nvim").rglob("*")):
        if not source.is_file() or source.name == "theme.lua.tmpl":
            continue
        relative = source.relative_to(base / "nvim").as_posix()
        target = f".config/terminal-kit/nvim/{relative}"
        files.append((target, source.read_bytes(), 0o644))

    nvim_theme = _render(base / "nvim/lua/plugins/theme.lua.tmpl", colors)
    files.append((".config/terminal-kit/nvim/lua/plugins/theme.lua", nvim_theme, 0o644))
    return files
