"""Management entry point. Packages and config recovery have separate lifetimes."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from .clipboard import backend
from .hooks import hook_specs, merge_hook, strip_hook
from .platforms import detect
from .state import Conflict, State, atomic_write, fingerprint, lock, write_json

REPO = Path(__file__).resolve().parents[2]
PI_SETTINGS = ".pi/agent/settings.json"
PROFILES = {
    "minimal": ["cli", "configs"],
    "headless": ["cli", "runtimes", "agents", "configs", "nvim"],
    "workstation": ["cli", "runtimes", "agents", "configs", "nvim", "ghostty", "fonts"],
}
MODULES = set(sum(PROFILES.values(), [])) | {"extras", "docker", "python", "pi", "hermes", "opencode", "codex", "claude", "bash", "tmux", "treesitter-build", "intel-build"}


def emit(name, status, detail, required=False, **extra):
    return {"name": name, "status": status, "detail": detail, "required": required, **extra}


def read_install(home):
    path = home / ".local/state/terminal-kit/installation.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return {} if data.get("status") == "uninstalled" else data


def receipt_report(results):
    for item in results:
        print(f"{item['status']:11} {item['name']}: {item.get('detail', '')}")
    failed = [r for r in results if r.get("required") and r["status"] in ("failed", "unsupported")]
    if failed:
        print(f"Partial installation: {len(failed)} required component(s) unavailable. Rerun after remediation.", file=sys.stderr)
        return 1
    return 0


def snapshot_repo(repo, home):
    candidates = sorted(p for p in repo.rglob("*") if p.is_file() and p.name != ".complete" and not any(x in (".git", "__pycache__", ".venv", ".artifacts", ".pytest_cache") for x in p.relative_to(repo).parts))
    digest = hashlib.sha256()
    for path in candidates:
        if path.is_symlink():
            raise Conflict(f"Source checkout contains a symlink: {path}")
        digest.update(str(path.relative_to(repo)).encode())
        digest.update(path.read_bytes())
        digest.update(str(path.stat().st_mode & 0o777).encode())
    identity = digest.hexdigest()[:20]
    target = home / ".local/share/terminal-kit/releases" / identity
    if not (target / ".complete").exists():
        target.mkdir(parents=True, exist_ok=True)
        for path in candidates:
            dest = target / path.relative_to(repo)
            atomic_write(dest, path.read_bytes(), path.stat().st_mode & 0o777)
        atomic_write(target / ".complete", identity.encode())
    return target


def select_modules(args, facts):
    profile = args.profile
    if profile == "auto":
        profile = "headless" if facts["ssh"] or not facts["display"] else "workstation"
    modules = list(PROFILES[profile])
    if args.modules is not None:
        modules = [x for x in args.modules.split(",") if x]
    modules += [x for x in args.with_modules.split(",") if x]
    modules = list(dict.fromkeys(modules))
    unknown = set(modules) - MODULES
    if unknown:
        raise Conflict("Unknown module(s): " + ", ".join(sorted(unknown)))
    return profile, modules


def select_bash():
    for candidate in [shutil.which("bash"), "/bin/bash"]:
        if candidate:
            check = subprocess.run([candidate, "-c", 'test "$BASH_VERSINFO" -ge 4'], capture_output=True)
            if check.returncode == 0:
                # Keep Homebrew's stable bin link across Cellar upgrades.
                return str(Path(candidate).absolute())
    raise Conflict("Modern Bash 4+ is missing; rerun install.sh after installing Bash")


def apply_configs(state, repo, facts, modules, theme="tokyo-night"):
    from .configs import build_configs
    # Pi saves its own preferences; older kit seeds must become user-owned.
    state.data["files"].pop(PI_SETTINGS, None)
    bash = select_bash()
    for relative, content, mode in build_configs(repo, state.home, bash, facts, theme):
        if "configs" not in modules and not any(m in modules for m in ("bash", "tmux", "nvim", "ghostty")):
            continue
        state.apply(relative, content, mode)
    for relative, body in hook_specs(state.home, modules):
        path = state.destination(relative)
        text = path.read_text() if path.is_file() else ""
        state.apply(relative, merge_hook(text, body).encode(), path.stat().st_mode & 0o777 if path.is_file() else 0o644, hook=True)
    if "nvim" in modules:
        nvim_entry = b'-- terminal-kit entry; original is in the backup manifest.\ndofile(vim.fn.expand("~/.config/terminal-kit/nvim/init.lua"))\n'
        state.apply(".config/nvim/init.lua", nvim_entry)
        baseline = state.home / ".config/terminal-kit/nvim/lazy-lock.json"
        mutable = state.root / "nvim-lazy-lock.json"
        if baseline.exists() and not mutable.exists():
            atomic_write(mutable, baseline.read_bytes())
    if "agents" in modules or "pi" in modules:
        path = state.home / PI_SETTINGS
        if not path.exists() and not path.is_symlink():
            path = state.destination(PI_SETTINGS)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "w") as output:
                    output.write(json.dumps({"shellPath": bash}, indent=2) + "\n")
    local = state.home / ".config/terminal-kit/local"
    local.mkdir(parents=True, exist_ok=True)
    for name, content in {"bash.sh": "# Your Bash overrides.\n", "tmux.conf": "# Your tmux overrides.\n", "ghostty.conf": "# Your Ghostty overrides.\n", "nvim.lua": "-- Your Neovim overrides.\n"}.items():
        path = local / name
        if not path.exists() and not path.is_symlink():
            with path.open("x") as out:
                out.write(content)
    return bash


def install_nvim(home):
    from .plugins import seed_plugin
    nvim = shutil.which("nvim")
    if not nvim:
        return emit("nvim-plugins", "failed", "Neovim executable is unavailable", True)
    env = dict(os.environ)
    env.pop("NVIM_APPNAME", None)
    env["TERMINAL_KIT_INSTALL"] = "1"
    env["TERMINAL_KIT_NVIM_INSTALL"] = str(REPO / "scripts/nvim-install.lua")
    tree_sitter = shutil.which("tree-sitter")
    if not tree_sitter:
        return emit("nvim-plugins", "failed", "Tree-sitter CLI is missing; on older glibc use --with treesitter-build (explicit source build)", True)
    env["TERMINAL_KIT_TREE_SITTER"] = tree_sitter
    try:
        mutable = home / ".local/state/terminal-kit/nvim-lazy-lock.json"
        seed = json.loads(mutable.read_text())
        stamp = mutable.with_name("nvim-verified.json")
        config_root = home / ".config/terminal-kit/nvim"
        def identity():
            digest = hashlib.sha256(mutable.read_bytes() + (REPO / "scripts/nvim-install.lua").read_bytes())
            for path in sorted(config_root.rglob("*.lua")):
                digest.update(path.read_bytes())
            return digest.hexdigest()
        if stamp.exists() and json.loads(stamp.read_text()).get("identity") == identity():
            check_env = {**env, "TERMINAL_KIT_NVIM_CHECK": "1"}
            check = subprocess.run([nvim, "--headless", "+lua dofile(vim.env.TERMINAL_KIT_NVIM_INSTALL)", "+qa"], env=check_env, capture_output=True, text=True, timeout=30)
            if check.returncode == 0 and "TERMINAL_KIT_NVIM_OK" in check.stdout + check.stderr:
                return emit("nvim-plugins", "reused", "Locked LazyVim, parsers and language tools verified locally; no downloads", True)
        lazy = home / ".local/share/terminal-kit/nvim/lazy/lazy.nvim"
        seed_plugin(lazy, "https://github.com/folke/lazy.nvim.git", seed["lazy.nvim"]["commit"], seed["lazy.nvim"].get("branch", "main"))
        lazyvim = lazy.parent / "LazyVim"
        seed_plugin(lazyvim, "https://github.com/LazyVim/LazyVim.git", seed["LazyVim"]["commit"], seed["LazyVim"].get("branch", "main"))
        # Lazy rewrites its lock non-atomically. Keep the user's mutable lock
        # intact even if a plugin transfer or editor process is interrupted.
        working_lock = mutable.with_name("nvim-install-lock.json")
        atomic_write(working_lock, mutable.read_bytes())
        env["TERMINAL_KIT_LOCKFILE"] = str(working_lock)
        # Synchronous restore respects the mutable user lock; no paid requests.
        result = subprocess.run([nvim, "--headless", "+Lazy! restore", "+qa"], env=env, timeout=900, capture_output=True, text=True)
        log = home / ".local/state/terminal-kit/nvim-install.log"
        atomic_write(log, (result.stdout + result.stderr).encode())
        if result.returncode or "Error detected" in result.stderr or "E5108" in result.stderr:
            return emit("nvim-plugins", "failed", f"Plugin restore failed; inspect {log}", True)
        result = subprocess.run([nvim, "--headless", "+lua dofile(vim.env.TERMINAL_KIT_NVIM_INSTALL)", "+qa"], env=env, timeout=1800, capture_output=True, text=True)
        if result.returncode or "TERMINAL_KIT_NVIM_OK" not in result.stdout + result.stderr:
            atomic_write(log, (result.stdout + result.stderr).encode())
            return emit("nvim-plugins", "failed", f"Parser/language-tool verification failed; inspect {log}", True)
        restored = json.loads(working_lock.read_text())
        if not restored or not all(len(value["commit"]) == 40 for value in restored.values()):
            raise Conflict("Plugin manager produced an invalid lockfile")
        atomic_write(mutable, working_lock.read_bytes())
        working_lock.unlink()
        write_json(stamp, {"identity": identity()})
        return emit("nvim-plugins", "installed", "Locked LazyVim, parsers, LSPs and formatters verified", True)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, Conflict) as exc:
        log = home / ".local/state/terminal-kit/nvim-install.log"
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            detail += "\n" + (exc.stderr or "")
        atomic_write(log, detail.encode())
        return emit("nvim-plugins", "failed", f"Plugin restore failed: {detail.splitlines()[0]}; inspect {log}", True)


def install(args, repo=REPO):
    home = Path.home()
    facts = detect()
    profile, modules = select_modules(args, facts)
    if args.profile == "headless" or facts["ssh"]:
        facts["display"] = False
    print(f"Platform: {facts['os']} {facts['distro']} {facts['version']} {facts['arch']}; profile: {profile}")
    if not facts["supported"]:
        print(facts["reason"], file=sys.stderr)
        return 2
    if args.dry_run:
        from .tools import install_tools
        print("Read-only plan. Modules: " + ", ".join(modules))
        print("Config hooks: " + ", ".join(p for p, _ in hook_specs(home, modules)))
        receipt_report(install_tools(repo, home, facts, modules, args.unattended, True))
        return 0
    if os.geteuid() == 0:
        print("Run as the invoking user; do not run the entire installer as root.", file=sys.stderr)
        return 2
    state = State(home)
    with lock(state.root):
        state.recover()
        previous = read_install(home)
        theme = previous.get("theme", "tokyo-night")
        identity = state.begin("install")
        for relative in (".local/share/terminal-kit/current", ".local/share/terminal-kit/bin/tool", ".local/share/terminal-kit/cache/download", ".local/share/terminal-kit/tools/tool", ".local/share/terminal-kit/runtimes/runtime", ".local/bin/terminal-kit"):
            state.destination(relative)
        release = snapshot_repo(repo, home)
        state.apply(".local/share/terminal-kit/current", link=str(release))
        state.apply(".local/bin/terminal-kit", link=str(release / "bin/terminal-kit"))
        from .tools import install_tools
        results = install_tools(repo, home, facts, modules, args.unattended)
        try:
            bash = apply_configs(state, repo, facts, modules, theme)
            results.append(emit("configuration", "installed", f"Bash: {bash}; backup: {identity}", True))
        except (Conflict, OSError, ValueError) as exc:
            results.append(emit("configuration", "failed", str(exc), True))
            bash = None
        if "nvim" in modules and bash:
            results.append(install_nvim(home))
        if "ghostty" in modules and bash:
            from .configs import validate_ghostty_config, validate_wslg_ghostty_launch
            ghostty = shutil.which("ghostty")
            if not ghostty and facts["os"] == "macos":
                ghostty = next((str(p) for p in (home / "Applications/Ghostty.app/Contents/MacOS/ghostty", Path("/Applications/Ghostty.app/Contents/MacOS/ghostty")) if p.is_file()), None)
            if ghostty:
                configuration = home / ".config/terminal-kit/ghostty.conf"
                checked = validate_ghostty_config(configuration.read_bytes(), ghostty)
                results.append(emit("ghostty-config", "installed" if checked["status"] == "valid" else "failed", "Official config validator passed" if checked["status"] == "valid" else "Ghostty config validation failed; inspect with ghostty +validate-config"))
                if facts["wsl"]:
                    launched = validate_wslg_ghostty_launch(configuration, facts, ghostty)
                    results.append(emit("wslg-launch", "installed" if launched["status"] == "started" else "unsupported", "Ghostty process launch passed; visible window/key delivery still need host acceptance" if launched["status"] == "started" else "WSLg launch unavailable or failed; use terminal-kit windows-host"))
        if "agents" in modules or any(x in modules for x in ("pi", "hermes", "opencode")):
            results.append(emit("authentication", "skipped", "Pending your provider choice: terminal-kit auth pi|hermes|opencode"))
        ownership = previous.get("tool_ownership", {})
        for result in results:
            if result.get("ownership"):
                ownership.setdefault(result["name"], result["ownership"])
        write_json(state.root / "installation.json", {"profile": profile, "modules": modules, "platform": facts, "bash": bash, "theme": theme, "results": results, "tool_ownership": ownership, "backup": identity, "release": str(release)})
        state.finish()
    return receipt_report(results)


def doctor(args):
    home = Path.home()
    installed = read_install(home)
    if not installed:
        print(json.dumps({"error": "No installation receipt"}) if args.json else "No terminal-kit install receipt; run install.sh first.")
        return 1
    from .checks import live_checks
    checks = live_checks(home, installed, REPO)
    state = State(home)
    for relative, entry in state.data["files"].items():
        if relative == PI_SETTINGS:
            continue  # Legacy ownership; JSON syntax is checked below.
        path = state.destination(relative)
        if entry["hook"]:
            pattern = r"(?ms)^# >>> terminal-kit managed include >>>\n.*?^# <<< terminal-kit managed include <<<\n?"
            blocks = re.findall(pattern, path.read_text() if path.is_file() else "")
            if blocks != [entry.get("block")]:
                checks.append(emit(relative, "failed", "Managed startup include is missing, edited or duplicated", True))
        elif fingerprint(path) != entry["installed"]:
            checks.append(emit(relative, "failed", "Managed file edited; use local overrides before updating", True))
    bash = installed.get("bash")
    if bash:
        for path in [home / ".config/terminal-kit/bash/env", home / ".config/terminal-kit/bash/rc"]:
            if path.exists() and subprocess.run([bash, "-n", str(path)], capture_output=True).returncode:
                checks.append(emit("Bash syntax", "failed", str(path), True))
    for path in [home / ".pi/agent/settings.json", home / ".config/opencode/opencode.json"]:
        if path.is_file() and path.suffix == ".json":
            try:
                json.loads(path.read_text())
            except (ValueError, OSError):
                checks.append(emit("JSON syntax", "failed", path.name, True))
    failed = any(r.get("required") and r["status"] in ("failed", "unsupported") for r in checks)
    if args.json:
        print(json.dumps({"platform": detect(), "checks": checks, "clipboard": backend(), "authentication": "pending or user-managed; credentials not inspected"}, indent=2))
        return 1 if failed else 0
    for check in checks:
        print(f"{check['status']:11} {check['name']}: {check.get('version') or check['detail']}")
    print(f"Clipboard: {backend()}; display: {detect()['display']}; SSH: {detect()['ssh']}")
    print("Authentication: pending or user-managed; credentials are never inspected. Run terminal-kit auth <agent>.")
    print("Docker: existing client available" if shutil.which("docker") else "Docker: unavailable; Lazydocker does not install a daemon")
    return 1 if failed else 0


def auth(agent):
    commands = {"pi": ["pi"], "hermes": ["hermes", "model"], "opencode": ["opencode", "auth", "login"], "codex": ["codex", "login"], "claude": ["claude", "auth", "login"]}
    if agent == "pi":
        print("In Pi, run /login for a supported provider, or use your provider's documented environment variable.", flush=True)
    if not shutil.which(commands[agent][0]):
        print(f"{agent} CLI is missing; install its module first.", file=sys.stderr)
        return 2
    return subprocess.call(commands[agent])


def update(args):
    installed = read_install(Path.home())
    if not installed:
        raise Conflict("No installed kit to update")
    if args.tools:
        from .tools import install_tools
        if not args.apply:
            print("Tool upgrade preview: only kit-owned tools may be upgraded; system packages stay at their package-manager versions.")
            return receipt_report(install_tools(REPO, Path.home(), detect(), installed["modules"], True, True, True))
        with lock(Path.home() / ".local/state/terminal-kit"):
            result = install_tools(REPO, Path.home(), detect(), installed["modules"], args.unattended, False, True)
            merged = {item["name"]: item for item in installed.get("results", [])}
            merged.update({item["name"]: item for item in result})
            installed["results"] = list(merged.values())
            write_json(Path.home() / ".local/state/terminal-kit/installation.json", installed)
            return receipt_report(result)
    if not args.source:
        print("Preview/update a reviewed checkout: terminal-kit update --source /path/to/terminal-kit [--apply].\nUpstream baseline refresh is a maintainer edit to manifests and vendored configs; it is never fetched automatically.")
        return 0
    source = Path(args.source).expanduser().resolve()
    if not (source / "install.sh").is_file() or not (source / "lib/terminalkit/cli.py").is_file():
        raise Conflict("Source is not a terminal-kit checkout")
    print(f"Kit update source: {source}; local overrides and plugin lock will be retained")
    if not args.apply:
        existing = Path(installed["release"])
        for path in sorted(source.rglob("*")):
            if path.is_file() and not any(p in (".git", "__pycache__", ".artifacts") for p in path.relative_to(source).parts):
                old = existing / path.relative_to(source)
                if not old.is_file() or old.read_bytes() != path.read_bytes():
                    print("changed " + str(path.relative_to(source)))
        return 0
    # New code owns its own installation. It cannot reset the source checkout.
    return subprocess.call([str(source / "install.sh"), "--modules", ",".join(installed["modules"]), *( ["--unattended"] if args.unattended else [])])


def main(argv=None):
    kit_bin = str(Path.home() / ".local/share/terminal-kit/bin")
    local_bin = str(Path.home() / ".local/bin")
    existing = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join([kit_bin, local_bin, *(p for p in existing if p not in (kit_bin, local_bin))])
    parser = argparse.ArgumentParser(prog="terminal-kit")
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("install")
    p.add_argument("--profile", choices=["auto", *PROFILES], default="auto")
    p.add_argument("--modules", help="replace default modules with comma-separated selection")
    p.add_argument("--with", dest="with_modules", default="", help="add comma-separated modules")
    p.add_argument("--unattended", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p = subs.add_parser("doctor")
    p.add_argument("--json", action="store_true")
    p = subs.add_parser("auth")
    p.add_argument("agent", choices=["pi", "hermes", "opencode", "codex", "claude"])
    p = subs.add_parser("rollback")
    p.add_argument("backup", nargs="?")
    p.add_argument("--list", action="store_true")
    subs.add_parser("uninstall")
    subs.add_parser("keys")
    p = subs.add_parser("update")
    p.add_argument("--source")
    p.add_argument("--tools", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--unattended", action="store_true")
    p = subs.add_parser("theme")
    p.add_argument("name", nargs="?", default="tokyo-night")
    p = subs.add_parser("clipboard")
    p.add_argument("action", choices=["copy", "paste"])
    p = subs.add_parser("layout")
    p.add_argument("layout_args", nargs=argparse.REMAINDER)
    p = subs.add_parser("session")
    p.add_argument("session_args", nargs=argparse.REMAINDER)
    p = subs.add_parser("login-shell")
    p.add_argument("--apply", action="store_true")
    p = subs.add_parser("windows-host")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--settings")
    p = subs.add_parser("docker")
    p.add_argument("--install-engine", action="store_true")
    p.add_argument("--unattended", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            return install(args)
        if args.command == "doctor":
            return doctor(args)
        if args.command == "auth":
            return auth(args.agent)
        if args.command == "clipboard":
            from .clipboard import main as clipboard_main
            return clipboard_main(args.action)
        if args.command in ("layout", "session"):
            from .layouts import main as layout_main
            return layout_main(args.layout_args if args.command == "layout" else ["sessions", *args.session_args])
        if args.command == "keys":
            print((REPO / "docs/KEYBINDINGS.md").read_text())
            return 0
        if args.command == "update":
            return update(args)
        if args.command == "windows-host":
            from .windows import configure
            return configure(args)
        if args.command == "docker":
            from .docker import configure as configure_docker
            return configure_docker(args)
        if args.command == "login-shell":
            bash = select_bash()
            print(f"Account login shell option: {bash}; Ghostty/tmux already select Bash independently.")
            if not args.apply:
                print("Apply with terminal-kit login-shell --apply")
                return 0
            if not shutil.which("chsh"):
                raise Conflict("chsh is unavailable; ask the account administrator")
            shells = Path("/etc/shells")
            if bash not in shells.read_text().splitlines():
                print("Bash must be registered in /etc/shells; this step requires OS authorization.", flush=True)
                sudo = shutil.which("sudo")
                if not sudo:
                    raise Conflict("Ask an administrator to register this Bash path in /etc/shells")
                subprocess.run([sudo, "tee", "-a", "/etc/shells"], input=(bash + "\n").encode(), check=True)
            return subprocess.call(["chsh", "-s", bash])
        state = State(Path.home())
        if args.command == "rollback" and (args.list or not args.backup):
            for manifest in sorted((state.root / "backups").glob("*/manifest.json")):
                txn = json.loads(manifest.read_text())
                print(f"{txn['id']} {txn['operation']} {txn['status']} ({len(txn['changes'])} paths)")
            return 0
        with lock(state.root):
            state.recover()
            if args.command == "rollback":
                state.rollback(args.backup)
                print("Configuration restored. Packages and runtimes were not downgraded.")
            elif args.command == "uninstall":
                from .windows import remove_fragment
                remove_fragment(state.home, dry_run=True)
                state.data["files"].pop(PI_SETTINGS, None)
                state.uninstall(strip_hook)
                remove_fragment(state.home)
                print("Owned configuration removed; original files restored. Shared packages, user overrides, all agent data, and runtimes retained.")
            elif args.command == "theme":
                installed = read_install(state.home)
                if not installed:
                    raise Conflict("Install the kit before selecting a theme")
                identity = state.begin("theme")
                apply_configs(state, REPO, installed["platform"], installed["modules"], args.name)
                installed["theme"] = args.name
                write_json(state.root / "installation.json", installed)
                state.finish()
                print(f"Theme {args.name} applied; backup {identity}. Reload tmux/Ghostty and restart Neovim to see it.")
        return 0
    except (Conflict, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"terminal-kit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
