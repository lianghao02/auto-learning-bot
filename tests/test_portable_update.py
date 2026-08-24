"""Portable 更新包安全驗證與 Release 資產解析測試。"""

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from ui import parse_release_update
from utils.portable_update import stage_portable_zip


class PortableUpdateTests(unittest.TestCase):
    VERSION = "V9.9.9"

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _make_valid_zip(self, root: Path, version: str | None = None) -> Path:
        version = version or self.VERSION
        files = {
            "啟動程式.bat": b"@echo off\n",
            "auto_update.ps1": b"# updater\n",
            "current/app.py": b"# app\n",
            "current/ui.py": b"# ui\n",
            "current/version.txt": version.encode(),
            "current/runtime/python.exe": b"python",
            "current/runtime/pythonw.exe": b"pythonw",
        }
        manifest = "".join(
            f"{self._digest(content)} *{name}\n" for name, content in files.items()
        ).encode()
        files["SHA256SUMS.txt"] = manifest
        archive = root / "update.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, content in files.items():
                bundle.writestr(f"行政效能領航員_{version}_Portable/{name}", content)
        return archive

    def test_valid_archive_is_staged_under_install_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            install.mkdir()
            archive = self._make_valid_zip(root)
            staging, current = stage_portable_zip(archive, install, self.VERSION)
            self.assertEqual(staging.parent, install)
            self.assertTrue((current / "ui.py").is_file())

    def test_rejects_zip_slip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            install.mkdir()
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("release/../../outside.txt", b"bad")
            with self.assertRaises(ValueError):
                stage_portable_zip(archive, install, self.VERSION)
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            install.mkdir()
            archive = self._make_valid_zip(root, "V1.0.0")
            with self.assertRaisesRegex(ValueError, "版本不符"):
                stage_portable_zip(archive, install, self.VERSION)

    def test_rejects_corrupted_manifest_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "install"
            install.mkdir()
            archive = self._make_valid_zip(root)
            with zipfile.ZipFile(archive) as bundle:
                content = {
                    info.filename: bundle.read(info)
                    for info in bundle.infolist()
                    if not info.is_dir()
                }
            app_name = f"行政效能領航員_{self.VERSION}_Portable/current/app.py"
            content[app_name] = b"tampered\n"
            with zipfile.ZipFile(archive, "w") as bundle:
                for name, value in content.items():
                    bundle.writestr(name, value)
            with self.assertRaises(ValueError):
                stage_portable_zip(archive, install, self.VERSION)

    def test_release_asset_requires_exact_name_and_digest(self):
        digest = "sha256:" + "a" * 64
        data = {
            "tag_name": self.VERSION,
            "body": "## 更新",
            "html_url": "https://github.example/release",
            "assets": [
                {
                    "name": f"AdminEfficiencyPilot_{self.VERSION}_Portable.zip",
                    "browser_download_url": "https://github.example/file.zip",
                    "size": 123,
                    "digest": digest,
                }
            ],
        }
        self.assertEqual(
            parse_release_update(data, "V1.0.0"),
            (self.VERSION, "## 更新", "https://github.example/file.zip", 123, digest),
        )

    def test_missing_digest_forces_manual_release_url(self):
        data = {
            "tag_name": self.VERSION,
            "html_url": "https://github.example/release",
            "assets": [
                {
                    "name": f"AdminEfficiencyPilot_{self.VERSION}_Portable.zip",
                    "browser_download_url": "https://github.example/file.zip",
                    "size": 123,
                }
            ],
        }
        info = parse_release_update(data, "V1.0.0")
        self.assertEqual(info[2], "https://github.example/release")
        self.assertEqual(info[4], "")

    def test_non_hex_digest_forces_manual_release_url(self):
        data = {
            "tag_name": self.VERSION,
            "html_url": "https://github.example/release",
            "assets": [
                {
                    "name": f"AdminEfficiencyPilot_{self.VERSION}_Portable.zip",
                    "browser_download_url": "https://github.example/file.zip",
                    "size": 123,
                    "digest": "sha256:" + "z" * 64,
                }
            ],
        }
        info = parse_release_update(data, "V1.0.0")
        self.assertEqual(info[2], "https://github.example/release")
        self.assertEqual(info[4], "")


if __name__ == "__main__":
    unittest.main()
