"""Path resolution for dev and PyInstaller frozen builds."""

from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    """Project root in dev; folder containing the .exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_dir() -> Path:
    """PyInstaller extract dir when frozen; project root in dev."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", bundle_root()))
    return bundle_root()


def ffmpeg_dir() -> Path:
    """External ffmpeg/ folder beside the project or exe (not inside _internal)."""
    return bundle_root() / "ffmpeg"


def ffmpeg_path() -> Path:
    return ffmpeg_dir() / "ffmpeg.exe"


def ffprobe_path() -> Path:
    return ffmpeg_dir() / "ffprobe.exe"
