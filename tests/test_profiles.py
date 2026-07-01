"""Unit tests for profile helpers (limits, estimates, naming)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ffmpeg import VideoInfo
from app.profiles import (
    clear_stem_outputs,
    descriptive_output_stem,
    effective_limit_bytes,
    ensure_valid_bitrate_mode,
    estimate_split_parts,
    output_dir_has_existing_files,
    output_would_overwrite_source,
    resolution_is_available,
    safety_padding,
    single_output_filename,
    source_video_bitrate_kbps,
    split_remux_is_redundant,
)


def _video_info(**overrides: object) -> VideoInfo:
    data = {
        "path": Path("clip.mp4"),
        "duration": 60.0,
        "file_size": 1_000_000,
        "width": 1280,
        "height": 720,
        "bitrate": 1_000_000,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_channels": 2,
        "audio_sample_rate": 48_000,
    }
    data.update(overrides)
    return VideoInfo(**data)  # type: ignore[arg-type]


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
        allow_split=True,
    )
    assert stem == "clip_4k_split"


def test_descriptive_output_stem_remux() -> None:
    stem = descriptive_output_stem(
        "clip",
        "original",
        2160,
        "split",
        "h264",
        "balanced",
        allow_split=False,
    )
    assert stem == "clip_4k"


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


def test_output_would_overwrite_source_dont_split_same_folder() -> None:
    source = Path("D:/videos/clip_remux.mp4")
    assert output_would_overwrite_source(
        source,
        Path("D:/videos"),
        "clip",
        "split",
        allow_split=False,
    )


def test_output_would_overwrite_source_split_subfolder_ok() -> None:
    source = Path("D:/videos/clip.mp4")
    assert not output_would_overwrite_source(
        source,
        Path("D:/videos/clip_discord_parts"),
        "clip",
        "split",
        allow_split=True,
    )


def test_output_would_overwrite_source_part_file_in_output_dir() -> None:
    source = Path("D:/videos/out/clip_part002.mp4")
    assert output_would_overwrite_source(
        source,
        Path("D:/videos/out"),
        "clip",
        "split",
        allow_split=True,
    )


def test_output_would_overwrite_source_mov_in_same_folder_ok() -> None:
    source = Path("D:/videos/clip.mov")
    assert not output_would_overwrite_source(
        source,
        Path("D:/videos"),
        "clip",
        "split",
        allow_split=False,
    )


def test_single_output_filename() -> None:
    assert single_output_filename("clip", "split") == "clip_remux.mp4"
    assert single_output_filename("clip", "compress") == "clip_compressed.mp4"


def test_output_dir_has_existing_files_ignores_source_mp4(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    assert not output_dir_has_existing_files(tmp_path, "clip", exclude=source)


def test_clear_stem_outputs_never_deletes_source(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    prior = tmp_path / "clip_remux.mp4"
    prior.write_bytes(b"old output")
    removed = clear_stem_outputs(tmp_path, "clip", exclude=source)
    assert removed == 1
    assert source.exists()
    assert not prior.exists()


def test_split_remux_is_redundant_h264_mp4() -> None:
    assert split_remux_is_redundant(_video_info())


def test_split_remux_is_redundant_mov_container() -> None:
    assert not split_remux_is_redundant(_video_info(path=Path("clip.mov")))


def test_split_remux_is_redundant_hevc_mp4() -> None:
    assert not split_remux_is_redundant(_video_info(video_codec="hevc"))


def test_split_remux_is_redundant_audio_reencode() -> None:
    assert not split_remux_is_redundant(
        _video_info(audio_codec="ac3", audio_channels=2, audio_sample_rate=48_000)
    )
