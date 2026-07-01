"""Download and install FFmpeg into the app ffmpeg/ folder (Windows)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from app.paths import ffmpeg_dir, ffmpeg_path, ffprobe_path

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

FFMPEG_ASSET_NAME = "ffmpeg-master-latest-win64-gpl.zip"
FFMPEG_ZIP_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    + FFMPEG_ASSET_NAME
)
_GITHUB_API_LATEST = (
    "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest"
)
_USER_AGENT = "DCVideoSplitter"


def ffmpeg_available() -> bool:
    return ffmpeg_path().is_file() and ffprobe_path().is_file()


def _urllib_https_works() -> bool:
    try:
        import ssl  # noqa: F401
    except ImportError:
        return False
    handlers = urllib.request.build_opener().handlers
    return any(handler.__class__.__name__ == "HTTPSHandler" for handler in handlers)


def _resolve_download_url() -> str:
    if not _urllib_https_works():
        return FFMPEG_ZIP_URL
    try:
        req = urllib.request.Request(
            _GITHUB_API_LATEST,
            headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        for asset in data.get("assets", []):
            if asset.get("name") == FFMPEG_ASSET_NAME:
                url = asset.get("browser_download_url")
                if url:
                    return str(url)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        pass
    return FFMPEG_ZIP_URL


def _download_file_urllib(
    url: str,
    dest: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        block = 1024 * 256
        with dest.open("wb") as out:
            while True:
                chunk = resp.read(block)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if on_progress and total > 0:
                    pct = min(100, downloaded * 100 // total)
                    on_progress(f"Downloading FFmpeg… {pct}%")
                elif on_progress and downloaded and downloaded % (block * 8) == 0:
                    mb = downloaded // (1024 * 1024)
                    on_progress(f"Downloading FFmpeg… {mb} MB")


def _download_file_curl(
    url: str,
    dest: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    if on_progress:
        on_progress("Downloading FFmpeg… (via curl)")
    result = subprocess.run(
        ["curl.exe", "-fL", "--retry", "3", "-o", str(dest), url],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"curl failed (exit {result.returncode})")


def _download_file_powershell(
    url: str,
    dest: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    if on_progress:
        on_progress("Downloading FFmpeg… (via PowerShell)")
    script = (
        "$ProgressPreference = 'SilentlyContinue'; "
        f"Invoke-WebRequest -Uri '{url}' -OutFile '{dest}' -UseBasicParsing"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"PowerShell download failed (exit {result.returncode})")


def _download_file(
    url: str,
    dest: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    if _urllib_https_works():
        try:
            _download_file_urllib(url, dest, on_progress)
            return
        except urllib.error.URLError as exc:
            if "unknown url type" not in str(exc).lower():
                raise

    if sys.platform == "win32":
        try:
            _download_file_curl(url, dest, on_progress)
            return
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
        _download_file_powershell(url, dest, on_progress)
        return

    raise RuntimeError(
        "HTTPS download is not available in this build. "
        "Install ffmpeg.exe and ffprobe.exe manually into the ffmpeg folder."
    )


def _find_ffmpeg_binaries(root: Path) -> tuple[Path, Path]:
    for candidate in root.rglob("ffmpeg.exe"):
        ffprobe = candidate.parent / "ffprobe.exe"
        if ffprobe.is_file():
            return candidate, ffprobe
    raise FileNotFoundError("ffmpeg.exe and ffprobe.exe not found in the downloaded archive")


def download_ffmpeg(on_progress: Callable[[str], None] | None = None) -> None:
    """Download BtbN win64 GPL FFmpeg and install into ffmpeg/."""
    if ffmpeg_available():
        return

    target_dir = ffmpeg_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    url = _resolve_download_url()
    if on_progress:
        on_progress("Downloading FFmpeg…")

    with tempfile.TemporaryDirectory(prefix="dcvs-ffmpeg-") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / FFMPEG_ASSET_NAME
        _download_file(url, zip_path, on_progress)

        if on_progress:
            on_progress("Extracting FFmpeg…")

        extract_root = tmp_path / "extract"
        extract_root.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_root)

        src_ffmpeg, src_ffprobe = _find_ffmpeg_binaries(extract_root)
        shutil.copy2(src_ffmpeg, ffmpeg_path())
        shutil.copy2(src_ffprobe, ffprobe_path())

        license_src = src_ffmpeg.parent / "LICENSE.txt"
        if license_src.is_file():
            shutil.copy2(license_src, target_dir / "LICENSE.txt")

    if not ffmpeg_available():
        raise RuntimeError("FFmpeg install finished but binaries are still missing")
