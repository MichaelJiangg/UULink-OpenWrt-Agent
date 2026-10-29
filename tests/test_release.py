"""Offline checks for the UULink OpenWrt release artifacts."""

from __future__ import annotations

import hashlib
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[1]
BUILDER = AGENT_DIR / "build-release.py"
VERSION = "v0.1.0-rc.1"
REPO = "MichaelJiangg/UULink-OpenWrt-Agent"
ARCHIVE_NAME = f"uulink-agent-{VERSION}.tar.gz"
EXPECTED_FILES = {
    "uulink-agent/README.md",
    "uulink-agent/LICENSE",
    "uulink-agent/install.sh",
    "uulink-agent/upgrade.sh",
    "uulink-agent/files/etc/init.d/uulink",
    "uulink-agent/files/usr/libexec/uulink/sampler.uc",
    "uulink-agent/files/usr/share/rpcd/acl.d/uulink.json",
    "uulink-agent/files/usr/share/rpcd/ucode/uulink.uc",
}
SHELL_FILES = {
    "uulink-agent/install.sh",
    "uulink-agent/upgrade.sh",
    "uulink-agent/files/etc/init.d/uulink",
}
FORBIDDEN_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"github_pat_",
    b"ghp_",
    b"UULink-iOS-Source",
    b"/Users/",
)


class ReleaseArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch = tempfile.TemporaryDirectory(prefix="uulink-release-test-")
        root = Path(cls.scratch.name)
        cls.outputs = [root / "build-a", root / "build-b"]
        for output in cls.outputs:
            result = subprocess.run(
                [
                    "python3",
                    str(BUILDER),
                    "--version",
                    VERSION,
                    "--repo",
                    REPO,
                    "--output",
                    str(output),
                ],
                cwd=AGENT_DIR,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise AssertionError(f"release build failed:\n{result.stdout}\n{result.stderr}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.scratch.cleanup()

    def test_repeated_builds_are_byte_identical(self) -> None:
        for name in ("setup.sh", ARCHIVE_NAME, "SHA256SUMS"):
            with self.subTest(name=name):
                first = (self.outputs[0] / name).read_bytes()
                second = (self.outputs[1] / name).read_bytes()
                self.assertEqual(first, second)

    def test_archive_is_limited_to_agent_files(self) -> None:
        with tarfile.open(self.outputs[0] / ARCHIVE_NAME, "r:gz") as archive:
            files = set()
            for member in archive.getmembers():
                name = member.name.rstrip("/")
                parts = Path(name).parts
                self.assertFalse(name.startswith("/"), name)
                self.assertNotIn("..", parts, name)
                self.assertEqual(parts[0], "uulink-agent", name)
                self.assertFalse(member.issym() or member.islnk(), name)
                self.assertTrue(member.isfile() or member.isdir(), name)
                if member.isfile():
                    files.add(name)
            self.assertEqual(files, EXPECTED_FILES)

    def test_checksum_manifest_matches_archive(self) -> None:
        output = self.outputs[0]
        entries = {}
        for line in (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            digest, name = line.split(maxsplit=1)
            entries[name.lstrip("* ")] = digest
        digest = hashlib.sha256((output / ARCHIVE_NAME).read_bytes()).hexdigest()
        self.assertEqual(entries.get(ARCHIVE_NAME), digest)
        setup_digest = hashlib.sha256((output / "setup.sh").read_bytes()).hexdigest()
        self.assertEqual(entries.get("setup.sh"), setup_digest)

    def test_verify_only_accepts_valid_archive_and_rejects_tampering(self) -> None:
        output = self.outputs[0]
        setup = output / "setup.sh"
        archive = output / ARCHIVE_NAME
        valid = subprocess.run(
            ["sh", str(setup), "--verify-only", str(archive)],
            cwd=output,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

        tampered_dir = Path(self.scratch.name) / "tampered"
        tampered_dir.mkdir()
        tampered = tampered_dir / ARCHIVE_NAME
        payload = bytearray(archive.read_bytes())
        payload[-1] ^= 1
        tampered.write_bytes(payload)
        invalid = subprocess.run(
            ["sh", str(setup), "--verify-only", str(tampered)],
            cwd=output,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(invalid.returncode, 0)

    def test_release_shell_scripts_have_valid_syntax(self) -> None:
        setup = subprocess.run(
            ["sh", "-n", str(self.outputs[0] / "setup.sh")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(setup.returncode, 0, setup.stderr)
        with tarfile.open(self.outputs[0] / ARCHIVE_NAME, "r:gz") as archive:
            for name in SHELL_FILES:
                with self.subTest(name=name):
                    stream = archive.extractfile(name)
                    self.assertIsNotNone(stream)
                    checked = subprocess.run(
                        ["sh", "-n"],
                        input=stream.read(),
                        capture_output=True,
                    )
                    self.assertEqual(checked.returncode, 0, checked.stderr.decode(errors="replace"))

    def test_release_excludes_credentials_and_private_app_sources(self) -> None:
        output = self.outputs[0]
        forbidden_names = re.compile(
            r"(^|/)(\.env[^/]*|id_rsa|[^/]*\.(?:pem|p12|key)|App|Shared|Tests|[^/]*\.xcodeproj)(/|$)",
            re.IGNORECASE,
        )
        with tarfile.open(output / ARCHIVE_NAME, "r:gz") as archive:
            for member in archive.getmembers():
                self.assertIsNone(forbidden_names.search(member.name), member.name)
                if member.isfile():
                    stream = archive.extractfile(member)
                    self.assertIsNotNone(stream)
                    payload = stream.read()
                    for marker in FORBIDDEN_MARKERS:
                        with self.subTest(name=member.name, marker=marker):
                            self.assertNotIn(marker, payload)
        for name in ("setup.sh", ARCHIVE_NAME, "SHA256SUMS"):
            payload = (output / name).read_bytes()
            for marker in FORBIDDEN_MARKERS:
                with self.subTest(name=name, marker=marker):
                    self.assertNotIn(marker, payload)


if __name__ == "__main__":
    unittest.main()
