"""Exercise the App installer against a disposable OpenWrt filesystem fixture."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ASSETS = Path(__file__).resolve().parents[3] / "App/Resources/UULinkInstaller"
AGENT = Path(__file__).resolve().parents[1]
LAUNCHER = ASSETS / "install-only.sh"
ARCHIVE = ASSETS / "uulink-agent-v0.3.0-rc.6.tar.gz"
ARCHIVE_SHA256 = "ea4e09cab4d22ada012082b761bb700ea9cf83d0eab93945f4fa55b8a54a9f46"


@unittest.skipUnless(LAUNCHER.is_file(), "requires the iOS workspace")
class AppInstallOnlyTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="uulink-app-install-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.tmp = self.root / "tmp"
        self.commands = self.root / "bin"
        self.tmp.mkdir()
        self.commands.mkdir()
        self.launcher = self.root / "install-only.sh"
        self.launcher.write_text(
            re.sub(r"(?<!\w)/(etc|usr|opt|www|tmp)(?=/|\b)", rf"{self.root}/\1", LAUNCHER.read_text())
        )
        for path in (
            "etc/openwrt_release", "etc/init.d/rpcd", "usr/lib/rpcd/ucode.so",
            "www/cgi-bin/luci", "usr/libexec/.keep", "usr/share/rpcd/ucode/.keep",
            "usr/share/rpcd/acl.d/.keep", "usr/share/luci/menu.d/.keep", "www/luci-static/resources/view/.keep",
        ):
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch()
        (self.root / "etc/init.d/rpcd").chmod(0o755)
        self.sampler = self.root / "usr/libexec/uulink/sampler.uc"
        self.lock = self.tmp / "uulink-agent-install.lock"
        self.installed = self.root / "installer-called"
        self.command("id", "echo 0")
        self.command("ucode", "exit 0")
        self.command("jsonfilter", "cat >/dev/null; echo 0")
        self.command("ubus", 'case "$3" in list) echo mu300dash;; call) echo \'{}\';; *) exit 1;; esac')
        self.command("df", "printf 'header\\nfs 8192 4096 4096 50%% /\\n'")
        self.command("sha256sum", 'python3 -c \'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())\' "$1"')
        self.command("sh", f'printf "%s\\n" "${{1##*/}}" >> "{self.installed}"')
        self.model = self.root / "opt/mu300/bin/mu300-device"
        self.model.parent.mkdir(parents=True)
        self.model.write_text("#!/bin/sh\necho f50\n")
        self.model.chmod(0o755)

    def command(self, name, body):
        path = self.commands / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def run_launcher(self, *arguments):
        return subprocess.run(
            ["/bin/sh", "-s", "--", *map(str, arguments)], input=self.launcher.read_text(),
            env={**os.environ, "PATH": f"{self.commands}:{os.environ['PATH']}"},
            text=True, capture_output=True, timeout=10,
        )

    def assert_preflight(self, verdict):
        result = self.run_launcher("--preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"UULINK_PREFLIGHT={verdict}\n")
        self.assertFalse(self.installed.exists())

    def test_preflight_confirms_missing_without_staging_or_installing(self):
        self.assert_preflight("missing")
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_missing_rpc_status_is_not_treated_as_missing_plugin(self):
        self.command("ubus", "echo mu300dash; exit 1")
        self.assert_preflight("unknown")

    def test_registered_service_blocks_install_even_without_files(self):
        self.command("ubus", "printf 'mu300dash\\nuulink\\n'")
        self.assert_preflight("present")

    def test_dangling_symlink_blocks_install(self):
        self.sampler.parent.mkdir()
        self.sampler.symlink_to(self.root / "missing-target")
        self.assert_preflight("present")

    def test_unsupported_hardware_and_low_space_use_manual_path(self):
        self.model.write_text("#!/bin/sh\necho v50\n")
        self.assert_preflight("unsupported")
        self.model.write_text("#!/bin/sh\necho u30air\n")
        self.command("df", "printf 'header\\nfs 8192 8191 1 99%% /\\n'")
        self.assert_preflight("space")

    def test_running_install_is_not_disrupted(self):
        self.lock.mkdir()
        self.assert_preflight("busy")
        result = self.run_launcher("--install", ARCHIVE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "UULINK_INSTALL=busy\n")
        self.assertTrue(self.lock.exists())

    def test_refuses_file_created_after_preflight_inside_install_lock(self):
        self.assert_preflight("missing")
        self.sampler.parent.mkdir()
        self.command("mkdir", f'/bin/mkdir "$@" && touch "{self.sampler}"')
        result = self.run_launcher("--install", ARCHIVE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "UULINK_INSTALL=present\n")
        self.assertFalse(self.installed.exists())
        self.assertTrue(self.sampler.exists())
        self.assertFalse(self.lock.exists())

    def test_exact_published_archive_runs_only_initial_installer(self):
        self.assertEqual(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), ARCHIVE_SHA256)
        for model in ("u30air", "f50"):
            with self.subTest(model=model):
                self.model.write_text(f"#!/bin/sh\necho {model}\n")
                self.installed.write_text("")
                result = self.run_launcher("--install", ARCHIVE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "UULINK_INSTALL=success\n")
                self.assertEqual(self.installed.read_text(), "install.sh\n")
                self.assertEqual(list(self.tmp.iterdir()), [])

    def test_app_installer_does_not_replace_existing_sampler(self):
        self.sampler.parent.mkdir()
        existing = (AGENT / "files/usr/libexec/uulink/sampler.uc").read_bytes()
        self.sampler.write_bytes(existing)
        self.assert_preflight("present")
        result = self.run_launcher("--install", ARCHIVE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "UULINK_INSTALL=present\n")
        self.assertEqual(self.sampler.read_bytes(), existing)
        self.assertFalse(self.installed.exists())

    def test_altered_archive_stops_before_lock_and_write(self):
        tampered = self.root / "tampered.tar.gz"
        tampered.write_bytes(ARCHIVE.read_bytes() + b"tampered")
        result = self.run_launcher("--install", tampered)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.installed.exists())
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
