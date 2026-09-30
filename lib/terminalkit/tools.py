"""Install and verify terminal-kit dependencies and optional user tools."""

from __future__ import annotations

import json
import gzip
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import sys
import platform as host_platform
from pathlib import Path

from .download import download, safe_extract, validate_script


_CHECKS = {
    "bash": ("bash", ["--version"]), "git": ("git", ["--version"]), "gh": ("gh", ["--version"]),
    "neovim": ("nvim", ["--version"]), "tmux": ("tmux", ["-V"]), "fzf": ("fzf", ["--version"]),
    "ripgrep": ("rg", ["--version"]), "fd-find": ("fdfind", ["--version"]), "fd": ("fd", ["--version"]),
    "bat": ("bat", ["--version"]), "eza": ("eza", ["--version"]), "zoxide": ("zoxide", ["--version"]),
    "fdfind": ("fdfind", ["--version"]), "batcat": ("batcat", ["--version"]),
    "starship": ("starship", ["--version"]), "lazygit": ("lazygit", ["--version"]),
    "lazydocker": ("lazydocker", ["--version"]), "btop": ("btop", ["--version"]), "jq": ("jq", ["--version"]),
    "curl": ("curl", ["--version"]), "tar": ("tar", ["--version"]), "unzip": ("unzip", ["-v"]),
    "tldr": ("tldr", ["--version"]), "ncdu": ("ncdu", ["--version"]), "tree": ("tree", ["--version"]),
    "cc": ("cc", ["--version"]), "gcc": ("gcc", ["--version"]), "c++": ("c++", ["--version"]),
    "make": ("make", ["--version"]), "pkg-config": ("pkg-config", ["--version"]), "pkgconf": ("pkgconf", ["--version"]),
    "tic": ("tic", ["-V"]), "wl-copy": ("wl-copy", ["--version"]), "xclip": ("xclip", ["-version"]),
}
_PKG_EXEC = {
    "apt": {"fd-find": ("fdfind", ["--version"]), "bat": ("batcat", ["--version"]), "build-essential": ("cc", ["--version"]), "pkg-config": ("pkg-config", ["--version"])},
    "dnf": {"fd-find": ("fd", ["--version"]), "gcc-c++": ("c++", ["--version"]), "pkgconf-pkg-config": ("pkg-config", ["--version"])},
}
_APT = "apt"


def _result(name: str, status: str, detail: str, *, required: bool = True,
            version: str | None = None, path: str | None = None,
            ownership: str | None = None) -> dict:
    return {"name": name, "status": status, "required": required,
            "detail": detail, "version": version, "path": path,
            "ownership": ownership}


def _version(command: str, args: list[str] | str | None = None, env: dict | None = None) -> tuple[str | None, str | None]:
    executable = shutil.which(command, path=(env or {}).get("PATH"))
    if not executable:
        return None, None
    try:
        argv = [args] if isinstance(args, str) else (args or ["--version"])
        proc = subprocess.run([executable, *argv], capture_output=True,
                              text=True, timeout=10, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, executable
    text = proc.stdout + "\n" + proc.stderr
    # Go CLIs can print commit hashes and build dates before their version.
    match = re.search(r"\bversion\s*[=:]\s*v?(\d+(?:\.\d+){1,3})", text, re.I)
    if not match:
        match = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})", text)
    if not match:
        match = re.search(r"(?<!\d)(\d+)", text)
    return (match.group(1) if proc.returncode == 0 and match else ("installed" if proc.returncode == 0 else None)), executable


def _at_least(actual: str | None, required: str | None) -> bool:
    if actual == "installed":
        return not required
    if not required:
        return bool(actual)
    if not actual:
        return False
    try:
        left, right = tuple(map(int, actual.split("."))), tuple(map(int, required.split(".")))
        length = max(len(left), len(right))
        return left + (0,) * (length - len(left)) >= right + (0,) * (length - len(right))
    except ValueError:
        return False


def _pkg_command(pm: str, package: str, unattended: bool) -> list[str]:
    if pm == "apt":
        return ["apt-get", "install", "-y", package]
    if pm == "dnf":
        return ["dnf", "install", "-y", package]
    if pm == "pacman":
        return ["pacman", "-S", "--needed", *( ["--noconfirm"] if unattended else []), package]
    if pm == "brew":
        # Verified release fallbacks avoid large source builds on Tier 3 Macs.
        bottle_only = package in ("neovim", "fzf", "eza", "zoxide", "starship", "lazygit", "lazydocker", "ripgrep", "fd", "bat")
        small_intel_build = sys.platform == "darwin" and host_platform.machine() == "x86_64" and package in ("bash", "bash-completion@2", "btop", "jq", "gnu-tar", "unzip", "curl")
        flags = ["--force-bottle"] if bottle_only else (["--build-from-source"] if small_intel_build else [])
        return ["brew", "install", *flags, package]
    raise ValueError(f"Unsupported package manager: {pm}")


def _run_native(command: list[str], pm: str, unattended: bool) -> subprocess.CompletedProcess:
    # Stream the native installer so sudo can prompt normally and package
    # progress is visible. Elevation is limited to the package operation.
    if pm == "brew":
        return subprocess.run(command, check=False, timeout=1800)
    if os.geteuid() == 0:
        return subprocess.CompletedProcess(command, 1, "", "Refusing native package operations as root")
    sudo = shutil.which("sudo")
    if not sudo:
        return subprocess.CompletedProcess(command, 1, "", "sudo is unavailable")
    if unattended:
        probe = subprocess.run([sudo, "-n", "true"], check=False, capture_output=True, timeout=5)
        if probe.returncode:
            return subprocess.CompletedProcess(command, 1, "", "Unattended install requires pre-authorized sudo -n")
        command = [sudo, "-n", *command]
    else:
        if not Path("/dev/tty").exists():
            return subprocess.CompletedProcess(command, 1, "", "Native package operation requires an interactive terminal")
        command = [sudo, *command]
        with open("/dev/tty", "rb", buffering=0) as tty:
            return subprocess.run(command, stdin=tty, check=False, timeout=1800)
    return subprocess.run(command, check=False, timeout=1800)


def _package_installed(package: str, pm: str) -> bool | None:
    """Ask the host package database for package-only components."""
    if package not in ("bash-completion", "bash-completion@2"):
        return None
    commands = {
        "apt": ["dpkg-query", "-W", "-f=${db:Status-Status}", package],
        "dnf": ["rpm", "-q", package],
        "pacman": ["pacman", "-Q", package],
        "brew": ["brew", "list", "--versions", package],
    }
    try:
        proc = subprocess.run(commands[pm], capture_output=True, text=True, check=False, timeout=8)
        if proc.returncode:
            return False
        if pm == "apt":
            return proc.stdout.strip() == "installed"
        return True
    except (OSError, subprocess.TimeoutExpired, KeyError):
        return False


def _manifest(repo: Path) -> dict:
    return json.loads((Path(repo) / "manifests" / "tools.json").read_text(encoding="utf-8"))


def _cmd_for(package: str, pm: str) -> tuple[str, list[str]]:
    if package in _PKG_EXEC.get(pm, {}):
        return _PKG_EXEC[pm][package]
    package = {"tealdeer": "tldr", "github-cli": "gh", "bash-completion": "bash", "bash-completion@2": "bash",
               "base-devel": "make", "build-essential": "cc", "pkgconf-pkg-config": "pkg-config", "gnu-tar": "gtar",
               "ncurses-bin": "tic", "ncurses": "tic", "wl-clipboard": "wl-copy"}.get(package, package)
    if pm == "apt" and package == "fd-find":
        return "fdfind", ["--version"]
    if pm in ("apt", "dnf") and package == "bat":
        return "batcat" if pm == "apt" else "bat", ["--version"]
    if package == "fd-find":
        return ("fd", ["--version"]) if pm != "apt" else ("fdfind", ["--version"])
    return _CHECKS.get(package, (package, ["--version"]))


