"""Unit tests for profile helpers (limits, estimates, naming)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.profiles import (
    descriptive_output_stem,
    effective_limit_bytes,
    ensure_valid_bitrate_mode,
    estimate_split_parts,
    resolution_is_available,
    safety_padding,
    source_video_bitrate_kbps,
)


@pytest.mark.parametrize(
    ("limit_mb", "expected_padding"),
    [
        (10, 0.12),
        (25, 0.10),
        (100, 0.08),
        (500, 0.03),
    ],
)
def test_safety_padding(limit_mb: float, expected_padding: float) -> None:
    assert safety_padding(limit_mb) == expected_padding


def test_effective_limit_bytes_under_raw_limit() -> None:
    limit_mb = 100.0
    eff = effective_limit_bytes(limit_mb)
    raw = int(limit_mb * 1024 * 1024)
    assert eff < raw
    assert eff == int(raw * (1 - safety_padding(limit_mb)))


@pytest.mark.parametrize(
    ("file_size", "limit_mb", "expected_parts"),
    [
        (50 * 1024 * 1024, 100, 1),
        (200 * 1024 * 1024, 100, 3),
        (0, 100, 1),
    ],
)
def test_estimate_split_parts(
    file_size: int, limit_mb: float, expected_parts: int
) -> None:
    assert estimate_split_parts(file_size, limit_mb) == expected_parts


def test_descriptive_output_stem_compress() -> None:
    stem = descriptive_output_stem(
        "clip",
        "1080p",
        1080,
        "compress",
        "hevc",
        "balanced",
    )
    assert stem == "clip_1080p_hevc_balanced"


def test_descriptive_output_stem_split() -> None:
    stem = descriptive_output_stem(
        "clip",
        "original",
        2160,
        "split",
        "h264",
        "balanced",
    )
    assert stem == "clip_4k_split_split"


def test_resolution_is_available_no_upscale() -> None:
    assert resolution_is_available("720p", 720) is True
    assert resolution_is_available("1080p", 720) is False
    assert resolution_is_available("original", 480) is True


def test_ensure_valid_bitrate_mode_falls_back_to_source() -> None:
    mode = ensure_valid_bitrate_mode(
        "1080p",
        "hevc",
        source_video_kbps=800,
        source_height=1080,
        bitrate_mode="super_high",
    )
    assert mode == "source"


def test_source_video_bitrate_kbps_from_bitrate() -> None:
    assert source_video_bitrate_kbps(10_000_000, 60.0, 0) == 9872
