import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from terminalkit import platforms, tools
from terminalkit.download import DownloadError


class PlatformTests(unittest.TestCase):
    def detect(self, system="Linux", machine="x86_64", release="6.12", env=None, metadata=None):
        with patch.object(platforms._platform, "system", return_value=system), \
             patch.object(platforms._platform, "machine", return_value=machine), \
             patch.object(platforms._platform, "release", return_value=release), \
             patch.object(platforms._platform, "mac_ver", return_value=("15.0", ("", "", ""), "arm64")):
            return platforms.detect(env or {}, os_release=metadata or {"ID": "ubuntu", "VERSION_ID": "24.04"})

    def test_linux_arm_and_headless_ssh(self):
        result = self.detect(machine="aarch64", env={"SSH_CONNECTION": "host 22 1 2"})
        self.assertTrue(result["supported"])
        self.assertEqual(result["arch"], "aarch64")
        self.assertTrue(result["ssh"])
        self.assertFalse(result["display"])

    def test_wsl2_and_wsl1(self):
        wsl2 = self.detect(release="6.6.87.2-microsoft-standard-WSL2", env={"WSL_INTEROP": "pipe", "DISPLAY": ":0", "COMSPEC": "C:\\Windows\\System32\\cmd.exe"})
        self.assertTrue(wsl2["supported"])
        self.assertEqual(wsl2["wsl"], 2)
        self.assertTrue(wsl2["windows_interop"])
        wsl1 = self.detect(release="4.4.0-microsoft", env={"WSL_INTEROP": "pipe"})
        self.assertFalse(wsl1["supported"])
        self.assertEqual(wsl1["wsl"], 1)

    def test_arch_arm_is_unsupported_and_unknown_distro_stays_unsupported(self):
        arch = self.detect(machine="aarch64", metadata={"ID": "arch"})
        self.assertFalse(arch["supported"])
        arch_derivative = self.detect(metadata={"ID": "omarchy", "ID_LIKE": "arch", "VERSION_ID": "4.0.4"})
        self.assertTrue(arch_derivative["supported"])
        self.assertEqual(arch_derivative["distro"], "arch")
        alpine = self.detect(metadata={"ID": "alpine", "VERSION_ID": "3.21"})
        self.assertFalse(alpine["supported"])

    def test_macos_support_floor_and_intel_caveat(self):
        arm = self.detect(system="Darwin", machine="arm64")
        self.assertTrue(arm["supported"])
        intel = self.detect(system="Darwin", machine="x86_64")
        self.assertIn("Intel", intel["reason"])


