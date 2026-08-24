"""Portable ZIP 更新的安全 staging 與內容驗證。"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from utils.security import verify_file_sha256


MAX_ARCHIVE_FILES = 20_000
MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
REQUIRED_CURRENT_FILES = (
    "app.py",
    "ui.py",
    "version.txt",
    "runtime/python.exe",
    "runtime/pythonw.exe",
)
REQUIRED_ROOT_FILES = ("啟動程式.bat", "auto_update.ps1", "SHA256SUMS.txt")


def _safe_member_parts(name: str) -> tuple[str, ...]:
    normalized = str(name or "").replace("\\", "/")
    if not normalized or normalized.startswith(("/", "//")):
        raise ValueError(f"ZIP 含有無效或絕對路徑：{name!r}")
    pure = PurePosixPath(normalized)
    parts = tuple(part for part in pure.parts if part not in ("", "."))
    if not parts or ".." in parts or ":" in parts[0]:
        raise ValueError(f"ZIP 含有路徑穿越或磁碟機路徑：{name!r}")
    return parts


def _is_link(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filesystem_path(path: Path) -> Path:
    """Windows 深層相依路徑使用 extended path，避開傳統 MAX_PATH。"""
    value = str(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        return Path("\\\\?\\" + value)
    return path


def _verify_manifest(package_root: Path) -> None:
    manifest = package_root / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise ValueError("更新包缺少 SHA256SUMS.txt")
    for raw_line in manifest.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            expected, relative = line.split(maxsplit=1)
        except ValueError as exc:
            raise ValueError(f"SHA256SUMS.txt 格式錯誤：{line!r}") from exc
        relative = relative.lstrip("*")
        parts = _safe_member_parts(relative)
        target = package_root.joinpath(*parts).resolve()
        filesystem_target = _filesystem_path(target)
        if package_root.resolve() not in target.parents or not filesystem_target.is_file():
            raise ValueError(f"雜湊清單指向不存在或越界檔案：{relative}")
        if not verify_file_sha256(filesystem_target, expected):
            raise ValueError(f"更新包內檔案雜湊不符：{relative}")


def stage_portable_zip(
    archive_path: str | Path,
    install_dir: str | Path,
    expected_version: str,
) -> tuple[Path, Path]:
    """安全解壓並驗證更新包，回傳 ``(staging_dir, staged_current)``。"""
    archive = Path(archive_path).resolve()
    root = Path(install_dir).resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"找不到更新包：{archive}")
    root.mkdir(parents=True, exist_ok=True)
    # 不在 staging 內重建冗長的發行頂層名稱，降低 Windows 深層路徑長度。
    staging = root / f".u_{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    seen: set[str] = set()
    top_level: str | None = None

    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise ValueError("更新包檔案數超過安全上限")
            if sum(max(info.file_size, 0) for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("更新包解壓大小超過安全上限")

            for info in infos:
                parts = _safe_member_parts(info.filename)
                if top_level is None:
                    top_level = parts[0]
                elif parts[0].casefold() != top_level.casefold():
                    raise ValueError("更新包必須只包含一個頂層發行資料夾")

                relative_parts = parts[1:]
                if not relative_parts:
                    continue
                key = "/".join(part.casefold() for part in relative_parts)
                if key in seen:
                    raise ValueError(f"ZIP 含有重複路徑：{info.filename}")
                seen.add(key)
                if _is_link(info):
                    raise ValueError(f"ZIP 不允許 symbolic link：{info.filename}")
                destination = staging.joinpath(*relative_parts).resolve()
                if staging.resolve() not in destination.parents:
                    raise ValueError(f"ZIP 項目超出 staging：{info.filename}")
                filesystem_destination = _filesystem_path(destination)
                if info.is_dir():
                    filesystem_destination.mkdir(parents=True, exist_ok=True)
                    continue
                filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, filesystem_destination.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

        if not top_level:
            raise ValueError("更新包必須只包含一個頂層發行資料夾")
        package_root = staging
        for relative in REQUIRED_ROOT_FILES:
            if not (package_root / relative).is_file():
                raise ValueError(f"更新包缺少必要檔案：{relative}")
        current = package_root / "current"
        for relative in REQUIRED_CURRENT_FILES:
            if not (current / Path(relative)).is_file():
                raise ValueError(f"更新包缺少必要檔案：current/{relative}")

        actual_version = (current / "version.txt").read_text(encoding="utf-8-sig").strip()
        if actual_version.upper() != str(expected_version).strip().upper():
            raise ValueError(
                f"更新包版本不符：預期 {expected_version}，實際 {actual_version}"
            )
        _verify_manifest(package_root)
        return staging, current
    except Exception:
        shutil.rmtree(_filesystem_path(staging), ignore_errors=True)
        raise


def archive_sha256(path: str | Path) -> str:
    return _sha256(Path(path))
