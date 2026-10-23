#!/usr/bin/env python3
"""Download, verify and pin the Warrant core release.

The showcases need compiled outputs of the policy-execution repository: the helper binaries
and the compiled contracts. They take them from one pinned GitHub release. core.lock names
the release and the SHA-256 of every asset.

    python scripts/fetch_core.py fetch              # download and verify into .core/
    python scripts/fetch_core.py verify             # check the files in .core/ against core.lock
    python scripts/fetch_core.py lock core-v0.1.0   # write core.lock from a published release

`lock` reads SHA256SUMS and core-manifest.json from the release. That trusts the release once,
so review the resulting core.lock diff before you commit it. `fetch` never trusts the release:
it checks every download against core.lock and stops on a mismatch.

The tools archive is chosen by platform. warrant-host exists for linux x86_64 only.
Environment: WARRANT_CORE_DIR sets the target directory (default .core in the repository root),
WARRANT_CORE_BASE_URL replaces https://github.com (used by the tests).
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "core.lock"
SOURCE_REPO = "mnemonik-xyz/policy-execution"
TAG_RE = re.compile(r"^core-v[0-9]+\.[0-9]+\.[0-9]+([.-]?[a-z0-9]+)*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# Release asset name patterns. {v} is the version without the core-v prefix.
TOOLS_TARGETS = {
    ("Linux", "x86_64"): "x86_64-unknown-linux-musl",
    ("Linux", "aarch64"): "aarch64-unknown-linux-musl",
    ("Linux", "arm64"): "aarch64-unknown-linux-musl",
    ("Darwin", "arm64"): "aarch64-apple-darwin",
}
HOST_TARGET = "x86_64-unknown-linux-gnu"


class CoreError(Exception):
    pass


def core_dir() -> Path:
    override = os.environ.get("WARRANT_CORE_DIR")
    return Path(override).expanduser() if override else ROOT / ".core"


def base_url() -> str:
    return os.environ.get("WARRANT_CORE_BASE_URL", "https://github.com").rstrip("/")


def asset_url(repo: str, tag: str, name: str) -> str:
    return f"{base_url()}/{repo}/releases/download/{tag}/{name}"


def download(url: str) -> bytes:
    if not url.startswith(("https://", "http://")):
        raise CoreError(f"Refusing a URL that is not http or https: {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise CoreError(f"Could not download {url}: {exc}") from exc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tools_asset(version: str) -> str:
    key = (platform.system(), platform.machine())
    target = TOOLS_TARGETS.get(key)
    if target is None:
        raise CoreError(f"No tools archive for {key[0]} {key[1]}. Supported: {sorted(TOOLS_TARGETS)}")
    return f"warrant-tools-{version}-{target}.tar.gz"


def host_asset(version: str) -> str:
    return f"warrant-host-{version}-{HOST_TARGET}.tar.gz"


def contracts_asset(version: str) -> str:
    return f"warrant-contracts-{version}.tar.gz"


def read_lock() -> dict:
    if not LOCK.is_file():
        raise CoreError("core.lock does not exist. Run: python scripts/fetch_core.py lock <tag>")
    lock = json.loads(LOCK.read_text())
    tag = lock.get("tag", "")
    if not TAG_RE.match(tag):
        raise CoreError(f"core.lock has an invalid tag: {tag!r}")
    for name, digest in lock.get("assets", {}).items():
        if not SHA_RE.match(digest) or "/" in name:
            raise CoreError(f"core.lock has an invalid entry for {name!r}")
    return lock


def safe_extract(archive: bytes, dest: Path) -> list[str]:
    """Extract a .tar.gz of plain files. Refuse links, devices and paths outside dest."""
    names = []
    with tempfile.TemporaryFile() as handle:
        handle.write(archive)
        handle.seek(0)
        with tarfile.open(fileobj=handle, mode="r:gz") as tar:
            for member in tar.getmembers():
                target = (dest / member.name).resolve()
                if not (member.isfile() or member.isdir()) or dest.resolve() not in (target, *target.parents):
                    raise CoreError(f"Refusing unsafe archive member: {member.name}")
            tar.extractall(dest, filter="data")
            names = [m.name for m in tar.getmembers() if m.isfile()]
    return names


def wanted_assets(lock: dict, only_host: bool) -> list[str]:
    version = lock["tag"].removeprefix("core-v")
    wanted = [tools_asset(version)]
    if platform.system() == "Linux" and platform.machine() == "x86_64":
        wanted.append(host_asset(version))
    elif only_host:
        raise CoreError("warrant-host is published for linux x86_64 only")
    wanted.append(contracts_asset(version))
    return wanted


def fetch(args: argparse.Namespace) -> int:
    lock = read_lock()
    dest = core_dir()
    dest.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="core-", dir=dest))
    try:
        for name in wanted_assets(lock, only_host=False):
            expected = lock["assets"].get(name)
            if not expected:
                raise CoreError(f"core.lock has no checksum for {name}")
            data = download(asset_url(lock.get("repo", SOURCE_REPO), lock["tag"], name))
            if sha256(data) != expected:
                raise CoreError(f"Checksum mismatch for {name}: expected {expected}, got {sha256(data)}")
            subdir = "contracts" if name.startswith("warrant-contracts-") else "."
            (staging / subdir).mkdir(parents=True, exist_ok=True)
            safe_extract(data, staging / subdir)
            print(f"ok  {name}")
        for part in ("bin", "contracts"):
            if (staging / part).exists():
                target = dest / part
                target.mkdir(parents=True, exist_ok=True)
                for item in (staging / part).iterdir():
                    shutil.move(str(item), str(target / item.name))
                    if part == "bin":
                        (target / item.name).chmod(0o755)
        (dest / "core.lock.fetched").write_text(LOCK.read_text())
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"Core {lock['tag']} is in {dest}")
    return 0


def verify(args: argparse.Namespace) -> int:
    lock = read_lock()
    fetched = core_dir() / "core.lock.fetched"
    if not fetched.is_file() or json.loads(fetched.read_text()) != lock:
        raise CoreError("The files in .core do not come from the current core.lock. Run: fetch")
    bin_dir = core_dir() / "bin"
    missing = [b for b in ("warrant-policy", "warrant-evidence") if not (bin_dir / b).is_file()]
    if missing:
        raise CoreError(f"Missing binaries in {bin_dir}: {missing}")
    print(f"Core {lock['tag']} matches core.lock")
    return 0


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and SHA_RE.match(parts[0]):
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def lock_release(args: argparse.Namespace) -> int:
    tag = args.tag
    if not TAG_RE.match(tag):
        raise CoreError(f"Invalid tag: {tag!r}")
    repo = args.repo
    sums = parse_sums(download(asset_url(repo, tag, "SHA256SUMS")).decode())
    manifest_bytes = download(asset_url(repo, tag, "core-manifest.json"))
    if sums.get("core-manifest.json") != sha256(manifest_bytes):
        raise CoreError("core-manifest.json does not match SHA256SUMS")
    manifest = json.loads(manifest_bytes)
    version = tag.removeprefix("core-v")
    if manifest.get("version") != version:
        raise CoreError(f"core-manifest.json is for version {manifest.get('version')!r}, not {version!r}")
    names = [host_asset(version), contracts_asset(version)]
    names += [f"warrant-tools-{version}-{t}.tar.gz" for t in sorted(set(TOOLS_TARGETS.values()))]
    missing = [n for n in names if n not in sums]
    if missing:
        raise CoreError(f"SHA256SUMS lacks: {missing}")
    lock = {
        "repo": repo,
        "tag": tag,
        "commit": manifest["commit"],
        "assets": {n: sums[n] for n in names},
        "image_ids": manifest["image_ids"],
        "deployed_code_hashes": manifest["deployed_code_hashes"],
        "toolchain": manifest["toolchain"],
    }
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {LOCK.name} for {tag} ({manifest['commit'][:7]}). Review it before you commit.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download and verify the pinned release into .core/").set_defaults(func=fetch)
    sub.add_parser("verify", help="check .core/ against core.lock").set_defaults(func=verify)
    lock_p = sub.add_parser("lock", help="write core.lock from a published release")
    lock_p.add_argument("tag", help="release tag, for example core-v0.1.0")
    lock_p.add_argument("--repo", default=SOURCE_REPO)
    lock_p.set_defaults(func=lock_release)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
