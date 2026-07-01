"""Path resolution for dev and PyInstaller frozen builds."""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def ffmpeg_dir() -> Path:
    return app_dir() / "ffmpeg"


def ffmpeg_path() -> Path:
    return ffmpeg_dir() / "ffmpeg.exe"


def ffprobe_path() -> Path:
    return ffmpeg_dir() / "ffprobe.exe"