def _install_package(package: str, pm: str, unattended: bool, dry_run: bool) -> tuple[str, str]:
    command = _pkg_command(pm, package, unattended)
    if dry_run:
        return "skipped", "Dry run: " + shlex.join(command)
    try:
        proc = _run_native(command, pm, unattended)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "failed", str(exc)
    if proc.returncode:
        return "failed", f"{shlex.join(command)} exited with status {proc.returncode}"
    return "installed", f"Installed with {pm}"


def _asset_key(platform: dict) -> str:
    arch = platform.get("arch")
    os_name = platform.get("os")
    if os_name == "macos":
        return f"macos-{arch}"
    return f"linux-{arch}"


def _command_name(name: str) -> str:
    return {"neovim": "nvim", "ripgrep": "rg"}.get(name, name)


def _record_fallback(results: list[dict], fallback: dict):
    if fallback["status"] in ("installed", "reused"):
        for previous in results:
            if previous["name"] == fallback["name"] and previous["status"] in ("failed", "unsupported"):
                previous["required"] = False
                previous["detail"] += "; verified upstream binary supplies the required command"
    results.append(fallback)


def _owned_link(path: Path, target: Path, owned_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            old = (path.parent / os.readlink(path)).resolve()
            if old == target.resolve():
                return
            if old.is_relative_to(owned_root.resolve()):
                path.unlink()
            else:
                raise FileExistsError(f"Refusing to replace unrelated {path}")
        else:
            raise FileExistsError(f"Refusing to replace unrelated {path}")
    path.symlink_to(target)


def _managed_path(path: str | Path | None, root: Path) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def _pin_matches(version: str | None, pin: str | None) -> bool:
    return bool(version and pin and version.lstrip("v") == pin.lstrip("v"))


def _tree_sitter_cli(manifest: dict, root: Path, bin_dir: Path, platform: dict,
                     unattended: bool, dry_run: bool, upgrade: bool,
                     build: bool = False) -> dict:
    """Ensure the pinned CLI executes on this host; do not mistake glibc errors for success."""
    spec = manifest["tree_sitter_cli"]
    minimum = spec["version"]
    environment = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
    current, current_path = _version("tree-sitter", ["--version"], environment)
    managed = _managed_path(current_path, root)
    if current and _at_least(current, minimum) and (not upgrade or not managed or _pin_matches(current, minimum)):
        return _result("tree-sitter-cli", "reused", "Using compatible executable tree-sitter CLI", version=current,
                       path=current_path, ownership="terminal-kit" if managed else "existing")
    if upgrade and current_path and not managed:
        return _result("tree-sitter-cli", "skipped", "Preserving host-managed tree-sitter during tool-only update", required=not build,
                       version=current, path=current_path, ownership="existing")
    if build:
        return _build_tree_sitter(spec, root, bin_dir, platform, dry_run, unattended)

    key = _asset_key(platform)
    asset = spec.get("assets", {}).get(key)
    native = spec.get("native_packages", {}).get(platform.get("pm"))
    if not upgrade and native and not current_path:
        if dry_run:
            return _result("tree-sitter-cli", "skipped", f"Dry run: install native {native}, then execute-version check; pinned release fallback is available")
        status, detail = _install_package(native, platform["pm"], unattended, False)
        current, current_path = _version("tree-sitter", ["--version"], environment)
        if current and _at_least(current, minimum):
            return _result("tree-sitter-cli", "installed" if status == "installed" else "reused", detail, version=current,
                           path=current_path, ownership=platform["pm"])

    if (not upgrade or managed) and asset:
        if dry_run:
            return _result("tree-sitter-cli", "skipped", f"Dry run: download pinned tree-sitter {minimum} for {key} (SHA-256 pinned); execute-version check required")
        archive = root / "cache" / Path(asset["url"]).name
        executable = root / "tools" / "tree-sitter-cli" / minimum / "tree-sitter"
        try:
            download(asset["url"], archive, asset["sha256"], max_bytes=32 * 1024 * 1024)
            executable.parent.mkdir(parents=True, exist_ok=True)
            temporary = executable.with_name("tree-sitter.new")
            with gzip.open(archive, "rb") as compressed, temporary.open("wb") as output:
                total = 0
                while block := compressed.read(64 * 1024):
                    total += len(block)
                    if total > 100 * 1024 * 1024:
                        raise ValueError("decompressed tree-sitter CLI exceeds 100 MiB")
                    output.write(block)
            temporary.chmod(0o755)
            version, _ = _version(str(temporary), ["--version"])
            if not version or not _at_least(version, minimum):
                temporary.unlink(missing_ok=True)
                detail = f"Official {minimum} release asset failed execution/version validation on {key}"
                if build:
                    return _build_tree_sitter(spec, root, bin_dir, platform, dry_run, unattended)
                return _result("tree-sitter-cli", "unsupported", detail + "; opt in with `--with treesitter-build` to compile it using an isolated Rust toolchain")
            executable.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(executable)
            _owned_link(bin_dir / "tree-sitter", executable, root)
            return _result("tree-sitter-cli", "installed", f"Installed verified tree-sitter {version} release binary", version=version,
                           path=str(executable), ownership="terminal-kit")
        except Exception as exc:
            if build:
                return _build_tree_sitter(spec, root, bin_dir, platform, dry_run, unattended)
            return _result("tree-sitter-cli", "failed", f"Pinned tree-sitter release install failed: {type(exc).__name__}: {exc}")

    explanation = "No verified compatible release asset for this platform" if not asset else "Pinned release asset could not be installed"
    return _result("tree-sitter-cli", "unsupported", explanation + "; opt in with `--with treesitter-build` to compile pinned source using an isolated Rust toolchain")


def _build_tree_sitter(spec: dict, root: Path, bin_dir: Path, platform: dict, dry_run: bool, unattended=False) -> dict:
    version = spec["version"]
    rust_version = spec["rust_version"]
    detail = (f"Build tree-sitter-cli {version} from the verified source archive using isolated Rust {rust_version}; "
              "source is under 1 MiB, Rust/crate downloads can total several hundred MiB, and compilation may take 10–30 minutes")
    if dry_run:
        return _result("tree-sitter-cli", "skipped", "Dry run: " + detail)
    print("Building pinned tree-sitter-cli from source. This opt-in downloads Rust and crates (several hundred MiB) and may take 10–30 minutes; Rust/Cargo data stays under terminal-kit.", file=sys.stderr, flush=True)
    build_package = {"apt": "libclang-dev", "dnf": "clang-devel", "pacman": "clang", "brew": "llvm"}.get(platform.get("pm"))
    if not build_package:
        return _result("tree-sitter-cli", "unsupported", "No native libclang build prerequisite for this platform")
    print(f"The source build also requires the native {build_package} development package.", file=sys.stderr, flush=True)
    status, detail = _install_package(build_package, platform["pm"], unattended, False)
    if status != "installed":
        return _result("tree-sitter-cli", "failed", "Build prerequisite unavailable: " + detail)
    repo = Path(__file__).resolve().parents[2]
    manifest = _manifest(repo)
    mise, mise_result = _ensure_mise(manifest, root, bin_dir, platform, False)
    if not mise:
        return _result("tree-sitter-cli", "failed", f"Could not prepare isolated mise: {mise_result['detail']}")
    env = _runtime_env(root, bin_dir)
    env.update({"CARGO_HOME": str(root / "runtimes" / "cargo-home"),
                "RUSTUP_HOME": str(root / "runtimes" / "rustup"),
                "CARGO_TARGET_DIR": str(root / "runtimes" / "cargo-target" / f"tree-sitter-{version}")})
    try:
        proc = subprocess.run([str(mise), "install", "--yes", f"rust@{rust_version}"], env=env, cwd=root, check=False, timeout=1800)
        if proc.returncode:
            return _result("tree-sitter-cli", "failed", f"mise install rust@{rust_version} exited {proc.returncode}")
        resolved = subprocess.run([str(mise), "where", f"rust@{rust_version}"], env=env, cwd=root, check=False, timeout=30, capture_output=True, text=True)
        if resolved.returncode or not resolved.stdout.strip():
            return _result("tree-sitter-cli", "failed", "mise did not report the isolated Rust toolchain path")
        rust_path = Path(resolved.stdout.strip()).resolve()
        rust_bin = rust_path if (rust_path / "rustc").exists() else rust_path / "bin"
        if not _managed_path(rust_bin, root):
            return _result("tree-sitter-cli", "failed", "Refusing Rust toolchain path outside terminal-kit runtime directory")
        env["PATH"] = str(rust_bin) + os.pathsep + str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["RUSTUP_TOOLCHAIN"] = rust_version
        rustc, _ = _version("rustc", ["--version"], env)
        if not rustc or not _at_least(rustc, rust_version):
            return _result("tree-sitter-cli", "failed", f"Isolated rustc did not meet {rust_version}")
        archive = root / "cache" / f"tree-sitter-{spec['commit']}.tar.gz"
        download(spec["source_url"], archive, spec["source_sha256"], max_bytes=16 * 1024 * 1024)
        with tempfile.TemporaryDirectory(prefix="tree-sitter-build-", dir=root) as temporary:
            stage = Path(temporary)
            safe_extract(archive, stage, max_bytes=32 * 1024 * 1024)
            crate = stage / f"tree-sitter-{spec['commit']}" / "crates" / "cli"
            if not (crate / "Cargo.toml").is_file():
                candidates = list(stage.glob("*/crates/cli/Cargo.toml"))
                if len(candidates) != 1:
                    return _result("tree-sitter-cli", "failed", "Verified source archive has no unique crates/cli manifest")
                crate = candidates[0].parent
            cargo = shutil.which("cargo", path=env["PATH"])
            if not cargo:
                return _result("tree-sitter-cli", "failed", "Isolated cargo executable is unavailable")
            prefix = stage / "install"
            proc = subprocess.run([cargo, "install", "--locked", "--path", str(crate), "--root", str(prefix), "--bin", "tree-sitter", "--jobs", "2"],
                                  env=env, cwd=crate, check=False, timeout=3600)
            built = prefix / "bin" / "tree-sitter"
            built_version, _ = _version(str(built), ["--version"], env) if built.is_file() else (None, None)
            if proc.returncode or not built_version or not _at_least(built_version, version):
                return _result("tree-sitter-cli", "failed", f"Pinned source build failed validation (cargo exit {proc.returncode}, version {built_version})")
            final = root / "tools" / "tree-sitter-cli" / version / "tree-sitter"
            final.parent.mkdir(parents=True, exist_ok=True)
            staged = final.with_name("tree-sitter.new")
            shutil.copyfile(built, staged)
            staged.chmod(0o755)
            staged.replace(final)
            for name in ("LICENSE", "LICENSE-MIT", "LICENSE-APACHE"):
                candidate = stage / f"tree-sitter-{spec['commit']}" / name
                if candidate.is_file():
                    license_dir = final.parent / "licenses"
                    license_dir.mkdir(exist_ok=True)
                    shutil.copyfile(candidate, license_dir / name)
            _owned_link(bin_dir / "tree-sitter", final, root)
            return _result("tree-sitter-cli", "installed", "Built pinned CLI from hash-verified source with isolated Rust", version=built_version,
                           path=str(final), ownership="terminal-kit")
    except Exception as exc:
        return _result("tree-sitter-cli", "failed", f"Pinned tree-sitter source build failed: {type(exc).__name__}: {exc}")


def _owned_wrapper(path: Path, target: Path, owned_root: Path) -> None:
    """Create a wrapper so relocatable script launchers retain their real $0."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        replaceable = False
        if path.is_symlink():
            replaceable = _managed_path(path, owned_root)
        elif path.is_file():
            try:
                contents = path.read_text(encoding="utf-8")
                replaceable = "# terminal-kit runtime wrapper" in contents and _managed_path(target, owned_root)
            except (OSError, UnicodeError):
                replaceable = False
        if not replaceable:
            raise FileExistsError(f"Refusing to replace unrelated {path}")
    content = "#!/bin/sh\n# terminal-kit runtime wrapper\nexec " + shlex.quote(str(target.resolve())) + ' "$@"\n'
    temporary = path.with_name(path.name + ".terminal-kit-new")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o755)
    os.replace(temporary, path)


def _install_asset(name: str, spec: dict, root: Path, bin_dir: Path,
                   platform: dict, dry_run: bool, upgrade: bool = False) -> dict:
    key = _asset_key(platform)
    asset = spec.get("assets", {}).get(key)
    member = spec.get("binary_member", {}).get(key)
    if not asset or not member:
        return _result(name, "unsupported", f"No pinned upstream binary for {key}", required=True)
    tool_dir = root / "tools" / name
    release_dir = tool_dir / str(spec["version"]) if name == "neovim" else tool_dir
    executable = release_dir / (Path(member).name if name != "neovim" else "bin/nvim")
    link = bin_dir / _command_name(name)
    managed_current = link.resolve() if link.is_symlink() and _managed_path(link, root) else None
    current_executable = managed_current if managed_current and managed_current.is_file() else executable
    if current_executable.is_file() and os.access(current_executable, os.X_OK):
        version, _ = _version(str(current_executable), ["--version"])
        if version:
            pin_matches = _pin_matches(version, spec.get("version"))
            if not upgrade or pin_matches:
                if dry_run:
                    return _result(name, "reused", "Dry run: managed version is already current", version=version, path=str(current_executable), ownership="terminal-kit")
                try:
                    _owned_link(link, current_executable, root)
                except FileExistsError as exc:
                    return _result(name, "failed", str(exc), version=version, path=str(current_executable), ownership="terminal-kit")
                return _result(name, "reused", "Using terminal-kit managed binary", version=version, path=str(current_executable), ownership="terminal-kit")
            if dry_run:
                return _result(name, "skipped", f"Dry run: update kit-owned {name} {version} to pinned {spec['version']}", version=version, path=str(current_executable), ownership="terminal-kit")
    if dry_run:
        return _result(name, "skipped", f"Dry run: download {asset['url']} (SHA-256 pinned)")
    archive = root / "cache" / Path(asset["url"]).name
    try:
        download(asset["url"], archive, asset["sha256"])
        with tempfile.TemporaryDirectory(prefix=f"{name}-", dir=root) as staging:
            stage = Path(staging)
            safe_extract(archive, stage)
            source = stage / member
            if not source.is_file():
                return _result(name, "failed", f"Pinned archive is missing expected file {member}")
            tool_dir.mkdir(parents=True, exist_ok=True)
            if name == "neovim":
                archive_root = stage / Path(member).parts[0]
                if not archive_root.is_dir():
                    return _result(name, "failed", f"Pinned archive is missing release directory {archive_root.name}")
                if release_dir.exists():
                    return _result(name, "failed", f"Refusing to replace existing tool tree {release_dir}")
                shutil.copytree(archive_root, release_dir, symlinks=True)
                staged_binary = release_dir / "bin/nvim"
            else:
                staged_binary = tool_dir / (Path(member).name + ".new")
                shutil.copyfile(source, staged_binary)
                staged_binary.chmod(0o755)
            version, _ = _version(str(staged_binary), ["--version"])
            if not version:
                if name == "neovim":
                    shutil.rmtree(release_dir, ignore_errors=True)
                else:
                    staged_binary.unlink(missing_ok=True)
                return _result(name, "failed", "Downloaded binary did not pass its version check")
            final = staged_binary if name == "neovim" else tool_dir / Path(member).name
            if name != "neovim":
                staged_binary.replace(final)
            for notice in stage.rglob("*"):
                if not notice.is_file() or not re.search(r"license|licence|copying|notice|ofl", notice.name, re.I):
                    continue
                license_dir = tool_dir / "licenses"
                license_dir.mkdir(parents=True, exist_ok=True)
                license_path = license_dir / notice.name
                if not license_path.exists():
                    shutil.copyfile(notice, license_path)
            _owned_link(link, final, root)
            return _result(name, "installed", f"Installed pinned {spec['version']} release", version=version, path=str(final), ownership="terminal-kit")
    except Exception as exc:
        return _result(name, "failed", f"Pinned binary install failed: {type(exc).__name__}: {exc}")


def _ensure_mise(manifest: dict, root: Path, bin_dir: Path, platform: dict, dry_run: bool, upgrade: bool = False) -> tuple[Path | None, dict]:
    spec = manifest["mise"]
    asset = spec.get("assets", {}).get(_asset_key(platform))
    if platform.get("os") == "macos":
        existing = shutil.which("mise")
        version, _ = _version("mise", ["--version"])
        if existing and version and not _managed_path(existing, root):
            return Path(existing), _result("mise", "reused", "Preserving host-managed mise", version=version, path=existing, ownership="existing")
    if not asset:
        return None, _result("mise", "unsupported", f"No pinned mise artifact for {_asset_key(platform)}", required=False)
    executable = root / "tools" / "mise" / "mise"
    if upgrade and not executable.is_file():
        return None, _result("mise", "skipped", "No kit-managed mise is installed; tool updates do not add runtime managers", required=False)
    current_version, _ = _version(str(executable), ["--version"]) if executable.is_file() else (None, None)
    already_current = _pin_matches(current_version, spec["version"])
    if executable.is_file() and current_version and (not upgrade or already_current):
        try:
            if not dry_run:
                _owned_link(bin_dir / "mise", executable, root)
        except FileExistsError as exc:
            return None, _result("mise", "failed", str(exc), version=current_version, required=False)
        return executable, _result("mise", "reused", "Using current kit-managed mise" if already_current else "Using existing kit-managed mise", version=current_version, path=str(executable), ownership="terminal-kit")
    if dry_run:
        operation = f"update kit-managed mise {current_version} to {spec['version']}" if executable.exists() else f"download {asset['url']} (SHA-256 pinned)"
        return (executable if executable.exists() else None), _result("mise", "skipped", f"Dry run: {operation}", required=False, version=current_version, path=str(executable) if executable.exists() else None, ownership="terminal-kit" if executable.exists() else None)
    try:
        archive = root / "cache" / Path(asset["url"]).name
        download(asset["url"], archive, asset["sha256"])
        stage = root / "tools" / "mise-stage"
        if stage.exists():
            shutil.rmtree(stage)
        safe_extract(archive, stage)
        src = stage / spec["binary_member"]
        if not src.is_file():
            candidates = [path for path in stage.rglob("mise") if path.is_file() and os.access(path, os.X_OK)]
            if len(candidates) == 1:
                src = candidates[0]
        if not src.is_file():
            return None, _result("mise", "failed", "Pinned archive did not contain the expected mise executable", required=False)
        executable.parent.mkdir(parents=True, exist_ok=True)
        temporary = executable.with_name("mise.new")
        shutil.copyfile(src, temporary)
        temporary.chmod(0o755)
        staged_version, _ = _version(str(temporary), ["--version"])
        if not staged_version or not _pin_matches(staged_version, spec["version"]):
            temporary.unlink(missing_ok=True)
            shutil.rmtree(stage, ignore_errors=True)
            return None, _result("mise", "failed", "Downloaded mise failed its pinned version check; existing manager was preserved", required=False, version=current_version, path=str(executable) if executable.exists() else None, ownership="terminal-kit" if executable.exists() else None)
        temporary.replace(executable)
        shutil.rmtree(stage)
    except Exception as exc:
        return None, _result("mise", "failed", f"Pinned mise install failed: {type(exc).__name__}: {exc}", required=False)
    version, _ = _version(str(executable), ["--version"])
    if not version:
        return None, _result("mise", "failed", "mise executable failed version check", required=False)
    try:
        _owned_link(bin_dir / "mise", executable, root)
    except FileExistsError as exc:
        return None, _result("mise", "failed", str(exc), version=version, required=False)
    return executable, _result("mise", "updated" if current_version else "installed", f"Installed pinned {spec['version']}", version=version, path=str(executable), ownership="terminal-kit")

def _runtime_env(root: Path, bin_dir: Path, env: dict | None = None) -> dict:
    updated = dict(os.environ if env is None else env)
    updated.update({"MISE_DATA_DIR": str(root / "runtimes"), "MISE_CONFIG_DIR": str(root / "mise-config"),
                    "MISE_AUTO_INSTALL": "0", "MISE_YES": "1"})
    updated["PATH"] = str(bin_dir) + os.pathsep + updated.get("PATH", "")
    return updated


def _prepare_intel_builds(platform: dict, requested: set, dry_run: bool) -> dict:
    if platform.get("os") != "macos" or platform.get("arch") != "x86_64":
        return _result("intel-build", "skipped", "Intel Mac source builds do not apply to this host", required=False)
    detail = "Explicit Intel build: Homebrew tmux/btop dependencies and OpenSSL; Hermes uses isolated pinned Rust. Allow 20–60 minutes and several hundred MiB."
    if dry_run:
        return _result("intel-build", "skipped", "Dry run: " + detail)
    print(detail, file=sys.stderr, flush=True)
    formulas = []
    if "cli" in requested:
        for name, args, minimum in (("tmux", ["-V"], "3.2"), ("btop", ["--version"], None)):
            if not _at_least(_version(name, args)[0], minimum):
                formulas.append(name)
    if requested & {"agents", "hermes"} and not _at_least(_version("hermes", ["--version"])[0], "0.21.5"):
        try:
            prefix = subprocess.check_output(["brew", "--prefix", "openssl@3"], text=True, timeout=15).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return _result("intel-build", "failed", f"Could not inspect native OpenSSL: {exc}")
        if not (Path(prefix) / "include/openssl/ssl.h").is_file():
            formulas.append("openssl@3")
    if not formulas:
        return _result("intel-build", "reused", "Compatible native tools and OpenSSL already exist", ownership="existing")
    try:
        deps = subprocess.check_output(["brew", "deps", "--union", "--include-build", *formulas], text=True, timeout=120).splitlines()
        packages = list(dict.fromkeys([*deps, *formulas]))
        if len(packages) > 60 or any(not re.fullmatch(r"[A-Za-z0-9@+_.-]+", item) for item in packages):
            raise ValueError("Unexpected or excessive Homebrew dependency list; refusing source builds")
        command = ["brew", "install", "--build-from-source", *packages]
        print(shlex.join(command), file=sys.stderr, flush=True)
        result = _run_native(command, "brew", True)
        return _result("intel-build", "installed" if result.returncode == 0 else "failed", f"Explicit Homebrew dependency build exited {result.returncode}", ownership="brew" if result.returncode == 0 else None)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return _result("intel-build", "failed", f"Explicit native build failed: {exc}")


def _hermes_intel_environment(manifest: dict, root: Path, bin_dir: Path, platform: dict) -> dict:
    mise, result = _ensure_mise(manifest, root, bin_dir, platform, False)
    if not mise:
        raise RuntimeError(result["detail"])
    rust = manifest["tree_sitter_cli"]["rust_version"]
    env = _runtime_env(root, bin_dir)
    env.update({"CARGO_HOME": str(root / "runtimes/cargo-home"), "RUSTUP_HOME": str(root / "runtimes/rustup"),
                "CARGO_BUILD_JOBS": "2", "RUSTUP_TOOLCHAIN": rust})
    subprocess.run([str(mise), "install", "--yes", "rust@" + rust], env=env, cwd=root, check=True, timeout=1800)
    location = Path(subprocess.check_output([str(mise), "where", "rust@" + rust], env=env, cwd=root, text=True, timeout=30).strip()).resolve()
    binary = location if (location / "rustc").is_file() else location / "bin"
    if not _managed_path(binary, root) or not (binary / "rustc").is_file():
        raise ValueError("Isolated Rust path is invalid")
    env["PATH"] = str(binary) + os.pathsep + env["PATH"]
    env["OPENSSL_DIR"] = subprocess.check_output(["brew", "--prefix", "openssl@3"], text=True, timeout=15).strip()
    if not (Path(env["OPENSSL_DIR"]) / "include/openssl/ssl.h").is_file():
        raise ValueError("OpenSSL headers are missing; rerun --with intel-build")
    return env


def _install_node(mise: Path, root: Path, bin_dir: Path, dry_run: bool, upgrade: bool = False) -> tuple[Path | None, dict]:
    data_dir = root / "runtimes"
    manifest = _manifest(Path(__file__).resolve().parents[2])
    version_target = manifest["runtime_versions"]["node"]
    minimum = manifest["runtime_versions"]["node_minimum"]
    node_bin = data_dir / "installs" / "node" / version_target / "bin"
    candidate = root / "bin" / "node"
    if not candidate.exists():
        candidate_name = shutil.which("node")
        candidate = Path(candidate_name) if candidate_name else candidate
    if candidate.is_file():
        existing_version, _ = _version(str(candidate), ["--version"])
        managed = _managed_path(candidate, root)
        runtime_bin = candidate.resolve().parent
        package_manager = runtime_bin / "npm"
        if not package_manager.is_file():
            npm_name = shutil.which("npm", path=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
            package_manager = Path(npm_name) if npm_name else package_manager
        package_env = _runtime_env(root, bin_dir)
        package_env["PATH"] = str(runtime_bin) + os.pathsep + package_env["PATH"]
        npm_version, _ = _version(str(package_manager), ["--version"], package_env) if package_manager.is_file() else (None, None)
        pinned = _pin_matches(existing_version, version_target)
        if existing_version and _at_least(existing_version.lstrip("v"), minimum) and npm_version and (not upgrade or not managed or pinned):
            if managed and not dry_run:
                try:
                    for command in ("npm", "npx"):
                        launcher = runtime_bin / command
                        if launcher.exists():
                            _owned_wrapper(bin_dir / command, launcher, root)
                except (FileExistsError, OSError) as exc:
                    return None, _result("node", "failed", f"Could not repair kit-owned runtime wrappers: {exc}", version=existing_version, path=str(candidate))
            return candidate, _result("node", "reused", "Using compatible existing Node and npm", version=existing_version.lstrip("v"), path=str(candidate), ownership="terminal-kit" if managed else "existing")
        if upgrade and not managed:
            return None, _result("node", "skipped", "Preserving host-managed Node; tool updates only change kit-owned runtimes", required=False, version=existing_version, path=str(candidate), ownership="existing")
    if upgrade and dry_run:
        return None, _result("node", "skipped", f"Dry run: mise install --yes node@{version_target}")
    env = _runtime_env(root, bin_dir)
    if not dry_run:
        try:
            proc = subprocess.run([str(mise), "install", "--yes", f"node@{version_target}"], env=env, cwd=root, check=False, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, _result("node", "failed", f"mise could not install Node {version_target}: {exc}")
        if proc.returncode:
            return None, _result("node", "failed", f"mise install node@{version_target} exited {proc.returncode}")
    else:
        return None, _result("node", "skipped", f"Dry run: mise install --yes node@{version_target}")
    node = node_bin / "node"
    version, _ = _version(str(node), ["--version"])
    if not version or not _at_least(version.lstrip("v"), minimum):
        return None, _result("node", "failed", f"Installed Node did not meet v{minimum}")
    env["PATH"] = str(node_bin) + os.pathsep + env["PATH"]
    try:
        for command in ("node", "npm", "npx"):
            target = node_bin / command
            if target.exists():
                if command == "node":
                    _owned_link(bin_dir / command, target, root)
                else:
                    _owned_wrapper(bin_dir / command, target, root)
    except (FileExistsError, OSError) as exc:
        return None, _result("node", "failed", str(exc), version=version, path=str(node))
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    npm_version, npm_path = _version(str(bin_dir / "npm"), ["--version"], env)
    if not npm_version:
        return None, _result("node", "failed", "Installed Node runtime has no working kit npm wrapper", version=version, path=npm_path or str(node))
    return node, _result("node", "installed", f"Installed Node {version_target} through mise", version=version, path=str(node), ownership="terminal-kit")


def _agent_module(agent: str, manifest: dict, home: Path, root: Path,
                  bin_dir: Path, node: Path | None, dry_run: bool,
                  upgrade: bool = False, intel_build: bool = False,
                  platform: dict | None = None) -> dict:
    spec = manifest["agents"][agent]
    required = True
    existing = shutil.which(agent, path=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    version = None
    managed = False
    if existing:
        version, _ = _version(agent, ["--version"], {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")})
        minimum = spec.get("minimum")
        managed = _managed_path(existing, root)
        pin = spec.get("cli_version") if agent == "hermes" else spec.get("version")
        if upgrade and not managed:
            return _result(agent, "reused", "Preserving host-managed agent; tool updates only change kit-owned installs", required=False, version=version, path=existing, ownership="existing")
        if version and _at_least(version.lstrip("v"), minimum) and (not upgrade or (agent != "hermes" and _pin_matches(version, pin))):
            return _result(agent, "reused", "Using compatible existing agent installation", version=version, path=existing, ownership="terminal-kit" if managed else "existing")
        if upgrade and dry_run and managed:
            return _result(agent, "skipped", f"Dry run: update kit-owned {agent} {version or 'unknown'} to pinned {pin}", version=version, path=existing, ownership="terminal-kit")
    if agent == "hermes":
        platform = platform or {"os": "macos" if sys.platform == "darwin" else "linux", "arch": host_platform.machine()}
        intel = platform.get("os") == "macos" and platform.get("arch") == "x86_64"
        if intel and not intel_build:
            return _result(agent, "unsupported", "Pinned cryptography 50 has no Intel Mac wheel. Use --with intel-build for explicit isolated Rust/OpenSSL compilation; security pins are retained.")
        if dry_run:
            action = "update" if upgrade and existing and managed else "install"
            return _result(agent, "skipped", f"Dry run: {action} from official Hermes installer pinned to {spec['commit']}; setup/browser/computer-use disabled", required=True)
        data = home / ".hermes"
        install_dir = root / "tools" / "hermes" / spec["commit"]
        marker = install_dir.parent / (spec["commit"] + ".owned")
        repository_ready = False
        if install_dir.exists():
            if not marker.is_file() or marker.read_text().strip() != spec["commit"]:
                return _result(agent, "failed", f"Unowned Hermes tree: {install_dir}; choose a separate directory", required=True)
            if (install_dir / ".git").exists():
                embedded_marker = install_dir / ".terminal-kit-owned"
                if embedded_marker.is_file() and embedded_marker.read_text(encoding="utf-8").strip() == spec["commit"]:
                    embedded_marker.unlink()
                current = subprocess.run(["git", "-C", str(install_dir), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15)
                dirty = subprocess.run(["git", "-C", str(install_dir), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, timeout=15)
                if current.returncode or current.stdout.strip() != spec["commit"] or dirty.returncode or dirty.stdout:
                    return _result(agent, "failed", "Hermes source changed; refusing to reset it. Keep local edits in a separate checkout.", required=True)
                repository_ready = True
            elif any(install_dir.iterdir()):
                return _result(agent, "failed", "Interrupted Hermes clone contains unexpected files; inspect the named kit-owned directory", required=True)
            else:
                install_dir.rmdir()
        hermes_node = data / "node" / "node" / "bin" / "node"
        if hermes_node.exists():
            node_version, _ = _version(str(hermes_node), ["--version"])
            if not node_version or not _at_least(node_version.lstrip("v"), "22.22.0"):
                return _result(agent, "failed", "Existing Hermes managed Node is incompatible; refusing to replace Hermes data", required=required, path=str(hermes_node))
        try:
            environment = _hermes_intel_environment(manifest, root, bin_dir, platform) if intel else dict(os.environ)
        except Exception as exc:
            return _result(agent, "failed", f"Intel Hermes build prerequisites failed: {exc}")
        environment["HOME"] = str(root / "hermes-user-home")
        environment["HERMES_HOME"] = str(data)
        environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
        script = root / "cache" / "hermes-install.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        common = ["--branch", spec["version"], "--commit", spec["commit"],
                  "--non-interactive", "--skip-browser", "--skip-computer-use", "--skip-setup",
                  "--dir", str(install_dir), "--hermes-home", str(data)]
        stages = ("repository", "venv", "python-deps", "node-deps", "path", "complete")
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(spec["commit"] + "\n")
            download(spec["installer_url"], script, spec["installer_sha256"], max_bytes=2 * 1024 * 1024)
            validate_script(script)
            # Avoid the broad prerequisite stage (it may install optional
            # ffmpeg), the setup wizard and the gateway stage.
            for stage_name in stages:
                if stage_name == "repository" and repository_ready:
                    continue
                proc = subprocess.run(["bash", str(script), *common, "--stage", stage_name, "--json"],
                                      env=environment, check=False, timeout=2400)
                if proc.returncode:
                    return _result(agent, "failed", f"Official Hermes {stage_name} stage exited {proc.returncode}", required=required)
            shim = Path(environment["HOME"]) / ".local/bin/hermes"
            if not shim.is_file() or not os.access(shim, os.X_OK):
                return _result(agent, "failed", "Official installer completed without an executable hermes shim", required=required)
            _owned_link(bin_dir / "hermes", shim, root)
            environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
            version, path = _version("hermes", ["--version"], environment)
            result = _result(agent, "installed" if version else "failed",
                             "Installed from official pinned Hermes installer" if version else "Hermes shim failed version check",
                             required=required, version=version, path=path, ownership="terminal-kit" if version else None)
            return result
        except Exception as exc:
            return _result(agent, "failed", f"Hermes installation failed: {type(exc).__name__}: {exc}", required=required)
    if dry_run:
        return _result(agent, "skipped", f"Dry run: install {spec['package']}@{spec['version'].lstrip('v')}", required=required)
    if node is None:
        return _result(agent, "failed", "Compatible Node/npm runtime is unavailable", required=required)
    env = _runtime_env(root, bin_dir)
    node_bin = node.parent
    env["PATH"] = str(node_bin) + os.pathsep + env["PATH"]
    prefix = root / "tools" / "npm" / agent
    npm = shutil.which("npm", path=env["PATH"])
    if not npm:
        return _result(agent, "failed", "npm disappeared from the validated runtime PATH", required=True)
    command = [npm, "install", "--global", "--prefix", str(prefix), f"{spec['package']}@{spec['version'].lstrip('v')}"]
    try:
        proc = subprocess.run(command, env=env, check=False, timeout=900)
        entry = prefix / "bin" / ("pi" if agent == "pi" else "opencode")
        if proc.returncode or not entry.exists():
            return _result(agent, "failed", f"npm install failed or did not create {entry}", required=required)
        _owned_link(bin_dir / ("opencode" if agent == "opencode" else "pi"), entry, root)
        ver, path = _version("opencode" if agent == "opencode" else "pi", ["--version"], env)
        return _result(agent, "installed" if ver else "failed", f"Installed pinned {spec['version']} npm package" if ver else "Installed executable failed version check", required=required, version=ver, path=path, ownership="terminal-kit" if ver else None)
    except Exception as exc:
        return _result(agent, "failed", f"npm installation failed: {type(exc).__name__}: {exc}", required=required)


def _ensure_extra_binary(name: str, manifest: dict, root: Path, bin_dir: Path,
                         platform: dict, unattended: bool, dry_run: bool,
                         upgrade: bool) -> dict:
    spec = manifest.get("releases", {}).get(name)
    if not spec:
        return _result(name, "unsupported", "No pinned asset for this optional tool", required=False)
    command = _command_name(name)
    args = _CHECKS.get(command, (command, ["--version"]))[1]
    minimum = manifest.get("minimum_versions", {}).get(command)
    link = bin_dir / command
    managed = link.is_symlink() and _managed_path(link, root)
    current, path = _version(command, args)
    if upgrade:
        if managed:
            return _install_asset(name, spec, root, bin_dir, platform, dry_run, upgrade=True)
        return _result(name, "reused" if current else "skipped", "Preserving host-managed optional tool during scoped update" if current else "Optional tool is absent; update --tools does not install it", required=False, version=current, path=path, ownership="existing" if current else None)
    if current and (not minimum or _at_least(current, minimum)):
        return _result(name, "reused", "Using compatible native or existing tool", required=False, version=current, path=path, ownership="existing")
    if name in manifest.get("packages", {}).get(platform.get("pm"), []):
        status, detail = _install_package(name, platform.get("pm"), unattended, dry_run)
        if status == "installed":
            current, path = _version(command, args)
            if current and (not minimum or _at_least(current, minimum)):
                return _result(name, "installed", detail, required=False, version=current, path=path, ownership=platform.get("pm"))
    asset_result = _install_asset(name, spec, root, bin_dir, platform, dry_run)
    asset_result["required"] = False
    return asset_result


def _install_font(root: Path, home: Path, platform: dict, dry_run: bool) -> dict:
    spec_path = Path(__file__).resolve().parents[2] / "manifests" / "tools.json"
    manifest = json.loads(spec_path.read_text(encoding="utf-8"))
    if platform.get("wsl"):
        return _result("font", "unsupported", "Linux font files do not configure Windows Terminal; install the font in Windows explicitly", required=False)
    asset = manifest["fonts"]["jetbrains_mono"]
    if dry_run:
        return _result("font", "skipped", f"Dry run: download {asset['url']} (SHA-256 pinned)", required=False)
    cache = root / "cache" / "JetBrainsMono.zip"
    try:
        download(asset["url"], cache, asset["sha256"], max_bytes=80 * 1024 * 1024)
        destination = (Path(home) / "Library" / "Fonts" / "Terminal Kit") if platform.get("os") == "macos" else (Path(home) / ".local" / "share" / "fonts" / "terminal-kit")
        stage = root / "font-stage"
        if stage.exists():
            shutil.rmtree(stage)
        safe_extract(cache, stage, max_bytes=150 * 1024 * 1024)
        files = [p for p in stage.rglob("*") if p.is_file() and p.suffix.lower() in (".ttf", ".otf", ".txt", ".md", ".ofl")]
        if not any(p.suffix.lower() in (".ttf", ".otf") for p in files) or not any("license" in p.name.lower() or "ofl" in p.name.lower() for p in files):
            return _result("font", "failed", "Pinned Nerd Fonts archive is missing fonts or its license notice", required=False)
        destination.mkdir(parents=True, exist_ok=True)
        for source in files:
            target = destination / source.name
            if target.exists() and target.read_bytes() != source.read_bytes():
                return _result("font", "failed", f"Refusing to replace unrelated font file {target}", required=False)
            shutil.copyfile(source, target)
        shutil.rmtree(stage)
        if platform.get("os") == "linux" and shutil.which("fc-cache"):
            subprocess.run(["fc-cache", "-f", str(destination)], check=False, timeout=60)
        return _result("font", "installed", "Installed JetBrainsMono Nerd Font with upstream license notice", required=False, path=str(destination), ownership="terminal-kit")
    except Exception as exc:
        return _result("font", "failed", f"Font install failed: {type(exc).__name__}: {exc}", required=False)


def install_tools(repo: Path, home: Path, platform: dict, modules: list[str], unattended: bool = False,
                  dry_run: bool = False, upgrade: bool = False) -> list[dict]:
    """Install dependencies for selected modules and return per-component results.

    ``cli`` is the standard terminal workstation set. ``runtimes`` installs
    pinned mise and a compatible Node runtime; ``python`` adds a kit-managed
    Python. ``agents`` installs all three agent
    clients; ``pi``, ``opencode`` and ``hermes`` select them separately.
    ``extras`` adds lazygit/lazydocker and optional tealdeer/ncdu/tree, while ``ghostty`` and ``fonts`` are
    explicit desktop add-ons. ``docker`` installs only the lazydocker client.
    """
    repo, home = Path(repo), Path(home)
    if not platform.get("supported"):
        return [_result("platform", "unsupported", platform.get("reason", "Unsupported platform"))]
    try:
        manifest = _manifest(repo)
    except (OSError, ValueError) as exc:
        return [_result("manifest", "failed", str(exc))]

    root = home / ".local" / "share" / "terminal-kit"
    bin_dir = root / "bin"
    if not dry_run:
        (root / "cache").mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)
    requested = set(modules)
    known = {"cli", "runtimes", "python", "agents", "pi", "opencode", "hermes", "extras", "ghostty", "fonts", "docker", "configs", "nvim", "bash", "tmux", "codex", "claude", "treesitter-build", "intel-build"}
    unknown = requested - known
    results = [_result(module, "unsupported", "Unknown installer module", required=False) for module in sorted(unknown)]
    if "intel-build" in requested and not upgrade:
        results.append(_prepare_intel_builds(platform, requested, dry_run))
    cli = "cli" in requested
    if cli:
        pm = platform.get("pm")
        packages = manifest.get("packages", {}).get(pm, [])
        if not packages:
            results.append(_result("packages", "unsupported", f"No package set for {pm}"))
        else:
            # Keep each native operation narrow; a missing package cannot block
            # the rest of the dependency set or user-scoped binary fallbacks.
            for package in packages:
                command, args = _cmd_for(package, pm)
                minimum = manifest.get("minimum_versions", {}).get(command)
                current, executable = _version(command, args)
                installed_now = False
                ensure_package = package in ("bash-completion", "bash-completion@2")
                if upgrade:
                    managed_link = bin_dir / _command_name(package)
                    if managed_link.is_symlink() and _managed_path(managed_link, root):
                        managed_version, managed_path = _version(str(managed_link.resolve()), args)
                        if managed_version:
                            results.append(_result(package, "reused", "Preserving kit-owned binary during scoped update", version=managed_version, path=managed_path, ownership="terminal-kit"))
                            continue
                    if ensure_package:
                        if _package_installed(package, pm):
                            results.append(_result(package, "reused", "Preserving host package during tool-only update", path=executable, ownership=pm))
                        else:
                            results.append(_result(package, "unsupported", "Required host package is missing; update --tools does not install OS packages"))
                    elif current:
                        compatible = not minimum or _at_least(current, minimum)
                        results.append(_result(package, "reused" if compatible else "unsupported",
                                               "Preserving host-managed command during tool-only update" if compatible else f"Host-managed {command} {current} is below required {minimum}; update --tools does not change OS packages",
                                               version=current, path=executable, ownership="existing"))
                    else:
                        results.append(_result(package, "unsupported", f"Required host command {command} is missing; update --tools does not install OS packages"))
                    continue
                if ensure_package and _package_installed(package, pm):
                    results.append(_result(package, "reused", "Package database confirms it is installed", path=executable, ownership=pm))
                    continue
                if current and _at_least(current, minimum) and not ensure_package:
                    results.append(_result(package, "reused", f"Using existing {command}", version=current, path=executable, ownership="terminal-kit" if _managed_path(executable, root) else "existing"))
                    continue
                needs_native = not current or ensure_package or (bool(minimum and not _at_least(current, minimum)) and package in packages)
                if needs_native:
                    status, detail = _install_package(package, pm, unattended, dry_run)
                    if status == "installed":
                        current, executable = _version(command, args)
                        package_verified = not ensure_package or bool(_package_installed(package, pm))
                        if current is None or not package_verified:
                            results.append(_result(package, "failed", f"Package manager completed but {command} failed its version check"))
                        else:
                            installed_now = True
                        if current and command == "fdfind":
                            try:
                                _owned_link(bin_dir / "fd", Path(executable), root)
                            except FileExistsError:
                                pass
                        elif current and command == "batcat":
                            try:
                                _owned_link(bin_dir / "bat", Path(executable), root)
                            except FileExistsError:
                                pass
                        if current and package_verified:
                            results.append(_result(package, "installed", detail, version=current, path=executable, ownership=pm))
                    else:
                        results.append(_result(package, status, detail, version=current, path=executable, ownership="existing" if current else None))
                if package in manifest.get("releases", {}) and (not current or (minimum and not _at_least(current, minimum))):
                    _record_fallback(results, _install_asset(package, manifest["releases"][package], root, bin_dir, platform, dry_run))
                elif not current:
                    if not any(row["name"] == package and row["status"] in ("failed", "skipped", "installed") for row in results):
                        results.append(_result(package, "failed", f"{command} is unavailable after package check"))
                elif minimum and not _at_least(current, minimum):
                    results.append(_result(package, "unsupported", f"Installed {command} {current} is below required {minimum}", version=current, path=executable, ownership="existing"))
                elif not installed_now:
                    results.append(_result(package, "reused", f"Using {command}", version=current, path=executable, ownership="terminal-kit" if _managed_path(executable, root) else "existing"))
        # Official pinned releases fill tool gaps from older vendor repositories.
        candidates = ("neovim", "fzf", "eza", "zoxide", "starship", "lazygit", "lazydocker")
        if platform.get("os") == "macos":
            candidates += ("ripgrep", "fd", "bat")
        for name in candidates:
            if name not in manifest.get("releases", {}):
                continue
            command = _command_name(name)
            minimum = manifest.get("minimum_versions", {}).get(command)
            current, executable = _version(command, _CHECKS.get(command, (command, ["--version"]))[1])
            if upgrade:
                managed_link = bin_dir / _command_name(name)
                managed_binary = managed_link.is_symlink() and _managed_path(managed_link, root)
                if managed_binary:
                    results.append(_install_asset(name, manifest["releases"][name], root, bin_dir, platform, dry_run, upgrade=True))
                continue
            if current and (not minimum or _at_least(current, minimum)):
                results.append(_result(name, "reused", f"Using compatible {command}", version=current, path=executable,
                                       ownership="terminal-kit" if _managed_path(executable, root) else "existing"))
                continue
            existing_fallback = next((r for r in reversed(results) if r["name"] == name and r["status"] in ("installed", "reused", "skipped")), None)
            if not existing_fallback:
                _record_fallback(results, _install_asset(name, manifest["releases"][name], root, bin_dir, platform, dry_run))

    if requested & {"nvim", "treesitter-build"}:
        results.append(_tree_sitter_cli(manifest, root, bin_dir, platform, unattended, dry_run, upgrade,
                                        build="treesitter-build" in requested))

    if cli:
        # Debian names these commands batcat/fdfind; expose conventional names
        # through kit-owned links so non-interactive consumers (including fzf)
        # do not depend on shell aliases.
        path_env = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        for alias, candidates in (("fd", ("fdfind",)), ("bat", ("batcat",))):
            if _version(alias, _CHECKS[alias][1], {**os.environ, "PATH": path_env})[0]:
                continue
            source = None
            for name in candidates:
                version, target = _version(name, _CHECKS.get(name, (name, ["--version"]))[1], {**os.environ, "PATH": path_env})
                if version and target:
                    source = (version, target)
                    break
            if not source:
                continue
            version, target = source
            link = bin_dir / alias
            try:
                if dry_run:
                    results.append(_result(alias, "skipped", f"Dry run: link {alias} to working {Path(target).name}", required=False, version=version, path=target))
                else:
                    _owned_link(link, Path(target), root)
                    results.append(_result(alias, "installed", f"Added kit-owned {alias} compatibility link", required=False, version=version, path=str(link), ownership="terminal-kit"))
            except (FileExistsError, OSError) as exc:
                results.append(_result(alias, "failed", str(exc), required=False, version=version, path=target))

    runtime_requested = bool(requested & {"runtimes", "agents", "pi", "opencode", "python"})
    if runtime_requested:
        node = None
        node_result = None
        # Agents can reuse a compatible system runtime without installing mise.
        if requested & {"agents", "pi", "opencode"}:
            managed_node = bin_dir / "node"
            if upgrade and managed_node.is_symlink() and _managed_path(managed_node, root):
                candidate_name = str(managed_node)
            else:
                candidate_name = shutil.which("node") if (not upgrade or requested & {"agents", "pi", "opencode"}) else None
            npm_name = shutil.which("npm", path=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
            if candidate_name and npm_name:
                candidate = Path(candidate_name)
                node_ver, _ = _version(candidate_name, ["--version"])
                npm_ver, _ = _version(npm_name, ["--version"], _runtime_env(root, bin_dir))
                if node_ver and npm_ver and _at_least(node_ver.lstrip("v"), manifest["runtime_versions"]["node_minimum"]):
                    node = candidate
                    node_result = _result("node", "reused", "Using compatible existing Node and npm", version=node_ver.lstrip("v"), path=str(candidate), ownership="existing")
        needs_managed_runtime = "runtimes" in requested or "python" in requested or (requested & {"agents", "pi", "opencode"} and node is None)
        if needs_managed_runtime:
            mise, mise_result = _ensure_mise(manifest, root, bin_dir, platform, dry_run, upgrade=upgrade)
            mise_result["required"] = True
            results.append(mise_result)
            if mise:
                managed_node = bin_dir / "node"
                upgrade_managed_node = upgrade and managed_node.is_symlink() and _managed_path(managed_node, root)
                if node is None or upgrade_managed_node:
                    node, node_result = _install_node(mise, root, bin_dir, dry_run, upgrade=upgrade)
                if "python" in requested and not dry_run:
                    python_version = manifest["runtime_versions"]["python"]
                    env = _runtime_env(root, bin_dir)
                    python_link = bin_dir / "python"
                    managed_python = python_link.is_symlink() and _managed_path(python_link, root)
                    if upgrade and not managed_python:
                        results.append(_result("python", "reused" if shutil.which("python3") else "skipped", "Preserving host Python; tool updates only change kit-owned runtimes", required=False, path=shutil.which("python3"), ownership="existing" if shutil.which("python3") else None))
                        proc = None
                    else:
                        proc = subprocess.run([str(mise), "install", "--yes", f"python@{python_version}"], env=env, cwd=root, check=False, timeout=1200)

                    resolved = subprocess.run([str(mise), "where", f"python@{python_version}"], env=env, cwd=root, check=False, timeout=30, capture_output=True, text=True) if proc else None
                    python_path = Path(resolved.stdout.strip()) / "bin/python" if resolved and resolved.returncode == 0 and resolved.stdout.strip() else root / "unavailable-python"
                    pyver, _ = _version(str(python_path), ["--version"]) if python_path.exists() else (None, None)
                    if proc and proc.returncode == 0 and pyver:
                        try:
                            _owned_link(bin_dir / "python", python_path, root)
                            _owned_link(bin_dir / "python3", python_path, root)
                        except FileExistsError as exc:
                            results.append(_result("python", "failed", str(exc)))
                        else:
                            results.append(_result("python", "installed", f"Installed Python {pyver} through mise", version=pyver, path=str(python_path), ownership="terminal-kit"))
                    elif proc:
                        results.append(_result("python", "failed", f"mise install python@{python_version} exited {proc.returncode}"))
                elif "python" in requested:
                    python_link = bin_dir / "python"
                    managed_python = python_link.is_symlink() and _managed_path(python_link, root)
                    message = f"Dry run: mise install --yes python@{manifest['runtime_versions']['python']}" if not upgrade or managed_python else "Preserving host Python; tool updates only change kit-owned runtimes"
                    results.append(_result("python", "skipped", message, required=not upgrade or managed_python))
            elif node is None:
                node = None
            if node_result:
                results.append(node_result)
        elif node_result:
            results.append(node_result)
        if node and "runtimes" in requested:
            results.append(_result("node-runtime", "reused" if node_result and node_result["status"] == "reused" else "installed", "Compatible Node/npm is ready", version=node_result.get("version") if node_result else None, path=str(node), ownership=node_result.get("ownership") if node_result else "terminal-kit"))
        selected_agents = {"pi", "opencode", "hermes"} if "agents" in requested else requested & {"pi", "opencode"}
        for agent in sorted(selected_agents):
            results.append(_agent_module(agent, manifest, home, root, bin_dir, None if agent == "hermes" else node, dry_run, upgrade=upgrade, intel_build="intel-build" in requested, platform=platform))
    elif "hermes" in requested:
        results.append(_agent_module("hermes", manifest, home, root, bin_dir, None, dry_run, upgrade=upgrade, intel_build="intel-build" in requested, platform=platform))

    if "extras" in requested:
        for package in manifest.get("extras", {}).get(platform.get("pm"), []):
            command, args = _cmd_for(package, platform.get("pm"))
            version, path = _version(command, args)
            if version:
                results.append(_result(command, "reused", "Using native package", required=False, version=version, path=path, ownership="existing"))
            elif upgrade:
                results.append(_result(command, "skipped", "Optional native extra is absent; update --tools does not install OS packages", required=False))
            else:
                status, detail = _install_package(package, platform.get("pm"), unattended, dry_run)
                if status == "installed":
                    version, path = _version(command, args)
                    status = "installed" if version else "failed"
                    detail = detail if version else f"{detail}; {command} failed its version check"
                results.append(_result(command, status, detail, required=False, version=version, path=path, ownership=platform.get("pm") if status == "installed" else None))
    if ("extras" in requested or "docker" in requested) and not cli:
        names = ("lazygit", "lazydocker") if "extras" in requested else ("lazydocker",)
        for name in names:
            results.append(_ensure_extra_binary(name, manifest, root, bin_dir, platform, unattended, dry_run, upgrade))
    if "ghostty" in requested:
        if upgrade:
            ghostty = shutil.which("ghostty")
            results.append(_result("ghostty", "reused" if ghostty else "skipped", "Preserving host Ghostty package during tool-only update" if ghostty else "Ghostty is absent; tool updates do not install desktop packages", required=False, path=ghostty, ownership="existing" if ghostty else None))
            ghostty = None
        else:
            ghostty = None
        pm = platform.get("pm")
        package = "ghostty" if pm in ("pacman", "brew") or (pm == "apt" and platform.get("distro") == "ubuntu" and platform.get("version") == "26.04") else None
        if upgrade:
            pass
        elif not package:
            results.append(_result("ghostty", "unsupported", "No supported native Ghostty package for this host; no third-party source is added", required=False))
        else:
            command = ["brew", "install", "--cask", "ghostty"] if pm == "brew" else _pkg_command(pm, package, unattended)
            if dry_run:
                results.append(_result("ghostty", "skipped", "Dry run: " + shlex.join(command), required=False))
            else:
                try:
                    proc = _run_native(command, pm, unattended)
                    status = "installed" if proc.returncode == 0 else "failed"
                    results.append(_result("ghostty", status, f"Native {pm} package operation exited {proc.returncode}", required=False, path=shutil.which("ghostty"), ownership=pm if not proc.returncode else None))
                except Exception as exc:
                    results.append(_result("ghostty", "failed", str(exc), required=False))
    if "ghostty" in requested and platform.get("os") == "linux" and platform.get("display"):
        protocol = platform.get("display_protocol")
        package = manifest.get("clipboard_packages", {}).get(platform.get("pm"), {}).get(protocol)
        if package:
            command, args = _cmd_for(package, platform["pm"])
            version, executable = _version(command, args)
            if version:
                results.append(_result(package, "reused", "Using desktop clipboard backend", required=False, version=version, path=executable, ownership="existing"))
            elif upgrade:
                results.append(_result(package, "unsupported", "Clipboard backend is absent; tool updates do not install OS packages", required=False))
            else:
                status, detail = _install_package(package, platform["pm"], unattended, dry_run)
                version, executable = _version(command, args) if status == "installed" else (None, None)
                if status == "installed" and not version:
                    status, detail = "failed", "Clipboard package installed but its executable failed verification"
                results.append(_result(package, status, detail, required=False, version=version, path=executable, ownership=platform["pm"] if version else None))
    if "fonts" in requested:
        font_path = (home / "Library/Fonts/Terminal Kit") if platform.get("os") == "macos" else (home / ".local/share/fonts/terminal-kit")
        if upgrade:
            results.append(_result("font", "reused" if font_path.exists() else "skipped", "Preserving existing user font during tool-only update" if font_path.exists() else "Font is absent; tool updates do not change desktop assets", required=False, path=str(font_path) if font_path.exists() else None, ownership="terminal-kit" if font_path.exists() else None))
        else:
            results.append(_install_font(root, home, platform, dry_run))
    for module, tool in (("bash", "bash"), ("tmux", "tmux")):
        if module in requested:
            command, args = _CHECKS[tool]
            version, path = _version(command, args)
            results.append(_result(tool, "reused" if version else "unsupported", "Using host command" if version else "Required command is missing", version=version, path=path, required=True))
    for agent in sorted(requested & {"codex", "claude"}):
        version, path = _version(agent, ["--version"])
        results.append(_result(agent, "reused" if version else "unsupported",
                               "Using existing CLI" if version else "This optional CLI is not installed by terminal-kit",
                               required=False, version=version, path=path, ownership="existing" if version else None))
    # A successful pinned fallback supersedes the failed/old native receipt
    # for the same component. Keep one final, authoritative row per name.
    final = {}
    for row in results:
        final[row["name"]] = row
    return list(final.values())