class ToolTests(unittest.TestCase):
    def test_apt_defers_service_restarts_even_when_caller_requests_automatic_mode(self):
        with patch.object(tools.os, "geteuid", return_value=1000), \
             patch.object(tools.shutil, "which", return_value="/usr/bin/sudo"), \
             patch.dict(os.environ, {"NEEDRESTART_MODE": "a"}), \
             patch.object(tools.subprocess, "run", return_value=tools.subprocess.CompletedProcess([], 0)) as run:
            tools._run_native(["apt-get", "install", "-y", "tmux"], "apt", True, timeout=12)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/sudo", "-n", "env", "NEEDRESTART_MODE=l", "apt-get", "install", "-y", "tmux"])
        self.assertEqual(run.call_args.kwargs["timeout"], 12)

    def test_non_apt_packages_keep_their_existing_environment_policy(self):
        with patch.object(tools.os, "geteuid", return_value=1000), \
             patch.object(tools.shutil, "which", return_value="/usr/bin/sudo"), \
             patch.object(tools.subprocess, "run", return_value=tools.subprocess.CompletedProcess([], 0)) as run:
            tools._run_native(["dnf", "install", "-y", "tmux"], "dnf", True)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/sudo", "-n", "dnf", "install", "-y", "tmux"])

    def test_interactive_package_operation_without_a_terminal_fails_before_sudo(self):
        with patch.object(tools.os, "geteuid", return_value=1000), \
             patch.object(tools.shutil, "which", return_value="/usr/bin/sudo"), \
             patch.object(tools.os, "isatty", return_value=False), \
             patch.object(tools.subprocess, "run") as run:
            result = tools._run_native(["apt-get", "install", "-y", "tmux"], "apt", False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("interactive terminal", result.stderr)
        run.assert_not_called()

    def test_wsl_graphical_font_targets_linux_client_and_headless_needs_windows_font(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(tools, "download", side_effect=AssertionError("dry-run downloaded")):
            home = Path(temporary)
            graphical = tools._install_font(home / "kit", home, {"os": "linux", "wsl": 2, "display": True}, True)
            headless = tools._install_font(home / "kit", home, {"os": "linux", "wsl": 2, "display": False}, True)
        self.assertEqual(graphical["status"], "skipped")
        self.assertEqual(headless["status"], "unsupported")

    def test_font_accepts_pinned_archive_size_and_retains_license(self):
        # Official v3.5.1 ZIP size and the sum of its member sizes.
        def fetch(url, destination, sha256, max_bytes):
            if max_bytes < 133975870:
                raise DownloadError("Download exceeds size limit")
            return destination

        def extract(archive, destination, max_bytes):
            if max_bytes < 243185440:
                raise DownloadError("Archive exceeds extraction limits")
            destination.mkdir(parents=True)
            (destination / "JetBrainsMonoNerdFont-Regular.ttf").write_bytes(b"font fixture")
            (destination / "OFL.txt").write_text("license fixture")

        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(tools, "download", side_effect=fetch), \
             patch.object(tools, "safe_extract", side_effect=extract), \
             patch.object(tools.shutil, "which", return_value=None):
            home = Path(temporary)
            result = tools._install_font(home / "kit", home, {"os": "linux"}, False)
            self.assertEqual(result["status"], "installed", result["detail"])
            destination = Path(result["path"])
            self.assertEqual((destination / "JetBrainsMonoNerdFont-Regular.ttf").read_bytes(), b"font fixture")
            self.assertEqual((destination / "OFL.txt").read_text(), "license fixture")

    def test_intel_build_preview_is_read_only_and_other_hosts_skip_it(self):
        with patch.object(tools.subprocess, "run", side_effect=AssertionError("dry-run executed")), \
             patch.object(tools.subprocess, "check_output", side_effect=AssertionError("dry-run inspected Homebrew")):
            result = tools._prepare_intel_builds({"os": "macos", "arch": "x86_64"}, {"cli", "agents"}, True)
            skipped = tools._prepare_intel_builds({"os": "linux", "arch": "x86_64"}, {"cli"}, False)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("20–90 minutes", result["detail"])
        self.assertEqual(skipped["status"], "skipped")

    def test_intel_build_reuses_inventory_and_has_explicit_longer_bound(self):
        with patch.object(tools, "_version", return_value=(None, None)), \
             patch.object(tools.subprocess, "check_output", side_effect=["cmake\nlibevent\n", "cmake 4.4.2\n", ""]), \
             patch.object(tools.time, "monotonic", return_value=100), \
             patch.object(tools, "_run_native", return_value=tools.subprocess.CompletedProcess([], 0)) as native:
            result = tools._prepare_intel_builds({"os": "macos", "arch": "x86_64"}, {"cli"}, False)
        self.assertEqual(result["status"], "installed")
        self.assertEqual([call.args[0] for call in native.call_args_list], [["brew", "install", "--build-from-source", name] for name in ("libevent", "tmux", "btop")])
        self.assertTrue(all(call.kwargs["timeout"] == 3600 for call in native.call_args_list))

    def test_intel_build_upgrades_only_required_outdated_dependencies_before_parents(self):
        with patch.object(tools, "_version", return_value=(None, None)), \
             patch.object(tools.subprocess, "check_output", side_effect=["pkgconf\nlibevent\n", "pkgconf 3.0.5\nunrelated 1.0\n", "pkgconf\n"]), \
             patch.object(tools, "_run_native", return_value=tools.subprocess.CompletedProcess([], 0)) as native:
            result = tools._prepare_intel_builds({"os": "macos", "arch": "x86_64"}, {"cli"}, False)
        self.assertEqual(result["status"], "installed")
        commands = [call.args[0] for call in native.call_args_list]
        self.assertEqual(commands[0], ["brew", "upgrade", "--build-from-source", "pkgconf"])
        self.assertEqual(commands[1], ["brew", "install", "--build-from-source", "libevent"])
        self.assertFalse(any("unrelated" in command for command in commands))

    def test_homebrew_operations_do_not_cleanup_or_upgrade_unrelated_dependents(self):
        with patch.object(tools.subprocess, "Popen") as spawn:
            spawn.return_value.wait.return_value = 0
            tools._run_native(["brew", "install", "tmux"], "brew", True)
        environment = spawn.call_args.kwargs["env"]
        for flag in ("HOMEBREW_NO_AUTO_UPDATE", "HOMEBREW_NO_INSTALL_UPGRADE", "HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK", "HOMEBREW_NO_INSTALL_CLEANUP"):
            self.assertEqual(environment[flag], "1")
        spawn.return_value.wait.assert_called_once_with(timeout=1800)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])

    def test_timed_out_native_build_stops_compiler_descendants(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "abandoned-child"
            child = "import time,sys,pathlib; time.sleep(0.6); pathlib.Path(sys.argv[1]).write_text('still running')"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(10)"
            with self.assertRaises(tools.subprocess.TimeoutExpired):
                tools._run_native([sys.executable, "-c", parent, child, str(marker)], "brew", True, timeout=0.2)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "Compiler child survived the bounded build")

    def test_intel_hermes_requires_explicit_build_without_downgrading_security_pin(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(tools.shutil, "which", return_value=None), \
             patch.object(tools, "download", side_effect=AssertionError("build not authorized")):
            home = Path(temporary)
            result = tools._agent_module("hermes", manifest, home, home / "kit", home / "kit/bin", None, True,
                                         platform={"os": "macos", "arch": "x86_64"})
        self.assertEqual(result["status"], "unsupported")
        self.assertIn("--with intel-build", result["detail"])
        self.assertTrue(result["required"])

    def test_successful_verified_fallback_resolves_native_failure(self):
        rows = [tools._result("neovim", "failed", "Native bottle unavailable")]
        tools._record_fallback(rows, tools._result("neovim", "installed", "Verified release executable"))
        self.assertFalse(any(row["required"] and row["status"] == "failed" for row in rows))
        self.assertIn("verified upstream binary", rows[0]["detail"])
        failed = [tools._result("neovim", "failed", "Native package failed")]
        tools._record_fallback(failed, tools._result("neovim", "failed", "Binary failed verification"))
        self.assertTrue(all(row["required"] for row in failed))

    def test_intel_homebrew_only_builds_selected_small_dependencies(self):
        with patch.object(tools.sys, "platform", "darwin"), \
             patch.object(tools.host_platform, "machine", return_value="x86_64"):
            self.assertIn("--build-from-source", tools._pkg_command("brew", "bash", True))
            self.assertIn("--force-bottle", tools._pkg_command("brew", "neovim", True))
            self.assertIn("--force-bottle", tools._pkg_command("brew", "bat", True))

    def test_macos_managed_mise_remains_owned_during_update(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "kit"
            executable = root / "tools/mise/mise"
            executable.parent.mkdir(parents=True)
            executable.write_text("managed executable")
            executable.chmod(0o755)
            with patch.object(tools.shutil, "which", return_value=str(executable)), \
                 patch.object(tools, "_version", return_value=("2026.9.18", str(executable))), \
                 patch.object(tools, "download", side_effect=AssertionError("already current")):
                _, result = tools._ensure_mise(manifest, root, root / "bin", {"os": "macos", "arch": "aarch64"}, True, upgrade=True)
            self.assertEqual(result["status"], "reused")
            self.assertEqual(result["ownership"], "terminal-kit")

    def test_version_ignores_commit_hash_and_build_date_before_lazygit_version(self):
        output = "commit=17cb09fa, build date=2026-09-13, version=0.65.1, git version=2.43.0"
        with patch.object(tools.shutil, "which", return_value="/kit/bin/lazygit"), \
             patch.object(tools.subprocess, "run", return_value=tools.subprocess.CompletedProcess([], 0, output, "")):
            version, _ = tools._version("lazygit", ["--version"])
        self.assertEqual(version, "0.65.1")
        self.assertFalse(tools._at_least(version, "1.0.0"))

    def test_version_uses_a_single_flag_and_enforces_minimum(self):
        with patch.object(tools.shutil, "which", return_value="/usr/bin/bash"), \
             patch.object(tools.subprocess, "run", return_value=tools.subprocess.CompletedProcess([], 0, "GNU bash, version 5.2.0\n", "")) as run:
            version, path = tools._version("bash", "--version")
        self.assertEqual(version, "5.2.0")
        self.assertEqual(path, "/usr/bin/bash")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/bash", "--version"])
        self.assertTrue(tools._at_least(version, "4.0"))
        self.assertFalse(tools._at_least("installed", "3.11"))

    def test_runtime_wrapper_preserves_dollar_zero_relative_launcher_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            runtime = root / "runtimes/node/bin"
            lib = root / "runtimes/node/lib/node_modules/npm/bin"
            kit_bin = root / "bin"
            runtime.mkdir(parents=True)
            lib.mkdir(parents=True)
            kit_bin.mkdir(parents=True)
            target = runtime / "npm"
            target.write_text("#!/bin/sh\nbasedir=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\nexec \"$basedir/../lib/node_modules/npm/bin/npm-cli.js\" \"$@\"\n", encoding="utf-8")
            target.chmod(0o755)
            cli = lib / "npm-cli.js"
            cli.write_text("#!/bin/sh\necho 99.1.0\n", encoding="utf-8")
            cli.chmod(0o755)
            wrapper = kit_bin / "npm"
            tools._owned_wrapper(wrapper, target, root)
            version, path = tools._version("npm", ["--version"], {"PATH": str(kit_bin) + ":" + os.environ.get("PATH", "")})
            self.assertEqual(version, "99.1.0")
            self.assertEqual(path, str(wrapper))
            self.assertIn("terminal-kit runtime wrapper", wrapper.read_text(encoding="utf-8"))

    def test_reused_managed_node_migrates_npm_and_npx_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            runtime = root / "runtimes/installs/node/26.10.0/bin"
            kit_bin = root / "bin"
            npm_lib = root / "runtimes/installs/node/26.10.0/lib/node_modules/npm/bin"
            npx_lib = root / "runtimes/installs/node/26.10.0/lib/node_modules/npm/bin"
            runtime.mkdir(parents=True)
            kit_bin.mkdir(parents=True)
            npm_lib.mkdir(parents=True)
            (runtime / "node").write_text("#!/bin/sh\necho v26.10.0\n", encoding="utf-8")
            (runtime / "node").chmod(0o755)
            for name in ("npm", "npx"):
                (runtime / name).write_text(f'#!/bin/sh\nbasedir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$basedir/../lib/node_modules/npm/bin/{name}-cli.js" "$@"\n', encoding="utf-8")
                (runtime / name).chmod(0o755)
                cli = npm_lib / f"{name}-cli.js"
                cli.write_text("#!/bin/sh\necho 10.0.0\n", encoding="utf-8")
                cli.chmod(0o755)
                (kit_bin / name).symlink_to(runtime / name)
            (kit_bin / "node").symlink_to(runtime / "node")
            node, result = tools._install_node(Path("/unused/mise"), root, kit_bin, False)
            self.assertEqual(result["status"], "reused")
            self.assertTrue(node)
            for command in ("npm", "npx"):
                version, path = tools._version(command, ["--version"], {"PATH": str(kit_bin) + os.pathsep + os.environ.get("PATH", "")})
                self.assertEqual(version, "10.0.0")
                self.assertEqual(path, str(kit_bin / command))
                self.assertFalse((kit_bin / command).is_symlink())

    def test_runtime_wrapper_refuses_unrelated_bin_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            (root / "bin").mkdir(parents=True)
            target = root / "runtimes/node/bin/npm"
            target.parent.mkdir(parents=True)
            target.write_text("#!/bin/sh\n", encoding="utf-8")
            collision = root / "bin/npm"
            collision.write_text("user-owned", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                tools._owned_wrapper(collision, target, root)
            self.assertEqual(collision.read_text(encoding="utf-8"), "user-owned")

    def test_manifest_has_pinned_assets_and_official_hermes_installer(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        self.assertEqual(manifest["releases"]["neovim"]["version"], "v0.12.5")
        self.assertEqual(manifest["minimum_versions"]["nvim"], "0.12.0")
        tree_sitter = manifest["tree_sitter_cli"]
        self.assertEqual(tree_sitter["version"], "0.26.1")
        self.assertEqual(tree_sitter["rust_version"], "1.92.0")
        self.assertEqual(len(tree_sitter["source_sha256"]), 64)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in tree_sitter["assets"].values()))
        for item in manifest["releases"].values():
            for asset in item["assets"].values():
                self.assertEqual(len(asset["sha256"]), 64)
                self.assertTrue(asset["url"].startswith("https://"))
        self.assertEqual(len(manifest["agents"]["hermes"]["installer_sha256"]), 64)

    def test_treesitter_optin_build_preview_is_explicit_and_read_only(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            with patch.object(tools, "_version", return_value=(None, None)), \
                 patch.object(tools, "download", side_effect=AssertionError("preview downloaded source")), \
                 patch.object(tools, "_ensure_mise", side_effect=AssertionError("preview installed mise")):
                result = tools._tree_sitter_cli(manifest, root, root / "bin",
                    {"os": "linux", "arch": "x86_64", "pm": "apt"}, False, True, False, build=True)
            self.assertEqual(result["status"], "skipped")
            self.assertIn("10–30 minutes", result["detail"])
            self.assertIn("hundred", result["detail"])
            self.assertFalse(root.exists())

    def test_treesitter_verified_release_asset_installs_and_links(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            bin_dir = root / "bin"
            compressed = root / "fixture.gz"
            compressed.parent.mkdir(parents=True)
            compressed.write_bytes(b"fixture")
            def fake_download(url, dest, sha, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(compressed.read_bytes())
                return dest
            versions = iter([(None, None), ("0.26.1", "fixture")])
            with patch.object(tools, "_version", side_effect=lambda *a, **k: next(versions)), \
                 patch.object(tools, "download", side_effect=fake_download), \
                 patch.object(tools.gzip, "open") as open_gzip:
                from io import BytesIO
                open_gzip.return_value.__enter__.return_value = BytesIO(b"#!/bin/sh\necho tree-sitter 0.26.1\n")
                result = tools._tree_sitter_cli(manifest, root, bin_dir,
                    {"os": "linux", "arch": "x86_64", "pm": "apt"}, False, False, False)
            self.assertEqual(result["status"], "installed", result["detail"])
            self.assertEqual(result["version"], "0.26.1")
            self.assertTrue((bin_dir / "tree-sitter").is_symlink())

    def test_treesitter_native_package_is_preferred_when_compatible(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temporary:
            versions = iter([(None, None), ("0.27.0", "/usr/bin/tree-sitter")])
            with patch.object(tools, "_version", side_effect=lambda *a, **k: next(versions)), \
                 patch.object(tools, "_install_package", return_value=("installed", "Installed with pacman")) as install, \
                 patch.object(tools, "download", side_effect=AssertionError("release should not be needed")):
                result = tools._tree_sitter_cli(manifest, Path(temporary) / "kit", Path(temporary) / "kit/bin",
                    {"os": "linux", "arch": "x86_64", "pm": "pacman"}, False, False, False)
            self.assertEqual(result["status"], "installed")
            self.assertEqual(install.call_args.args[:2], ("tree-sitter-cli", "pacman"))

    def test_treesitter_update_does_not_replace_host_install(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(tools, "_version", return_value=("0.25.0", "/usr/bin/tree-sitter")), \
                 patch.object(tools, "download", side_effect=AssertionError("update touched host binary")), \
                 patch.object(tools, "_install_package", side_effect=AssertionError("update touched host package")):
                result = tools._tree_sitter_cli(manifest, Path(temporary) / "kit", Path(temporary) / "kit/bin",
                    {"os": "linux", "arch": "x86_64", "pm": "pacman"}, True, False, True)
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["ownership"], "existing")

    def test_mise_update_validates_staged_binary_before_replacing_current(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = tools._manifest(repo)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            executable = root / "tools/mise/mise"
            executable.parent.mkdir(parents=True)
            executable.write_text("old known-good binary", encoding="utf-8")
            archive_asset = manifest["mise"]["assets"]["linux-x86_64"]

            def fake_download(url, dest, sha):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("archive", encoding="utf-8")
                return dest

            def fake_extract(archive, stage):
                source = stage / manifest["mise"]["binary_member"]
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("bad staged binary", encoding="utf-8")
                source.chmod(0o755)

            versions = iter([("2026.1.0", str(executable)), (None, str(executable.with_name("mise.new")))])
            with patch.object(tools, "download", side_effect=fake_download), \
                 patch.object(tools, "safe_extract", side_effect=fake_extract), \
                 patch.object(tools, "_version", side_effect=lambda *a, **kw: next(versions)):
                _, result = tools._ensure_mise(manifest, root, root / "bin",
                    {"os": "linux", "arch": "x86_64"}, False, upgrade=True)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(executable.read_text(encoding="utf-8"), "old known-good binary")

    def test_broken_existing_mise_is_not_reused(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = tools._manifest(repo)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            executable = root / "tools/mise/mise"
            executable.parent.mkdir(parents=True)
            executable.write_text("broken", encoding="utf-8")
            with patch.object(tools, "_version", return_value=(None, str(executable))), \
                 patch.object(tools, "download", side_effect=OSError("offline")):
                _, result = tools._ensure_mise(manifest, root, root / "bin",
                    {"os": "linux", "arch": "x86_64"}, False)
            self.assertNotEqual(result["status"], "reused")
            self.assertEqual(executable.read_text(encoding="utf-8"), "broken")

    def test_minimal_cli_skips_treesitter_and_creates_safe_debian_aliases(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            tools_dir = home / "native"
            tools_dir.mkdir()
            fdfind = tools_dir / "fdfind"
            batcat = tools_dir / "batcat"
            for path in (fdfind, batcat):
                path.write_text("#!/bin/sh\necho 1.0.0\n", encoding="utf-8")
                path.chmod(0o755)
            manifest = {"packages": {"apt": []}, "releases": {}}

            def version(name, args=None, env=None):
                paths = {"fd": (None, None), "bat": (None, None),
                         "fdfind": ("10.0.0", str(fdfind)), "batcat": ("1.0.0", str(batcat))}
                return paths.get(name, (None, None))

            with patch.object(tools, "_manifest", return_value=manifest), \
                 patch.object(tools, "_version", side_effect=version), \
                 patch.object(tools, "_tree_sitter_cli", side_effect=AssertionError("minimal cli should not require parsers")):
                preview = tools.install_tools(repo, home,
                    {"supported": True, "pm": "apt", "os": "linux", "arch": "x86_64"}, ["cli"], dry_run=True)
                kit_bin = home / ".local/share/terminal-kit/bin"
                self.assertFalse((kit_bin / "fd").exists())
                rows = tools.install_tools(repo, home,
                    {"supported": True, "pm": "apt", "os": "linux", "arch": "x86_64"}, ["cli"])
            self.assertTrue(any(row["name"] == "fd" and row["status"] == "skipped" for row in preview))
            self.assertTrue((kit_bin / "fd").is_symlink())
            self.assertTrue((kit_bin / "bat").is_symlink())
            self.assertEqual((kit_bin / "fd").resolve(), fdfind.resolve())
            self.assertEqual((kit_bin / "bat").resolve(), batcat.resolve())

    def test_dry_run_does_not_mutate_home_or_call_package_manager(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with patch.object(tools, "_version", return_value=(None, None)), \
                 patch.object(tools, "_run_native", side_effect=AssertionError("dry run invoked native installer")), \
                 patch.object(tools, "download", side_effect=AssertionError("dry run downloaded")):
                results = tools.install_tools(repo, home, {"supported": True, "pm": "apt", "os": "linux", "arch": "x86_64"},
                                             ["cli", "runtimes", "agents", "fonts"], dry_run=True)
            self.assertTrue(results)
            self.assertTrue(all(item["status"] in {"skipped", "unsupported", "reused"} for item in results))
            self.assertFalse((home / ".local/share/terminal-kit").exists())

    def test_tools_update_never_runs_native_package_operations(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with patch.object(tools, "_version", return_value=("99.0.0", "/usr/bin/tool")), \
                 patch.object(tools, "_package_installed", return_value=True), \
                 patch.object(tools, "_install_package", side_effect=AssertionError("tool update invoked package manager")), \
                 patch.object(tools, "_install_asset", side_effect=AssertionError("unowned binary should not update")):
                rows = tools.install_tools(repo, home, {"supported": True, "pm": "apt", "os": "linux", "arch": "x86_64"},
                                           ["cli"], upgrade=True)
            self.assertTrue(rows)
            self.assertFalse(any(row["status"] == "failed" for row in rows))

    def test_tool_update_preview_only_selects_kit_owned_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "kit"
            bin_dir = root / "bin"
            tool_dir = root / "tools/fzf"
            tool_dir.mkdir(parents=True)
            binary = tool_dir / "fzf"
            binary.write_text("old pinned binary", encoding="utf-8")
            binary.chmod(0o755)
            bin_dir.mkdir()
            (bin_dir / "fzf").symlink_to(binary)
            spec = tools._manifest(Path(__file__).resolve().parents[1])["releases"]["fzf"]
            platform = {"os": "linux", "arch": "x86_64"}
            with patch.object(tools, "_version", return_value=("0.70.0", str(binary))), \
                 patch.object(tools, "download", side_effect=AssertionError("dry-run downloaded")):
                result = tools._install_asset("fzf", spec, root, bin_dir, platform, True, upgrade=True)
            self.assertEqual(result["status"], "skipped")
            self.assertIn("update kit-owned", result["detail"])
            self.assertEqual(binary.read_text(encoding="utf-8"), "old pinned binary")
            self.assertEqual((bin_dir / "fzf").resolve(), binary.resolve())

    def test_optional_binary_prefers_supported_native_package_before_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            installed = {"value": False}
            def version(command, args=None, env=None):
                if command == "lazygit" and installed["value"]:
                    return "0.65.1", "/usr/bin/lazygit"
                return None, None
            def package(name, pm, unattended, dry_run):
                installed["value"] = True
                return "installed", "Installed with pacman"
            with patch.object(tools, "_version", side_effect=version), \
                 patch.object(tools, "_install_package", side_effect=package) as install_package, \
                 patch.object(tools, "_install_asset", side_effect=AssertionError("native package succeeded")):
                result = tools._ensure_extra_binary("lazygit", tools._manifest(Path(__file__).resolve().parents[1]),
                                                    root, root / "bin", {"os": "linux", "arch": "x86_64", "pm": "pacman"},
                                                    False, False, False)
            self.assertEqual(result["status"], "installed")
            self.assertEqual(install_package.call_args.args[0], "lazygit")

    def test_tools_update_repins_kit_owned_npm_agent(self):
        manifest = tools._manifest(Path(__file__).resolve().parents[1])
        manifest["agents"]["pi"].update({"version": "v1.0.0", "minimum": "0.1.0"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kit"
            bin_dir = root / "bin"
            entry = root / "tools/npm/pi/bin/pi"
            entry.parent.mkdir(parents=True)
            entry.write_text("#!/bin/sh\n", encoding="utf-8")
            entry.chmod(0o755)
            bin_dir.mkdir()
            (bin_dir / "pi").symlink_to(entry)
            node_bin = root / "runtime/bin"
            node_bin.mkdir(parents=True)
            (node_bin / "node").touch()
            (node_bin / "npm").touch()
            versions = iter(("0.9.0", "1.0.0"))
            def version(command, args=None, env=None):
                return (next(versions), str(entry)) if command == "pi" else ("10.0.0", str(node_bin / "npm"))
            with patch.object(tools.shutil, "which", side_effect=lambda name, path=None: str(bin_dir / "pi") if name == "pi" else (str(node_bin / "npm") if name == "npm" else None)), \
                 patch.object(tools, "_version", side_effect=version), \
                 patch.object(tools.subprocess, "run", return_value=tools.subprocess.CompletedProcess([], 0, "", "")) as run:
                result = tools._agent_module("pi", manifest, Path(temporary), root, bin_dir, node_bin / "node", False, upgrade=True)
            self.assertEqual(result["status"], "installed")
            self.assertTrue(result["required"])
            self.assertIn("@1.0.0", run.call_args.args[0][-1])

    def test_hermes_update_refuses_dirty_kit_checkout(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = tools._manifest(repo)
        spec = manifest["agents"]["hermes"]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "kit"
            bin_dir = root / "bin"
            checkout = root / "tools/hermes" / spec["commit"]
            (checkout / ".git").mkdir(parents=True)
            marker = checkout.parent / (spec["commit"] + ".owned")
            marker.write_text(spec["commit"] + "\n", encoding="utf-8")
            shim = root / "hermes-user-home/.local/bin/hermes"
            shim.parent.mkdir(parents=True)
            shim.write_text("#!/bin/sh\n", encoding="utf-8")
            shim.chmod(0o755)
            bin_dir.mkdir(parents=True)
            (bin_dir / "hermes").symlink_to(shim)
            def run(argv, **kwargs):
                if "rev-parse" in argv:
                    return tools.subprocess.CompletedProcess(argv, 0, spec["commit"] + "\n", "")
                return tools.subprocess.CompletedProcess(argv, 0, "?? local-edit\n", "")
            with patch.object(tools.shutil, "which", return_value=str(bin_dir / "hermes")), \
                 patch.object(tools, "_version", return_value=(spec["minimum"], str(bin_dir / "hermes"))), \
                 patch.object(tools.subprocess, "run", side_effect=run), \
                 patch.object(tools, "download", side_effect=AssertionError("dirty checkout should stop before download")):
                result = tools._agent_module("hermes", manifest, home, root, bin_dir, None, False, upgrade=True, platform={"os": "linux", "arch": "x86_64"})
            self.assertEqual(result["status"], "failed")
            self.assertIn("refusing to reset", result["detail"])

    def test_tools_update_preserves_host_managed_agent(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = tools._manifest(repo)
        with patch.object(tools.shutil, "which", return_value="/usr/bin/pi"), \
             patch.object(tools, "_version", return_value=("0.99.1", "/usr/bin/pi")):
            result = tools._agent_module("pi", manifest, Path("/tmp/home"), Path("/tmp/kit"),
                                         Path("/tmp/kit/bin"), None, False, upgrade=True)
        self.assertEqual(result["status"], "reused")
        self.assertEqual(result["ownership"], "existing")
        self.assertFalse(result["required"])

    def test_extras_use_native_packages_and_python_pin_is_exact(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = tools._manifest(repo)
        self.assertEqual(manifest["runtime_versions"]["python"], "3.13.15")
        self.assertEqual(manifest["extras"]["apt"], ["tealdeer", "ncdu", "tree"])
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(tools, "_version", return_value=(None, None)), \
                 patch.object(tools, "_run_native", side_effect=AssertionError("dry-run invoked package manager")):
                rows = tools.install_tools(repo, Path(temporary),
                                           {"supported": True, "pm": "apt", "os": "linux", "arch": "x86_64"},
                                           ["extras"], dry_run=True)
        self.assertTrue({"tldr", "ncdu", "tree", "lazygit", "lazydocker"}.issubset({r["name"] for r in rows}))

    def test_unknown_distro_is_reported_without_installing(self):
        with tempfile.TemporaryDirectory() as temporary:
            results = tools.install_tools(Path(temporary), Path(temporary), {"supported": False, "reason": "unsupported"}, [], dry_run=True)
            self.assertEqual(results[0]["status"], "unsupported")


    def test_agent_receipt_is_a_required_single_result(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = tools._manifest(repo)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "kit"
            bin_dir = root / "bin"
            node_bin = root / "runtimes" / "installs" / "node" / "26.10.0" / "bin"
            node_bin.mkdir(parents=True)
            node = node_bin / "node"
            npm = node_bin / "npm"
            node.touch(); npm.touch()
            entry = root / "tools/npm/pi/bin/pi"
            def run(argv, **kwargs):
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text("#!/bin/sh\necho pi\n", encoding="utf-8")
                entry.chmod(0o755)
                return tools.subprocess.CompletedProcess(argv, 0, "", "")
            with patch.object(tools.shutil, "which", side_effect=lambda name, **kw: str(node.parent / "npm") if name == "npm" else None), \
                 patch.object(tools.subprocess, "run", side_effect=run), \
                 patch.object(tools, "_version", return_value=("0.99.1", str(entry))):
                result = tools._agent_module("pi", manifest, base, root, bin_dir, node, False)
            self.assertIsInstance(result, dict)
            self.assertTrue(result["required"])
            self.assertEqual(result["status"], "installed")

    def test_hermes_reuses_standard_data_and_never_force_resets(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = tools._manifest(repo)
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "kit"
            bin_dir = root / "bin"
            (home / ".hermes").mkdir()
            calls = []
            def run(argv, **kwargs):
                calls.append(argv)
                if "--stage" in argv and argv[argv.index("--stage") + 1] == "repository":
                    (root / "tools/hermes" / manifest["agents"]["hermes"]["commit"]).mkdir(parents=True, exist_ok=True)
                if "--stage" in argv and argv[argv.index("--stage") + 1] == "path":
                    shim = root / "hermes-user-home/.local/bin/hermes"
                    shim.parent.mkdir(parents=True, exist_ok=True)
                    shim.write_text("#!/bin/sh\n", encoding="utf-8")
                    shim.chmod(0o755)
                return tools.subprocess.CompletedProcess(argv, 0, "", "")
            with patch.object(tools, "download", side_effect=lambda url, dest, sha, **kw: Path(dest).write_text("script", encoding="utf-8")), \
                 patch.object(tools, "validate_script"), patch.object(tools.subprocess, "run", side_effect=run), \
                 patch.object(tools, "_version", return_value=("0.21.5", str(bin_dir / "hermes"))), \
                 patch.object(tools.shutil, "which", return_value=None):
                result = tools._agent_module("hermes", manifest, home, root, bin_dir, None, False, platform={"os": "linux", "arch": "x86_64"})
            self.assertTrue(result["required"])
            self.assertEqual(result["status"], "installed", result["detail"])
            self.assertTrue(any("--hermes-home" in call and str(home / ".hermes") in call for call in calls))
            self.assertFalse(any("--force-commit" in call for call in calls))
            self.assertTrue(all("--stage" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
