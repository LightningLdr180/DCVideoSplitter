"""Resolution presets, bitrate tables, padding, and estimate helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.ffmpeg import VideoInfo

Codec = Literal["h264", "hevc", "av1"]
Resolution = Literal["4k", "1080p", "720p", "original"]
Mode = Literal["split", "compress", "compress_split"]
BitrateMode = Literal["source", "super_high", "high", "balanced", "compact"]

AUDIO_KBPS = 128
MIN_VIDEO_KBPS = 500

# GPU hardware encoders: average target = preset; peaks capped at this multiple.
GPU_VBR_PEAK_FACTOR = 1.5

# NVENC quality tuning (RTX / Quadro).
NVENC_PRESET = "p5"
NVENC_TUNE = "hq"
NVENC_LOOKAHEAD = 24
NVENC_AQ_STRENGTH = 8

HDR_COLOR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67", "smpte428"})

# Wall-clock multipliers on top of baseline _ENCODER_REALTIME_SPEED (quality pipeline).
NVENC_QUALITY_TIME_FACTOR = 1.18
NVENC_MULTIPASS_TIME_FACTOR = 1.75
AMF_PREANALYSIS_TIME_FACTOR = 1.35
QSV_LOOKAHEAD_TIME_FACTOR = 1.08
HDR_10BIT_ENCODE_TIME_FACTOR = 1.12
LANCZOS_DOWNSCALE_TIME_FACTOR = 1.08
ENCODE_TIME_UNCERTAIN_MULTIPLIER = 1.55

DISCORD_CODECS: tuple[Codec, ...] = ("h264", "hevc", "av1")

DISCORD_COPY_CODECS = frozenset({"h264", "hevc", "h265", "av1"})

# AAC in MP4 is what Discord expects; other codecs need re-encode on split.
DISCORD_COPY_AUDIO_CODECS = frozenset({"aac"})


def can_stream_copy_to_mp4(video_codec: str) -> bool:
    return video_codec.lower() in DISCORD_COPY_CODECS


def can_stream_copy_audio_to_mp4(audio_codec: str | None) -> bool:
    if audio_codec is None:
        return True
    return audio_codec.lower() in DISCORD_COPY_AUDIO_CODECS


def audio_stream_copyable(
    audio_codec: str | None,
    channels: int | None = None,
    sample_rate: int | None = None,
) -> bool:
    """True when audio can be stream-copied into MP4 (valid AAC metadata)."""
    if audio_codec is None:
        return True
    if not can_stream_copy_audio_to_mp4(audio_codec):
        return False
    if channels is not None and channels <= 0:
        return False
    if sample_rate is not None and sample_rate <= 0:
        return False
    return True


def is_hevc_codec(video_codec: str) -> bool:
    return video_codec.lower() in ("hevc", "h265")


def gpu_vbr_peak_kbps(target_kbps: int) -> int:
    """Peak cap for GPU VBR (average target × factor, with a small floor above target)."""
    target = max(MIN_VIDEO_KBPS, target_kbps)
    return max(target + 500, int(target * GPU_VBR_PEAK_FACTOR))

CODEC_BITRATES: dict[str, dict[Codec, int]] = {
    "4k": {"h264": 15000, "hevc": 10000, "av1": 8000},
    "1080p": {"h264": 6250, "hevc": 4400, "av1": 3500},
    "720p": {"h264": 3750, "hevc": 2625, "av1": 2125},
}

RESOLUTION_HEIGHT: dict[Resolution, int | None] = {
    "4k": 2160,
    "1080p": 1080,
    "720p": 720,
    "original": None,
}

CODEC_LABELS = {
    "h264": "H.264",
    "hevc": "HEVC",
    "av1": "AV1",
}

BITRATE_MODE_SCALE: dict[BitrateMode, float | None] = {
    "source": None,
    "super_high": 2.5,
    "high": 1.5,
    "balanced": 1.0,
    "compact": 0.75,
}

BITRATE_MODE_LABELS: dict[BitrateMode, str] = {
    "source": "Source",
    "super_high": "Super High",
    "high": "High",
    "balanced": "Balanced",
    "compact": "Compact",
}


def safety_padding(limit_mb: float) -> float:
    if limit_mb >= 200:
        return 0.03
    if limit_mb >= 50:
        return 0.08
    if limit_mb >= 20:
        return 0.10
    return 0.12


def vbr_headroom(limit_mb: float) -> float:
    """Extra multiplier on segment duration for stream-copy VBR spikes."""
    if limit_mb >= 200:
        return 0.97
    if limit_mb >= 50:
        return 0.92
    if limit_mb >= 20:
        return 0.90
    return 0.88


def effective_limit_bytes(limit_mb: float) -> int:
    return int(limit_mb * 1024 * 1024 * (1 - safety_padding(limit_mb)))


def format_bytes(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 ** 3):.1f} GB"
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 ** 2):.0f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes} B"


def format_duration(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# Rough encode speed: source video seconds processed per wall-clock second at 1080p.
_ENCODER_REALTIME_SPEED: dict[str, float] = {
    "h264_nvenc": 12.0,
    "hevc_nvenc": 8.0,
    "av1_nvenc": 5.0,
    "h264_amf": 10.0,
    "hevc_amf": 7.0,
    "av1_amf": 4.0,
    "h264_qsv": 8.0,
    "hevc_qsv": 6.0,
    "av1_qsv": 3.5,
    "libx264": 0.55,
    "libx265": 0.35,
    "libsvtav1": 0.1,
}


def _output_height(resolution: Resolution, source_height: int) -> int:
    target = RESOLUTION_HEIGHT.get(resolution)
    if target is None:
        return source_height
    return min(source_height, target)


def _encode_work_scale(resolution: Resolution, source_height: int) -> float:
    """Relative pixel work vs 1080p output (1.0 = 1080p)."""
    out_h = _output_height(resolution, source_height)
    return max(0.15, (out_h / 1080) ** 1.1)


def estimate_job_duration_seconds(
    duration: float,
    file_size: int,
    mode: Mode,
    resolution: Resolution,
    encoder: str,
    source_height: int,
    *,
    codec: Codec = "hevc",
    gpu_two_pass: bool = False,
    info: VideoInfo | None = None,
) -> float:
    """Rough wall-clock seconds for the job (heuristic, not a guarantee)."""
    if duration <= 0:
        return 0.0
    if mode == "split":
        # Stream-copy / remux: often much faster than realtime.
        return max(duration / 14.0, file_size / (100 * 1024 * 1024), 20.0)

    speed = _ENCODER_REALTIME_SPEED.get(encoder, 0.5)
    work = _encode_work_scale(resolution, source_height)
    effective_speed = max(0.05, speed / work)
    quality_mult = encode_quality_duration_multiplier(
        resolution, source_height, encoder, codec, gpu_two_pass, info
    )
    # verify / segment mux overhead
    return (duration / effective_speed) * 1.12 * quality_mult


def format_time_estimate(
    seconds: float, *, cpu_encoder: bool = False, uncertain: bool = False
) -> str:
    """Human-readable rough duration; wider range for slow or variable encodes."""
    if seconds <= 0:
        return ""
    if (cpu_encoder or uncertain) and seconds >= 60:
        low_factor = 0.72 if uncertain and not cpu_encoder else 0.7
        high_factor = 1.38 if uncertain and not cpu_encoder else 1.45
        low = seconds * low_factor
        high = seconds * high_factor
        return f"~{_format_time_short(low)}–{_format_time_short(high)}"
    return f"~{_format_time_short(seconds)}"


def _format_time_short(seconds: float) -> str:
    if seconds < 90:
        return f"{max(1, int(round(seconds)))} sec"
    minutes = max(1, int(round(seconds / 60)))
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    if m == 0:
        return f"{h} hr"
    return f"{h} hr {m} min"


def estimate_split_parts(file_size: int, limit_mb: float) -> int:
    eff = effective_limit_bytes(limit_mb)
    if eff <= 0:
        return 1
    return max(1, math.ceil(file_size / eff))


def _bitrate_preset_key(resolution: Resolution, source_height: int) -> str:
    """Map Source/original to the bitrate tier that matches output height."""
    if resolution == "original":
        if source_height >= 2160:
            return "4k"
        if source_height >= 1080:
            return "1080p"
        return "720p"
    if resolution in CODEC_BITRATES:
        return resolution
    return "1080p"


def video_bitrate_kbps(
    resolution: Resolution, codec: Codec, source_height: int = 1080
) -> int:
    key = _bitrate_preset_key(resolution, source_height)
    return CODEC_BITRATES[key][codec]


def uncapped_bitrate_kbps(
    resolution: Resolution,
    codec: Codec,
    source_height: int,
    bitrate_mode: BitrateMode,
) -> int:
    """Preset target before capping to source bitrate."""
    if bitrate_mode == "source":
        return 0
    scale = BITRATE_MODE_SCALE[bitrate_mode] or 1.0
    return max(
        MIN_VIDEO_KBPS,
        int(video_bitrate_kbps(resolution, codec, source_height) * scale),
    )


def bitrate_mode_exceeds_source(
    resolution: Resolution,
    codec: Codec,
    source_video_kbps: int,
    source_height: int,
    bitrate_mode: BitrateMode,
) -> bool:
    """True when a preset targets above the source video bitrate."""
    if bitrate_mode == "source":
        return False
    return uncapped_bitrate_kbps(
        resolution, codec, source_height, bitrate_mode
    ) > source_video_kbps


def bitrate_mode_is_available(
    resolution: Resolution,
    codec: Codec,
    source_video_kbps: int,
    source_height: int,
    bitrate_mode: BitrateMode,
) -> bool:
    return not bitrate_mode_exceeds_source(
        resolution, codec, source_video_kbps, source_height, bitrate_mode
    )


def ensure_valid_bitrate_mode(
    resolution: Resolution,
    codec: Codec,
    source_video_kbps: int,
    source_height: int,
    bitrate_mode: BitrateMode,
) -> BitrateMode:
    if bitrate_mode_is_available(
        resolution, codec, source_video_kbps, source_height, bitrate_mode
    ):
        return bitrate_mode
    for mode in ("super_high", "high", "balanced", "compact", "source"):
        if bitrate_mode_is_available(
            resolution, codec, source_video_kbps, source_height, mode
        ):
            return mode
    return "source"


def source_video_bitrate_kbps(
    bitrate_bps: int, duration: float, file_size: int
) -> int:
    """Estimate source video bitrate (kbps) from container bitrate or file size."""
    if bitrate_bps > 0:
        total_kbps = bitrate_bps // 1000
    elif duration > 0 and file_size > 0:
        total_kbps = int(file_size * 8 / duration / 1000)
    else:
        return MIN_VIDEO_KBPS
    return max(MIN_VIDEO_KBPS, total_kbps - AUDIO_KBPS)


def effective_video_bitrate_kbps(
    resolution: Resolution,
    codec: Codec,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> int:
    if bitrate_mode == "source":
        if source_video_kbps is not None:
            return source_video_kbps
        return video_bitrate_kbps(resolution, codec, source_height)

    scale = BITRATE_MODE_SCALE[bitrate_mode] or 1.0
    preset = max(
        MIN_VIDEO_KBPS,
        int(video_bitrate_kbps(resolution, codec, source_height) * scale),
    )
    if source_video_kbps is None:
        return preset
    return min(preset, source_video_kbps)


def should_nudge_split_instead(
    file_size: int,
    duration: float,
    resolution: Resolution,
    codec: Codec,
    source_video_kbps: int,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> bool:
    """True when re-encoding at quality presets would grow the file vs source."""
    if bitrate_mode == "source":
        return False
    preset = effective_video_bitrate_kbps(
        resolution, codec, source_video_kbps, source_height, bitrate_mode
    )
    if source_video_kbps >= preset:
        return False
    uncapped_bytes = int((preset + AUDIO_KBPS) * 1000 * duration / 8)
    return uncapped_bytes > file_size


def should_warn_quality_loss(
    source_video_kbps: int,
    resolution: Resolution,
    codec: Codec,
    source_height: int,
    bitrate_mode: BitrateMode,
) -> bool:
    """True when compress bitrate is far below source (visible quality loss likely)."""
    if bitrate_mode == "source":
        return False
    target = effective_video_bitrate_kbps(
        resolution, codec, source_video_kbps, source_height, bitrate_mode
    )
    return source_video_kbps > target * 2


def estimate_compress_size(
    duration: float,
    resolution: Resolution,
    codec: Codec,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> int:
    video_kbps = effective_video_bitrate_kbps(
        resolution, codec, source_video_kbps, source_height, bitrate_mode
    )
    return int((video_kbps + AUDIO_KBPS) * 1000 * duration / 8)


def estimate_compress_parts(
    duration: float,
    resolution: Resolution,
    codec: Codec,
    limit_mb: float,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> int:
    parts, _, _ = compute_compress_segments(
        duration,
        resolution,
        codec,
        limit_mb,
        source_video_kbps,
        source_height,
        bitrate_mode,
    )
    return parts


def estimate_compress_plan(
    duration: float,
    resolution: Resolution,
    codec: Codec,
    limit_mb: float,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
    allow_split: bool = True,
) -> tuple[int, int]:
    """Return (parts, estimated_total_bytes) using the same math as encoding."""
    if not allow_split:
        video_kbps = effective_video_bitrate_kbps(
            resolution, codec, source_video_kbps, source_height, bitrate_mode
        )
        total_bytes = int((video_kbps + AUDIO_KBPS) * 1000 * duration / 8)
        return 1, total_bytes
    parts, _seg, video_kbps = compute_compress_segments(
        duration,
        resolution,
        codec,
        limit_mb,
        source_video_kbps,
        source_height,
        bitrate_mode,
    )
    total_bytes = int((video_kbps + AUDIO_KBPS) * 1000 * duration / 8)
    return parts, total_bytes


def fits_single_compress(
    duration: float,
    resolution: Resolution,
    codec: Codec,
    limit_mb: float,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> bool:
    parts, _, _ = compute_compress_segments(
        duration,
        resolution,
        codec,
        limit_mb,
        source_video_kbps,
        source_height,
        bitrate_mode,
    )
    return parts == 1


def estimate_job_bytes(
    file_size: int,
    duration: float,
    mode: Mode,
    resolution: Resolution,
    codec: Codec,
    limit_mb: float,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
    allow_split: bool = True,
) -> int:
    """Rough bytes needed for a job (for disk-space preflight)."""
    if mode == "split":
        return file_size
    if not allow_split:
        video_kbps = effective_video_bitrate_kbps(
            resolution, codec, source_video_kbps, source_height, bitrate_mode
        )
        return int((video_kbps + AUDIO_KBPS) * 1000 * duration / 8)
    _parts, total = estimate_compress_plan(
        duration,
        resolution,
        codec,
        limit_mb,
        source_video_kbps,
        source_height,
        bitrate_mode,
    )
    return min(file_size, total) if source_video_kbps else total


def resolution_target_height(resolution: Resolution) -> int | None:
    return RESOLUTION_HEIGHT.get(resolution)


def resolution_is_available(resolution: Resolution, source_height: int) -> bool:
    """True when the preset does not upscale (source resolution is always allowed)."""
    if resolution == "original":
        return True
    target = resolution_target_height(resolution)
    return target is not None and source_height >= target


def ensure_valid_resolution(resolution: Resolution, source_height: int) -> Resolution:
    if resolution_is_available(resolution, source_height):
        return resolution
    return default_resolution(source_height)


def is_original_4k(resolution: Resolution, source_height: int) -> bool:
    return resolution == "original" and source_height >= 2160


def stem_output_glob_patterns(stem: str) -> tuple[str, ...]:
    return (
        f"{stem}_part*.mp4",
        f"{stem}_compressed.mp4",
        f"{stem}_*.tmp.mp4",
    )


def output_dir_has_existing_files(output_dir: Path, stem: str) -> bool:
    if not output_dir.is_dir():
        return False
    for pattern in stem_output_glob_patterns(stem):
        if any(output_dir.glob(pattern)):
            return True
    return False


def clear_stem_outputs(output_dir: Path, stem: str) -> int:
    """Remove prior output files for this source stem."""
    if not output_dir.is_dir():
        return 0
    removed = 0
    seen: set[Path] = set()
    for pattern in stem_output_glob_patterns(stem):
        for path in output_dir.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                try:
                    path.unlink()
                except OSError as exc:
                    raise OSError(
                        f"Could not delete {path.name}: {exc}"
                    ) from exc
                removed += 1
    return removed


def descriptive_output_stem(
    source_stem: str,
    resolution: Resolution,
    source_height: int,
    mode: Mode,
    codec: Codec,
    bitrate_mode: BitrateMode = "balanced",
) -> str:
    res = _resolution_filename_tag(resolution, source_height, mode)
    tag = "split" if mode == "split" else codec
    br = "split" if mode == "split" else bitrate_mode
    return f"{source_stem}_{res}_{tag}_{br}"


def test_output_stem(
    source_stem: str,
    resolution: Resolution,
    source_height: int,
    mode: Mode,
    codec: Codec,
    bitrate_mode: BitrateMode = "balanced",
) -> str:
    return "test_" + descriptive_output_stem(
        source_stem, resolution, source_height, mode, codec, bitrate_mode
    )


def _resolution_filename_tag(
    resolution: Resolution, source_height: int, mode: Mode
) -> str:
    if mode == "split":
        if source_height >= 2160:
            return "4k"
        if source_height >= 1080:
            return "1080p"
        if source_height >= 720:
            return "720p"
        return "source"
    if resolution == "original":
        return "source"
    return resolution


def test_output_glob_patterns(test_stem: str) -> tuple[str, ...]:
    return (
        f"{test_stem}_part*.mp4",
        f"{test_stem}_compressed.mp4",
        f"{test_stem}*.tmp.mp4",
    )


def clear_test_outputs(output_dir: Path, test_stem: str) -> int:
    """Remove prior test-clip files for one test configuration (same res/codec/mode)."""
    if not output_dir.is_dir():
        return 0
    removed = 0
    seen: set[Path] = set()
    for pattern in test_output_glob_patterns(test_stem):
        for path in output_dir.glob(pattern):
            if not path.is_file() or path in seen:
                continue
            if path.suffix.lower() not in {".mp4", ".tmp"}:
                continue
            seen.add(path)
            try:
                path.unlink()
            except OSError as exc:
                raise OSError(
                    f"Could not delete {path.name}: {exc}"
                ) from exc
            removed += 1
    return removed


def unique_output_dir(base: Path) -> Path:
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = base.parent / f"{base.name}_{n}"
        if not candidate.exists():
            return candidate
        n += 1


def bitrate_for_segment(limit_mb: float, segment_seconds: float) -> int:
    """Solve video bitrate to fit one segment under effective limit."""
    if segment_seconds <= 0:
        return MIN_VIDEO_KBPS
    eff_bytes = effective_limit_bytes(limit_mb)
    total_kbps = eff_bytes * 8 / segment_seconds / 1000
    return max(MIN_VIDEO_KBPS, int(total_kbps - AUDIO_KBPS))


def target_encode_bitrate(
    limit_mb: float,
    segment_seconds: float,
    resolution: Resolution,
    codec: Codec,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> int:
    preset = effective_video_bitrate_kbps(
        resolution, codec, source_video_kbps, source_height, bitrate_mode
    )
    solved = bitrate_for_segment(limit_mb, segment_seconds)
    return min(preset, solved)


def _initial_compress_parts(
    duration: float,
    resolution: Resolution,
    codec: Codec,
    limit_mb: float,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> int:
    total = estimate_compress_size(
        duration,
        resolution,
        codec,
        source_video_kbps,
        source_height,
        bitrate_mode,
    )
    eff = effective_limit_bytes(limit_mb)
    return max(1, math.ceil(total / eff))


def compute_compress_segments(
    duration: float,
    resolution: Resolution,
    codec: Codec,
    limit_mb: float,
    source_video_kbps: int | None = None,
    source_height: int = 1080,
    bitrate_mode: BitrateMode = "balanced",
) -> tuple[int, float, int]:
    """Return (parts, segment_seconds, video_kbps) with one refinement pass."""
    parts = _initial_compress_parts(
        duration,
        resolution,
        codec,
        limit_mb,
        source_video_kbps,
        source_height,
        bitrate_mode,
    )
    seg = duration if parts <= 1 else duration / parts
    video_kbps = target_encode_bitrate(
        limit_mb,
        seg,
        resolution,
        codec,
        source_video_kbps,
        source_height,
        bitrate_mode,
    )

    refined_parts = max(
        1,
        math.ceil(
            (video_kbps + AUDIO_KBPS) * 1000 * duration / 8 / effective_limit_bytes(limit_mb)
        ),
    )
    if refined_parts != parts:
        parts = refined_parts
        seg = duration if parts <= 1 else duration / parts
        video_kbps = target_encode_bitrate(
            limit_mb,
            seg,
            resolution,
            codec,
            source_video_kbps,
            source_height,
            bitrate_mode,
        )

    return parts, seg, video_kbps


def bitrate_for_single_file(limit_mb: float, duration: float) -> int:
    """Solve video bitrate to fit one file under effective limit."""
    eff_bytes = effective_limit_bytes(limit_mb)
    total_kbps = eff_bytes * 8 / duration / 1000
    return max(MIN_VIDEO_KBPS, int(total_kbps - AUDIO_KBPS))


def segment_seconds_split_only(
    file_size: int, duration: float, limit_mb: float
) -> float:
    eff = effective_limit_bytes(limit_mb)
    if file_size <= 0 or duration <= 0:
        return 60.0
    base = (eff / file_size) * duration
    return max(1.0, base * vbr_headroom(limit_mb))


def scale_filter(resolution: Resolution, source_height: int) -> str | None:
    target = RESOLUTION_HEIGHT.get(resolution)
    if target is None:
        return None
    if source_height <= target:
        return None
    return f"scale=-2:{target}:flags=lanczos"


@dataclass(frozen=True)
class EncodeVideoPlan:
    """Video filter + color path for a compress encode."""

    video_filter: str | None
    output_10bit: bool
    color_primaries: str | None
    color_trc: str | None
    colorspace: str | None

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.output_10bit:
            parts.append("10-bit HDR preserved")
        if self.video_filter:
            parts.append("Lanczos downscale" if "lanczos" in self.video_filter else "scaled")
        return ", ".join(parts) if parts else "no video filter"


def is_hdr_video(info: VideoInfo) -> bool:
    transfer = (info.color_transfer or "").lower()
    if transfer in HDR_COLOR_TRANSFERS:
        return True
    primaries = (info.color_primaries or "").lower()
    pix = (info.pixel_fmt or "").lower()
    if primaries == "bt2020" and (
        (info.bits_per_raw_sample or 0) > 8 or "10" in pix or "p010" in pix
    ):
        return True
    return False


def _downscale_target_height(resolution: Resolution, source_height: int) -> int | None:
    target = RESOLUTION_HEIGHT.get(resolution)
    if target is None or source_height <= target:
        return None
    return target


def build_encode_video_plan(
    resolution: Resolution,
    info: VideoInfo,
    codec: Codec,
) -> EncodeVideoPlan:
    """Choose filters and output color path for GPU/CPU re-encode."""
    target_h = _downscale_target_height(resolution, info.height)
    hdr = is_hdr_video(info)

    if hdr and codec == "hevc" and target_h is None:
        return EncodeVideoPlan(
            video_filter=None,
            output_10bit=True,
            color_primaries=info.color_primaries or "bt2020",
            color_trc=info.color_transfer or "smpte2084",
            colorspace=info.color_space or "bt2020nc",
        )

    if target_h is not None:
        return EncodeVideoPlan(
            video_filter=f"scale=-2:{target_h}:flags=lanczos,format=yuv420p",
            output_10bit=False,
            color_primaries=None,
            color_trc=None,
            colorspace=None,
        )

    return EncodeVideoPlan(
        video_filter=None,
        output_10bit=False,
        color_primaries=None,
        color_trc=None,
        colorspace=None,
    )


def _is_hw_encoder(encoder: str) -> bool:
    return "nvenc" in encoder or "amf" in encoder or "qsv" in encoder


def encode_quality_duration_multiplier(
    resolution: Resolution,
    source_height: int,
    encoder: str,
    codec: Codec,
    gpu_two_pass: bool,
    info: VideoInfo | None,
) -> float:
    """Slowdown factor from quality presets, multipass, HDR filters, etc."""
    mult = 1.0
    plan = build_encode_video_plan(resolution, info, codec) if info is not None else None

    if _is_hw_encoder(encoder):
        if "nvenc" in encoder:
            mult *= NVENC_QUALITY_TIME_FACTOR
            if gpu_two_pass:
                mult *= NVENC_MULTIPASS_TIME_FACTOR
        elif "amf" in encoder:
            if gpu_two_pass:
                mult *= AMF_PREANALYSIS_TIME_FACTOR
        elif "qsv" in encoder:
            mult *= QSV_LOOKAHEAD_TIME_FACTOR

    if plan is None:
        return mult

    if plan.output_10bit:
        mult *= HDR_10BIT_ENCODE_TIME_FACTOR
    elif plan.video_filter and "lanczos" in plan.video_filter:
        mult *= LANCZOS_DOWNSCALE_TIME_FACTOR

    return mult


def encode_time_estimate_uncertain(
    resolution: Resolution,
    source_height: int,
    encoder: str,
    codec: Codec,
    gpu_two_pass: bool,
    info: VideoInfo | None,
) -> bool:
    """True when quality pipeline makes wall-clock time harder to predict."""
    return (
        encode_quality_duration_multiplier(
            resolution, source_height, encoder, codec, gpu_two_pass, info
        )
        >= ENCODE_TIME_UNCERTAIN_MULTIPLIER
    )


def default_resolution(source_height: int) -> Resolution:
    return "original"


def default_mode(info_height: int) -> Mode:
    return "compress_split" if info_height >= 2160 else "split"
