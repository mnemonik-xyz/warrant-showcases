"""Tests for scripts/fetch_core.py. A local HTTP server plays the part of the GitHub release."""

import functools
import hashlib
import http.server
import importlib.util
import io
import json
import os
import platform
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_core.py"
spec = importlib.util.spec_from_file_location("fetch_core", SCRIPT)
fetch_core = importlib.util.module_from_spec(spec)
sys.modules["fetch_core"] = fetch_core
spec.loader.exec_module(fetch_core)

VERSION = "0.1.0"
TAG = "core-v0.1.0"
REPO = "owner/core"


def make_tar(members: dict[str, bytes], *, prefix: str = "") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass


class FetchCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.web = tmp / "web"
        self.release_dir = self.web / REPO / "releases" / "download" / TAG
        self.release_dir.mkdir(parents=True)
        self.core = tmp / "core"
        self.lock_path = tmp / "core.lock"

        self.assets = {
            fetch_core.tools_asset(VERSION): make_tar(
                {"bin/warrant-policy": b"policy", "bin/warrant-evidence": b"evidence"}
            ),
            fetch_core.host_asset(VERSION): make_tar({"bin/warrant-host": b"host"}),
            fetch_core.contracts_asset(VERSION): make_tar(
                {"TaskEscrow.json": b'{"abi": [], "bytecode": "0x00"}'}, prefix="./"
            ),
        }
        for name, data in self.assets.items():
            (self.release_dir / name).write_bytes(data)

        handler = functools.partial(QuietHandler, directory=str(self.web))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        env = {
            "WARRANT_CORE_BASE_URL": f"http://127.0.0.1:{self.server.server_address[1]}",
            "WARRANT_CORE_DIR": str(self.core),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        lock_patch = mock.patch.object(fetch_core, "LOCK", self.lock_path)
        lock_patch.start()
        self.addCleanup(lock_patch.stop)

    def write_lock(self, digests: dict[str, str] | None = None) -> None:
        digests = digests or {name: sha(data) for name, data in self.assets.items()}
        self.lock_path.write_text(json.dumps({"repo": REPO, "tag": TAG, "assets": digests}))

    def test_fetch_installs_binaries_and_contracts(self):
        self.write_lock()
        self.assertEqual(fetch_core.main(["fetch"]), 0)
        self.assertEqual((self.core / "bin" / "warrant-policy").read_bytes(), b"policy")
        self.assertTrue(os.access(self.core / "bin" / "warrant-evidence", os.X_OK))
        self.assertTrue((self.core / "contracts" / "TaskEscrow.json").is_file())
        if platform.system() == "Linux" and platform.machine() == "x86_64":
            self.assertEqual((self.core / "bin" / "warrant-host").read_bytes(), b"host")
        self.assertEqual(fetch_core.main(["verify"]), 0)

    def test_fetch_refuses_a_checksum_mismatch_and_installs_nothing(self):
        digests = {name: sha(data) for name, data in self.assets.items()}
        digests[fetch_core.tools_asset(VERSION)] = "0" * 64
        self.write_lock(digests)
        self.assertEqual(fetch_core.main(["fetch"]), 1)
        self.assertFalse((self.core / "bin").exists())

    def test_fetch_refuses_an_archive_that_escapes_the_target(self):
        evil = make_tar({"x": b"owned"}, prefix="../../")
        (self.release_dir / fetch_core.contracts_asset(VERSION)).write_bytes(evil)
        digests = {name: sha(data) for name, data in self.assets.items()}
        digests[fetch_core.contracts_asset(VERSION)] = sha(evil)
        self.write_lock(digests)
        self.assertEqual(fetch_core.main(["fetch"]), 1)
        self.assertFalse((Path(self.tmp.name) / "x").exists())

    def test_verify_fails_when_the_lock_changes_after_a_fetch(self):
        self.write_lock()
        fetch_core.main(["fetch"])
        lock = json.loads(self.lock_path.read_text())
        lock["tag"] = "core-v0.1.1"
        self.lock_path.write_text(json.dumps(lock))
        self.assertEqual(fetch_core.main(["verify"]), 1)

    def test_lock_writes_the_release_digests(self):
        sums = {name: sha(data) for name, data in self.assets.items()}
        for target in sorted(set(fetch_core.TOOLS_TARGETS.values())):
            name = f"warrant-tools-{VERSION}-{target}.tar.gz"
            sums.setdefault(name, "a" * 64)
        manifest = json.dumps(
            {
                "version": VERSION,
                "commit": "c" * 40,
                "image_ids": {"task": "0x01", "invoice": "0x02", "solver": "0x03"},
                "toolchain": {"rust": "1.88.0"},
                "deployed_code_hashes": {"TaskEscrow": "0x04"},
            }
        ).encode()
        sums["core-manifest.json"] = sha(manifest)
        (self.release_dir / "core-manifest.json").write_bytes(manifest)
        (self.release_dir / "SHA256SUMS").write_text("".join(f"{d}  {n}\n" for n, d in sums.items()))
        self.assertEqual(fetch_core.main(["lock", TAG, "--repo", REPO]), 0)
        lock = json.loads(self.lock_path.read_text())
        self.assertEqual(lock["tag"], TAG)
        self.assertEqual(lock["image_ids"]["task"], "0x01")
        self.assertEqual(lock["assets"][fetch_core.contracts_asset(VERSION)], sums[fetch_core.contracts_asset(VERSION)])

    def test_lock_refuses_a_manifest_that_does_not_match_the_sums(self):
        (self.release_dir / "core-manifest.json").write_bytes(b'{"version": "0.1.0"}')
        (self.release_dir / "SHA256SUMS").write_text(f"{'b' * 64}  core-manifest.json\n")
        self.assertEqual(fetch_core.main(["lock", TAG, "--repo", REPO]), 1)

    def test_a_base_url_that_is_not_http_is_refused(self):
        self.write_lock()
        with mock.patch.dict(os.environ, {"WARRANT_CORE_BASE_URL": "file:///etc"}):
            self.assertEqual(fetch_core.main(["fetch"]), 1)

    def test_invalid_tag_is_rejected(self):
        self.assertEqual(fetch_core.main(["lock", "v1; rm -rf /", "--repo", REPO]), 1)


if __name__ == "__main__":
    unittest.main()
