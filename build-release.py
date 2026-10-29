#!/usr/bin/env python3
"""Build a deterministic, standalone UULink OpenWrt release bundle."""

import argparse
import gzip
import hashlib
import io
import re
import tarfile
from pathlib import Path


SOURCE = Path(__file__).resolve().parent
FILES = (
    "README.md",
    "LICENSE",
    "install.sh",
    "upgrade.sh",
    "files/etc/init.d/uulink",
    "files/usr/libexec/uulink/sampler.uc",
    "files/usr/share/rpcd/acl.d/uulink.json",
    "files/usr/share/rpcd/ucode/uulink.uc",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_bundle() -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            dirs = {"uulink-agent/"}
            for name in FILES:
                path = Path("uulink-agent") / name
                dirs.update(str(parent).rstrip("/") + "/" for parent in path.parents if str(parent) != ".")
            for name in sorted(dirs, key=lambda item: (item.count("/"), item)):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = 0
                archive.addfile(info)
            for name in FILES:
                source = SOURCE / name
                if not source.is_file() or source.is_symlink():
                    raise ValueError(f"Missing or unsafe source file: {source}")
                content = source.read_bytes()
                info = tarfile.TarInfo(f"uulink-agent/{name}")
                info.size = len(content)
                info.mode = 0o755 if name == "files/etc/init.d/uulink" else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release tag, for example v0.1.0-rc.1")
    parser.add_argument("--repo", required=True, help="GitHub OWNER/REPO for the separate public agent repository")
    parser.add_argument("--output", required=True, type=Path, help="New local release artifact directory")
    args = parser.parse_args()

    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?", args.version):
        parser.error("--version must look like v0.1.0 or v0.1.0-rc.1")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("--repo must be a plain OWNER/REPO name")
    if args.output.exists():
        parser.error("--output must not exist, to avoid overwriting a prior build")

    bundle_name = f"uulink-agent-{args.version}.tar.gz"
    bundle = make_bundle()
    bundle_url = f"https://github.com/{args.repo}/releases/download/{args.version}/{bundle_name}"
    template = (SOURCE / "release-setup.template.sh").read_text(encoding="utf-8")
    setup = (template.replace("@VERSION@", args.version)
                     .replace("@BUNDLE_URL@", bundle_url)
                     .replace("@BUNDLE_SHA256@", digest(bundle))).encode("utf-8")
    if re.search(rb"@[A-Z_]+@", setup):
        raise ValueError("Unexpanded release template placeholder")

    args.output.mkdir(parents=True)
    (args.output / bundle_name).write_bytes(bundle)
    (args.output / "setup.sh").write_bytes(setup)
    checksums = f"{digest(bundle)}  {bundle_name}\n{digest(setup)}  setup.sh\n"
    (args.output / "SHA256SUMS").write_text(checksums, encoding="ascii")
    print(f"Built local release candidate: {args.output}")
    print(f"Bundle SHA-256: {digest(bundle)}")
    setup_url = f"https://github.com/{args.repo}/releases/download/{args.version}/setup.sh"
    print(
        "Proposed command after public release: "
        f"wget -O /tmp/uulink-setup.sh {setup_url} && "
        f"[ \"$(sha256sum /tmp/uulink-setup.sh | cut -d ' ' -f1)\" = \"{digest(setup)}\" ] && "
        "sh /tmp/uulink-setup.sh"
    )


if __name__ == "__main__":
    main()
