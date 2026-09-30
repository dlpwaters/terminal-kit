"""Portable tmux development layouts adapted from Omarchy's terminal helpers."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


AGENTS = ("pi", "hermes", "opencode")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class LayoutError(RuntimeError):
    pass


def _tmux(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    command = ["tmux"]
    socket = os.environ.get("TERMINAL_KIT_TMUX_SOCKET")
    if socket:
        command.extend(["-L", socket])
    command.extend(args)
    try:
        return subprocess.run(
            command,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as exc:
        raise LayoutError("tmux is required for development layouts") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise LayoutError(detail or "tmux command failed") from exc


def _pane() -> str:
    if not os.environ.get("TMUX"):
        raise LayoutError("Run this layout inside a tmux session")
    pane = os.environ.get("TMUX_PANE")
    if pane:
        return pane
    result = _tmux("display-message", "-p", "#{pane_id}", capture=True)
    pane = (result.stdout or "").strip()
    if not pane:
        raise LayoutError("Run this layout inside a tmux session")
    return pane


def _validate_agents(agents: list[str]) -> None:
    invalid = [agent for agent in agents if agent not in AGENTS]
    if invalid:
        raise LayoutError(f"Unsupported agent {invalid[0]!r}; choose one of: {', '.join(AGENTS)}")


def _project_name(path: Path) -> str:
    name = path.name.strip() or "terminal"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name)[:64].strip(".-") or "terminal"


def _send(pane: str, command: list[str]) -> None:
    _tmux("send-keys", "-t", pane, "-l", shlex.join(command))
    _tmux("send-keys", "-t", pane, "Enter")


def _run_agent_layout(mode: str, agents: list[str]) -> None:
    _validate_agents(agents)
    pane = _pane()
    cwd = Path.cwd()
    _tmux("rename-window", "-t", pane, _project_name(cwd))

    if mode == "tdl":
        _tmux("split-window", "-v", "-l", "15%", "-t", pane, "-c", str(cwd))
        agent_pane = _tmux(
            "split-window", "-h", "-l", "30%", "-t", pane, "-c", str(cwd),
            "-P", "-F", "#{pane_id}", capture=True,
        ).stdout.strip()
        if len(agents) == 2:
            second = _tmux(
                "split-window", "-v", "-t", agent_pane, "-c", str(cwd),
                "-P", "-F", "#{pane_id}", capture=True,
            ).stdout.strip()
            _send(second, [agents[1]])
        _send(agent_pane, [agents[0]])
        _send(pane, ["nvim", "."])
        _tmux("select-pane", "-t", pane)
        return

    if mode == "tds":
        terminal = _tmux(
            "split-window", "-v", "-l", "50%", "-t", pane, "-c", str(cwd),
            "-P", "-F", "#{pane_id}", capture=True,
        ).stdout.strip()
        diff = _tmux(
            "split-window", "-h", "-l", "50%", "-t", pane, "-c", str(cwd),
            "-P", "-F", "#{pane_id}", capture=True,
        ).stdout.strip()
        agent = _tmux(
            "split-window", "-h", "-l", "50%", "-t", terminal, "-c", str(cwd),
            "-P", "-F", "#{pane_id}", capture=True,
        ).stdout.strip()
        _send(pane, ["nvim", "."])
        _send(diff, ["terminal-kit", "layout", "diffwatch"])
        _send(agent, [agents[0] if agents else "opencode"])
        _tmux("select-pane", "-t", pane)
        return


def _tdlm(agents: list[str]) -> None:
    _validate_agents(agents)
    pane = _pane()
    cwd = Path.cwd()
    child_dirs = sorted(path for path in cwd.iterdir() if path.is_dir() and not path.name.startswith("."))
    if not child_dirs:
        raise LayoutError("No visible project directories found in the current directory")
    _tmux("rename-session", "-t", _session_for_pane(pane), _project_name(cwd))

    command = ["terminal-kit", "layout", "tdl", *agents]
    for index, path in enumerate(child_dirs):
        if index == 0:
            _send(pane, ["bash", "-lc", f"cd {shlex.quote(str(path))} && {shlex.join(command)}"])
        else:
            new_pane = _tmux(
                "new-window", "-c", str(path), "-P", "-F", "#{pane_id}", capture=True,
            ).stdout.strip()
            _send(new_pane, command)


def _tsl(count: int, agent: str) -> None:
    _validate_agents([agent])
    if count < 2 or count > 16:
        raise LayoutError("tsl pane count must be between 2 and 16")
    pane = _pane()
    cwd = Path.cwd()
    _tmux("rename-window", "-t", pane, _project_name(cwd))
    panes = [pane]
    while len(panes) < count:
        new_pane = _tmux(
            "split-window", "-h", "-t", panes[-1], "-c", str(cwd),
            "-P", "-F", "#{pane_id}", capture=True,
        ).stdout.strip()
        panes.append(new_pane)
        _tmux("select-layout", "-t", panes[0], "tiled")
    for target in panes:
        _send(target, [agent])
    _tmux("select-pane", "-t", panes[0])


def _validate_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise LayoutError("Session names may contain letters, digits, dot, underscore, and dash (1-64 characters)")
    return name


def _session_for_pane(pane: str) -> str:
    result = _tmux("display-message", "-p", "-t", pane, "#{session_id}", capture=True)
    session = (result.stdout or "").strip()
    if not session:
        raise LayoutError("Could not resolve the current tmux session")
    return session


def diffwatch(interval: float = 1.0) -> int:
    """Show a local, refreshing git diff in one tmux pane."""
    try:
        while True:
            result = subprocess.run(
                ["git", "--no-pager", "diff", "--no-ext-diff", "--color=always", "HEAD"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode not in (0, 1):
                print(result.stderr.strip() or "git diff failed", file=sys.stderr)
                return result.returncode
            sys.stdout.write("\033[H\033[2J")
            print("terminal-kit diffwatch · Ctrl-C to close")
            print(result.stdout or "(no changes)")
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="terminal-kit layout")
    sub = parser.add_subparsers(dest="layout", required=True)
    tdl = sub.add_parser("tdl", help="editor with one or two selected agents")
    tdl.add_argument("agents", nargs="+", choices=AGENTS)
    tds = sub.add_parser("tds", help="editor, terminal, local git diff, and OpenCode")
    tds.add_argument("agent", nargs="?", choices=AGENTS, default="opencode")
    tdlm = sub.add_parser("tdlm", help="one tdl window per child directory")
    tdlm.add_argument("agents", nargs="+", choices=AGENTS)
    tsl = sub.add_parser("tsl", help="tile a selected agent across panes")
    tsl.add_argument("count", type=int)
    tsl.add_argument("agent", choices=AGENTS)
    sessions = sub.add_parser("sessions", help="list tmux sessions")
    sessions_sub = sessions.add_subparsers(dest="session_action", required=True)
    sessions_sub.add_parser("list")
    new = sessions_sub.add_parser("new")
    new.add_argument("name", nargs="?")
    attach = sessions_sub.add_parser("attach")
    attach.add_argument("name")
    name = sessions_sub.add_parser("name")
    name.add_argument("name")
    sessions_sub.add_parser("detach")
    sub.add_parser("diffwatch", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.layout in ("tdl", "tds"):
            agents = getattr(args, "agents", [])
            if args.layout == "tdl" and len(agents) > 2:
                raise LayoutError("tdl accepts one or two agents")
            if args.layout == "tds":
                agents = [args.agent]
            _run_agent_layout(args.layout, agents)
        elif args.layout == "tdlm":
            if len(args.agents) > 2:
                raise LayoutError("tdlm accepts one or two agents")
            _tdlm(args.agents)
        elif args.layout == "tsl":
            _tsl(args.count, args.agent)
        elif args.layout == "diffwatch":
            return diffwatch()
        elif args.layout == "sessions":
            if args.session_action == "list":
                result = _tmux("list-sessions", check=False)
                return result.returncode
            if args.session_action == "new":
                name = _validate_name(args.name or _project_name(Path.cwd()))
                if os.environ.get("TMUX"):
                    existing = _tmux("has-session", "-t", name, check=False)
                    if existing.returncode == 0:
                        _tmux("switch-client", "-t", name)
                    else:
                        _tmux("new-session", "-d", "-s", name)
                        _tmux("switch-client", "-t", name)
                else:
                    _tmux("new-session", "-A", "-s", name)
            elif args.session_action == "attach":
                name = _validate_name(args.name)
                _tmux("switch-client" if os.environ.get("TMUX") else "attach-session", "-t", name)
            elif args.session_action == "name":
                _tmux("rename-session", "-t", _session_for_pane(_pane()), _validate_name(args.name))
            elif args.session_action == "detach":
                if not os.environ.get("TMUX"):
                    raise LayoutError("Run detach inside a tmux client")
                _tmux("detach-client")
    except LayoutError as exc:
        print(f"terminal-kit: {exc}", file=sys.stderr)
        return 2
    return 0
