"""Video split and compress pipelines."""

from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.cancel import CancelToken, CancelledError
from app.encoders import CODEC_LABELS, EncoderInfo
from app.ffmpeg import (
    FFmpegError,
    VideoInfo,
    ffmpeg_error_summary,
    ffmpeg_path,
    format_ffmpeg_cmd,
    parse_ffmpeg_duration,
    parse_ffmpeg_time,
    probe_video,
    run_command,
)
from app.profiles import (
    AUDIO_KBPS,
    MIN_VIDEO_KBPS,
    BitrateMode,
    Codec,
    EncodeVideoPlan,
    Mode,
    Resolution,
    bitrate_for_single_file,
    build_encode_video_plan,
    can_stream_copy_to_mp4,
    audio_stream_copyable,
    compute_compress_segments,
    descriptive_output_stem,
    effective_video_bitrate_kbps,
    estimate_job_bytes,
    fits_single_compress,
    format_bytes,
    gpu_vbr_peak_kbps,
    is_hevc_codec,
    NVENC_AQ_STRENGTH,
    NVENC_LOOKAHEAD,
    NVENC_PRESET,
    NVENC_TUNE,
    segment_seconds_split_only,
    single_output_filename,
    source_video_bitrate_kbps,
    target_encode_bitrate,
    test_output_stem,
)

ProgressCallback = Callable[[str, Optional[float]], None]
LogCallback = Callable[[str], None]

INPUT_ERROR_MARKERS = (
    "no such file",
    "invalid data",
    "does not contain",
    "error opening input",
    "no such stream",
)

ENCODER_FAILURE_MARKERS = (
    "codec not supported",
    "no capable devices found",
    "error while opening encoder",
    "could not open encoder",
    "no nvenc capable devices",
    "cannot load nvcuda",
    "encoder not found",
    "does not support",
)


class IncompatibleCodecError(Exception):
    """Source codec cannot be stream-copied to Discord-compatible MP4."""


class OutputSizeError(Exception):
    """One or more output files still exceed the size limit after retries."""


TEST_CLIP_SECONDS = 15.0


@dataclass
class ProcessOptions:
    mode: Mode
    limit_mb: float
    resolution: Resolution
    codec: Codec
    output_dir: Path
    encoder_info: EncoderInfo
    max_duration: float | None = None
    bitrate_mode: BitrateMode = "source"
    gpu_two_pass: bool = False
    allow_split: bool = True
    descriptive_filenames: bool = True


@dataclass
class ProcessResult:
    output_files: list[Path]
    log_lines: list[str]


def _stem(path: Path) -> str:
    return path.stem


def _work_duration(info: VideoInfo, opts: ProcessOptions) -> float:
    if opts.max_duration is None:
        return info.duration
    return min(info.duration, opts.max_duration)


def _work_file_size(info: VideoInfo, opts: ProcessOptions) -> int:
    if opts.max_duration is None or info.duration <= 0:
        return info.file_size
    return int(info.file_size * (_work_duration(info, opts) / info.duration))


def _output_stem(info: VideoInfo, opts: ProcessOptions) -> str:
    base = _stem(info.path)
    if opts.max_duration is not None:
        return test_output_stem(
            base,
            opts.resolution,
            info.height,
            opts.mode,
            opts.codec,
            opts.bitrate_mode,
            allow_split=opts.allow_split,
        )
    if opts.descriptive_filenames:
        return descriptive_output_stem(
            base,
            opts.resolution,
            info.height,
            opts.mode,
            opts.codec,
            opts.bitrate_mode,
            allow_split=opts.allow_split,
        )
    return base


def _duration_input_args(opts: ProcessOptions) -> list[str]:
    if opts.max_duration is None:
        return []
    return ["-t", str(opts.max_duration)]


def _ffmpeg_input_args(path: Path) -> list[str]:
    """Large probe window for MPEG-TS and other slow-probe containers."""
    return ["-analyzeduration", "100M", "-probesize", "100M", "-i", str(path)]


def _encode_output_maps(info: VideoInfo) -> list[str]:
    """Keep audio when -vf is used (ffmpeg drops unmapped streams otherwise)."""
    maps = ["-map", "0:v:0"]
    if info.audio_codec is not None:
        maps.extend(["-map", "0:a:0"])
    return maps


def _source_video_kbps(info: VideoInfo) -> int:
    return source_video_bitrate_kbps(info.bitrate, info.duration, info.file_size)


def _should_retry_encoder(stderr: str) -> bool:
    lower = stderr.lower()
    if any(marker in lower for marker in ENCODER_FAILURE_MARKERS):
        return True
    return not any(marker in lower for marker in INPUT_ERROR_MARKERS)


def _is_hw_video_encoder(encoder: str) -> bool:
    return "nvenc" in encoder or "amf" in encoder or "qsv" in encoder


def _log_gpu_encode_options(
    on_log: LogCallback,
    encoder: str,
    gpu_two_pass: bool,
    plan: EncodeVideoPlan,
    encoder_info: EncoderInfo | None = None,
) -> None:
    if not _is_hw_video_encoder(encoder):
        return
    details: list[str] = [plan.summary]
    if "nvenc" in encoder:
        details.append(f"NVENC {NVENC_PRESET}/{NVENC_TUNE}")
        details.append(f"lookahead {NVENC_LOOKAHEAD}")
        if gpu_two_pass:
            details.append("2-pass")
    elif "amf" in encoder and gpu_two_pass:
        details.append("AMF preanalysis")
    elif "qsv" in encoder:
        if encoder_info and encoder_info.qsv_quality_tiers.get(encoder) == "full":
            details.append("QSV lookahead")
        else:
            details.append("QSV compatible preset (reduced settings)")
    on_log("Video pipeline: " + "; ".join(details))


def _encode_rate_label(encoder: str, video_kbps: int) -> str:
    if _is_hw_video_encoder(encoder):
        peak = gpu_vbr_peak_kbps(video_kbps)
        return f"{video_kbps} kbps avg, ~{peak} kbps peak (VBR)"
    return f"{video_kbps} kbps"


def _color_output_args(plan: EncodeVideoPlan) -> list[str]:
    if not plan.color_primaries:
        return []
    args: list[str] = ["-color_primaries", plan.color_primaries]
    if plan.color_trc:
        args.extend(["-color_trc", plan.color_trc])
    if plan.colorspace:
        args.extend(["-colorspace", plan.colorspace])
    return args


def _effective_qsv_compat(
    encoder: str, encoder_info: EncoderInfo | None, qsv_compat: bool
) -> bool:
    if qsv_compat:
        return True
    if "qsv" not in encoder:
        return False
    if encoder_info is None:
        return True
    return encoder_info.qsv_quality_tiers.get(encoder, "compat") != "full"


def _build_video_encode_args(
    encoder: str,
    codec: Codec,
    video_kbps: int,
    *,
    gpu_two_pass: bool,
    plan: EncodeVideoPlan,
    nvenc_compat: bool = False,
    qsv_compat: bool = False,
    encoder_info: EncoderInfo | None = None,
) -> list[str]:
    kbps = max(MIN_VIDEO_KBPS, video_kbps)
    args: list[str] = []

    if encoder == "libx264":
        args.extend(["-c:v", "libx264", "-preset", "medium", "-b:v", f"{kbps}k"])
    elif encoder == "libx265":
        args.extend(
            ["-c:v", "libx265", "-preset", "medium", "-b:v", f"{kbps}k", "-tag:v", "hvc1"]
        )
    elif encoder == "libsvtav1":
        args.extend(["-c:v", "libsvtav1", "-preset", "6", "-b:v", f"{kbps}k"])
    elif _is_hw_video_encoder(encoder):
        peak = gpu_vbr_peak_kbps(kbps)
        rate_args = [
            "-b:v",
            f"{kbps}k",
            "-maxrate",
            f"{peak}k",
            "-bufsize",
            f"{peak * 2}k",
        ]
        if "nvenc" in encoder:
            if nvenc_compat:
                args.extend(
                    [
                        "-c:v",
                        encoder,
                        "-gpu",
                        "0",
                        "-preset",
                        "p4",
                        "-rc",
                        "vbr",
                        *rate_args,
                    ]
                )
            else:
                multipass = gpu_two_pass
                args.extend(
                    [
                        "-c:v",
                        encoder,
                        "-gpu",
                        "0",
                        "-preset",
                        NVENC_PRESET,
                        "-tune",
                        NVENC_TUNE,
                        "-rc",
                        "vbr",
                        *rate_args,
                        "-rc-lookahead",
                        str(NVENC_LOOKAHEAD),
                        "-spatial-aq",
                        "1",
                        "-temporal-aq",
                        "1",
                        "-aq-strength",
                        str(NVENC_AQ_STRENGTH),
                    ]
                )
                if multipass:
                    args.extend(["-multipass", "2"])
        else:
            multipass = gpu_two_pass
            if "amf" in encoder:
                args.extend(
                    [
                        "-c:v",
                        encoder,
                        "-quality",
                        "high_quality",
                        "-usage",
                        "high_quality",
                        *rate_args,
                    ]
                )
                if multipass:
                    args.extend(["-preanalysis", "1"])
            elif "qsv" in encoder:
                use_compat = _effective_qsv_compat(encoder, encoder_info, qsv_compat)
                qsv_args = (
                    ["-preset", "medium"]
                    if use_compat
                    else ["-extbrc", "1", "-look_ahead_depth", "40"]
                )
                args.extend(["-c:v", encoder, *rate_args, *qsv_args])
            else:
                args.extend(["-c:v", encoder, *rate_args])

        if plan.output_10bit and codec == "hevc":
            args.extend(["-pix_fmt", "p010le", "-profile:v", "main10"])
        elif plan.output_10bit and codec == "av1":
            args.extend(["-pix_fmt", "p010le"])
        elif "nvenc" in encoder:
            args.extend(["-pix_fmt", "yuv420p"])

        if codec == "hevc":
            args.extend(["-tag:v", "hvc1"])

        args.extend(_color_output_args(plan))
    else:
        args.extend(["-c:v", encoder, "-b:v", f"{kbps}k"])

    return args


def _append_video_encode(
    args: list[str],
    encoder: str,
    codec: Codec,
    video_kbps: int,
    *,
    gpu_two_pass: bool,
    plan: EncodeVideoPlan,
    nvenc_compat: bool = False,
    qsv_compat: bool = False,
    encoder_info: EncoderInfo | None = None,
) -> None:
    vf = plan.video_filter
    if vf:
        args.extend(["-vf", vf])
    args.extend(
        _build_video_encode_args(
            encoder,
            codec,
            video_kbps,
            gpu_two_pass=gpu_two_pass,
            plan=plan,
            nvenc_compat=nvenc_compat,
            qsv_compat=qsv_compat,
            encoder_info=encoder_info,
        )
    )


def _split_copy_extra_args(info: VideoInfo) -> list[str]:
    args = ["-movflags", "+faststart"]
    if is_hevc_codec(info.video_codec):
        args.extend(["-tag:v", "hvc1"])
    return args


def _split_stream_args(info: VideoInfo) -> list[str]:
    """Map/codec args for split remux; re-encode audio when MP4 copy is invalid."""
    if info.audio_codec is None:
        return ["-map", "0:v:0", "-c:v", "copy", *_split_copy_extra_args(info)]

    if audio_stream_copyable(
        info.audio_codec, info.audio_channels, info.audio_sample_rate
    ):
        return [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c",
            "copy",
            *_split_copy_extra_args(info),
        ]

    return [
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        f"{AUDIO_KBPS}k",
        *_split_copy_extra_args(info),
    ]


def _run_ffmpeg_with_progress(
    args: list[str],
    total_duration: float,
    on_progress: ProgressCallback,
    status_prefix: str,
    cancel: Optional[CancelToken] = None,
    *,
    lock_duration: bool = False,
    on_log: LogCallback | None = None,
) -> None:
    duration = total_duration
    last_pct = -1.0
    if on_log is not None:
        on_log(format_ffmpeg_cmd(args))
    on_progress(f"{status_prefix} (starting)...", None)

    def on_line(line: str) -> None:
        nonlocal duration, last_pct
        if not lock_duration:
            parsed_dur = parse_ffmpeg_duration(line)
            if parsed_dur:
                duration = parsed_dur
                if last_pct < 0:
                    on_progress(f"{status_prefix} (preparing)...", None)
        if "Input #" in line and last_pct < 0:
            on_progress(f"{status_prefix} (preparing)...", None)
        current = parse_ffmpeg_time(line)
        if current is not None and duration > 0:
            pct = min(100.0, (current / duration) * 100.0)
            if pct - last_pct >= 0.5 or last_pct < 0:
                last_pct = pct
                on_progress(f"{status_prefix} {pct:.0f}%", pct / 100.0)

    run_command(args, on_stderr_line=on_line, cancel=cancel)
    if lock_duration and last_pct < 100.0:
        on_progress(f"{status_prefix} 100%", 1.0)


def _run_encode_with_fallback(
    build_args: Callable[..., list[str]],
    requested_codec: Codec,
    encoder_info: EncoderInfo,
    on_log: LogCallback,
    run_fn: Callable[[list[str]], None],
) -> Codec:
    attempts = encoder_info.iter_encode_attempts(requested_codec)
    last_error = ""

    for idx, (codec, encoder) in enumerate(attempts):
        if "nvenc" in encoder:
            compat_modes: tuple[tuple[bool, bool], ...] = ((False, False), (True, False))
        elif "qsv" in encoder:
            compat_modes = ((False, False), (False, True))
        else:
            compat_modes = ((False, False),)
        for nvenc_compat, qsv_compat in compat_modes:
            args = build_args(
                codec, encoder, nvenc_compat=nvenc_compat, qsv_compat=qsv_compat
            )
            try:
                run_fn(args)
                if codec != requested_codec or idx > 0 or nvenc_compat or qsv_compat:
                    label = f"Encoding with {CODEC_LABELS[codec]} via {encoder}"
                    if nvenc_compat:
                        label += " (compatible NVENC)"
                    elif qsv_compat:
                        label += " (compatible QSV)"
                    elif idx > 0:
                        label += " (fallback)"
                    on_log(label)
                return codec
            except CancelledError:
                raise
            except FFmpegError as exc:
                last_error = ffmpeg_error_summary(exc.stderr or str(exc))
                if not last_error or last_error == "None":
                    last_error = f"FFmpeg encoding failed ({type(exc).__name__})"
                if nvenc_compat or qsv_compat:
                    if not _should_retry_encoder(last_error) or idx == len(attempts) - 1:
                        raise RuntimeError(last_error) from exc
                    on_log(f"{encoder} failed ({last_error}) — trying next encoder...")
                elif "nvenc" in encoder:
                    on_log(f"{encoder} failed ({last_error}) — retrying with compatible settings...")
                elif "qsv" in encoder:
                    on_log(f"{encoder} failed ({last_error}) — retrying with compatible QSV settings...")
                else:
                    if not _should_retry_encoder(last_error) or idx == len(attempts) - 1:
                        raise RuntimeError(last_error) from exc
                    on_log(f"{encoder} failed ({last_error}) — trying next encoder...")

    raise RuntimeError(last_error or "All encoders failed")


def _collect_outputs(output_dir: Path, stem: str) -> list[Path]:
    pattern = re.compile(
        rf"^{re.escape(stem)}(?:_(?:part\d+(?:_\d+)*|compressed|remux))?\.mp4$"
    )
    files = [f for f in output_dir.iterdir() if f.is_file() and pattern.match(f.name)]
    return sorted(files)


def _limit_bytes(limit_mb: float) -> int:
    return int(limit_mb * 1024 * 1024)


def _assert_outputs_under_limit(files: list[Path], limit_mb: float) -> None:
    limit = _limit_bytes(limit_mb)
    overs = [f for f in files if f.stat().st_size > limit]
    if not overs:
        return
    names = ", ".join(f.name for f in overs[:5])
    extra = f" (+{len(overs) - 5} more)" if len(overs) > 5 else ""
    raise OutputSizeError(
        f"{len(overs)} file(s) still exceed the {limit_mb:g} MB limit after retries: "
        f"{names}{extra}"
    )


def _check_disk_space(output_dir: Path, required_bytes: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(output_dir).free
    needed = int(required_bytes * 1.1)
    if free < needed:
        raise RuntimeError(
            f"Not enough disk space in {output_dir}. "
            f"Need ~{format_bytes(needed)}, have {format_bytes(free)} free."
        )


def _verify_and_fix(
    files: list[Path],
    limit_mb: float,
    mode: Mode,
    info: VideoInfo,
    opts: ProcessOptions,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
    encode_context: dict | None = None,
) -> list[Path]:
    limit_bytes = _limit_bytes(limit_mb)
    result: list[Path] = []
    encode_context = encode_context or {}

    for idx, fpath in enumerate(files, start=1):
        if cancel is not None:
            cancel.check()
        if len(files) > 1:
            on_progress(
                f"Verifying part {idx} of {len(files)}...",
                (idx - 1) / len(files),
            )
        fixed = _verify_one(
            fpath,
            limit_bytes,
            limit_mb,
            mode,
            info,
            opts,
            on_progress,
            on_log,
            cancel,
            encode_context,
            retries=0,
        )
        result.extend(fixed)
        if len(files) > 1:
            on_progress(f"Verified part {idx} of {len(files)}", idx / len(files))

    return sorted(result)


def _verify_one(
    fpath: Path,
    limit_bytes: int,
    limit_mb: float,
    mode: Mode,
    info: VideoInfo,
    opts: ProcessOptions,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
    encode_context: dict,
    retries: int,
) -> list[Path]:
    size = fpath.stat().st_size
    if size <= limit_bytes:
        on_log(f"{fpath.name} — {_fmt_size(size)} OK")
        return [fpath]

    if retries >= 2:
        on_log(f"ERROR: {fpath.name} still over limit ({_fmt_size(size)}) after retries")
        return [fpath]

    on_log(f"{fpath.name} — {_fmt_size(size)} OVER LIMIT, fixing...")

    if mode == "split":
        return _resplit_half(
            fpath, limit_bytes, limit_mb, info, opts, on_progress, on_log, cancel, retries
        )

    return _reencode_smaller(
        fpath,
        limit_bytes,
        limit_mb,
        info,
        opts,
        on_progress,
        on_log,
        cancel,
        encode_context,
        retries,
    )


def _fmt_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 ** 2):.1f} MB"
    return f"{num_bytes / 1024:.1f} KB"


def _resplit_half(
    fpath: Path,
    limit_bytes: int,
    limit_mb: float,
    info: VideoInfo,
    opts: ProcessOptions,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
    retries: int,
) -> list[Path]:
    try:
        probed = probe_video(fpath, cancel=cancel)
    except RuntimeError:
        probed = info

    seg = max(
        1.0,
        segment_seconds_split_only(probed.file_size, probed.duration, limit_mb) / 2,
    )
    part_base = fpath.stem
    out_pattern = str(fpath.parent / f"{part_base}_%02d.mp4")

    args = [
        str(ffmpeg_path()),
        "-y",
        *_ffmpeg_input_args(fpath),
        *_split_stream_args(probed),
        "-f",
        "segment",
        "-segment_time",
        str(seg),
        "-reset_timestamps",
        "1",
        out_pattern,
    ]
    on_progress("Re-splitting oversized part...", None)
    run_command(args, cancel=cancel)
    fpath.unlink(missing_ok=True)

    parts = sorted(
        p
        for p in fpath.parent.glob(f"{part_base}_*.mp4")
        if p.is_file() and re.match(rf"^{re.escape(part_base)}_\d{{2}}\.mp4$", p.name)
    )
    fixed: list[Path] = []
    for part in parts:
        fixed.extend(
            _verify_one(
                part,
                limit_bytes,
                limit_mb,
                "split",
                probed,
                opts,
                on_progress,
                on_log,
                cancel,
                {},
                retries + 1,
            )
        )
    return fixed


def _reencode_smaller(
    fpath: Path,
    limit_bytes: int,
    limit_mb: float,
    info: VideoInfo,
    opts: ProcessOptions,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
    encode_context: dict,
    retries: int,
) -> list[Path]:
    try:
        part_info = probe_video(fpath, cancel=cancel)
    except RuntimeError:
        part_info = info

    prev_kbps = encode_context.get(
        "video_kbps",
        effective_video_bitrate_kbps(
            opts.resolution,
            opts.codec,
            _source_video_kbps(info),
            info.height,
            opts.bitrate_mode,
        ),
    )
    new_kbps = max(MIN_VIDEO_KBPS, int(prev_kbps * 0.85))
    encode_context["video_kbps"] = new_kbps

    tmp = fpath.with_name(f"{fpath.stem}.tmp.mp4")

    def build_args(codec: Codec, encoder: str, *, nvenc_compat: bool = False, qsv_compat: bool = False) -> list[str]:
        plan = build_encode_video_plan(opts.resolution, part_info, codec)
        args = [str(ffmpeg_path()), "-y", *_ffmpeg_input_args(fpath)]
        args.extend(_encode_output_maps(part_info))
        _append_video_encode(
            args,
            encoder,
            codec,
            new_kbps,
            gpu_two_pass=opts.gpu_two_pass,
            plan=plan,
            nvenc_compat=nvenc_compat,
            qsv_compat=qsv_compat,
            encoder_info=opts.encoder_info,
        )
        args.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                f"{AUDIO_KBPS}k",
                "-movflags",
                "+faststart",
                str(tmp),
            ]
        )
        return args

    def run_fn(args: list[str]) -> None:
        _run_ffmpeg_with_progress(
            args, part_info.duration, on_progress, "Re-encoding", cancel, on_log=on_log
        )

    encode_codec = encode_context.get("codec", opts.codec)
    _run_encode_with_fallback(build_args, encode_codec, opts.encoder_info, on_log, run_fn)
    fpath.unlink(missing_ok=True)
    tmp.rename(fpath)
    return _verify_one(
        fpath,
        limit_bytes,
        limit_mb,
        opts.mode,
        info,
        opts,
        on_progress,
        on_log,
        cancel,
        encode_context,
        retries + 1,
    )


def process_video(
    info: VideoInfo,
    opts: ProcessOptions,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken] = None,
) -> ProcessResult:
    opts.output_dir.mkdir(parents=True, exist_ok=True)
    duration = _work_duration(info, opts)
    file_size = _work_file_size(info, opts)
    required = estimate_job_bytes(
        file_size,
        duration,
        opts.mode,
        opts.resolution,
        opts.codec,
        opts.limit_mb,
        _source_video_kbps(info),
        info.height,
        opts.bitrate_mode,
        allow_split=opts.allow_split,
    )
    _check_disk_space(opts.output_dir, required)
    log: list[str] = []

    def log_msg(msg: str) -> None:
        log.append(msg)
        on_log(msg)

    if opts.max_duration is not None:
        log_msg(f"Test clip: first {duration:.0f}s of source video")

    if opts.mode == "split":
        files = _split_only(info, opts, on_progress, log_msg, cancel)
        encode_ctx: dict | None = None
    else:
        files, encode_ctx = _compress(info, opts, on_progress, log_msg, cancel)

    if cancel is not None:
        cancel.check()

    if opts.allow_split:
        log_msg("Verifying output sizes...")
        verified = _verify_and_fix(
            files, opts.limit_mb, opts.mode, info, opts, on_progress, log_msg, cancel, encode_ctx
        )
        _assert_outputs_under_limit(verified, opts.limit_mb)
    else:
        verified = files
        for fpath in files:
            log_msg(f"{fpath.name} — {_fmt_size(fpath.stat().st_size)} (no size limit)")
    on_progress("Done", 1.0)
    return ProcessResult(output_files=verified, log_lines=log)


def _split_only(
    info: VideoInfo,
    opts: ProcessOptions,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
) -> list[Path]:
    if not can_stream_copy_to_mp4(info.video_codec):
        raise IncompatibleCodecError(
            f"Codec '{info.video_codec}' cannot be split to Discord-compatible MP4. "
            "Use Compress or Compress & split instead."
        )

    stem = _output_stem(info, opts)
    if not opts.allow_split:
        out = opts.output_dir / single_output_filename(
            stem, "split", descriptive=opts.descriptive_filenames
        )
        on_log("Remuxing to single MP4 (no split)")
        if info.audio_codec and not audio_stream_copyable(
            info.audio_codec, info.audio_channels, info.audio_sample_rate
        ):
            on_log("Audio remuxed to AAC (source audio metadata not MP4-compatible)")
        else:
            on_log("Output remuxed to MP4 (no re-encode)")
        args = [
            str(ffmpeg_path()),
            "-y",
            *_ffmpeg_input_args(info.path),
            *_duration_input_args(opts),
            *_split_stream_args(info),
            str(out),
        ]
        _run_ffmpeg_with_progress(
            args,
            _work_duration(info, opts),
            on_progress,
            "Remuxing",
            cancel,
            lock_duration=opts.max_duration is not None,
            on_log=on_log,
        )
        return [out]

    seg = segment_seconds_split_only(
        _work_file_size(info, opts), _work_duration(info, opts), opts.limit_mb
    )
    est_parts = max(1, math.ceil(_work_duration(info, opts) / seg))
    out_pattern = str(opts.output_dir / f"{stem}_part%03d.mp4")
    on_log(f"Splitting into ~{est_parts} parts (segment {seg:.1f}s)")
    if info.audio_codec and not audio_stream_copyable(
        info.audio_codec, info.audio_channels, info.audio_sample_rate
    ):
        on_log("Audio remuxed to AAC (source audio metadata not MP4-compatible)")
    else:
        on_log("Output remuxed to MP4 (no re-encode)")

    args = [
        str(ffmpeg_path()),
        "-y",
        *_ffmpeg_input_args(info.path),
        *_duration_input_args(opts),
        *_split_stream_args(info),
        "-f",
        "segment",
        "-segment_time",
        str(seg),
        "-reset_timestamps",
        "1",
        "-segment_start_number",
        "1",
        out_pattern,
    ]
    prefix = f"Splitting part 1 of ~{est_parts}"
    _run_ffmpeg_with_progress(
        args,
        _work_duration(info, opts),
        on_progress,
        prefix,
        cancel,
        lock_duration=opts.max_duration is not None,
        on_log=on_log,
    )
    return _collect_outputs(opts.output_dir, stem)


def _compress(
    info: VideoInfo,
    opts: ProcessOptions,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
) -> tuple[list[Path], dict]:
    preferred_codec, hw_encoder, backend = opts.encoder_info.pick_encoder(opts.codec)
    on_log(f"Preferred encoder: {backend}")
    encode_plan = build_encode_video_plan(opts.resolution, info, preferred_codec)
    _log_gpu_encode_options(on_log, hw_encoder, opts.gpu_two_pass, encode_plan, opts.encoder_info)

    encode_ctx: dict = {"codec": preferred_codec}
    source_kbps = _source_video_kbps(info)
    duration = _work_duration(info, opts)

    if not opts.allow_split:
        video_kbps = effective_video_bitrate_kbps(
            opts.resolution,
            preferred_codec,
            source_kbps,
            info.height,
            opts.bitrate_mode,
        )
        encode_ctx["video_kbps"] = video_kbps
        stem = _output_stem(info, opts)
        out = opts.output_dir / single_output_filename(
            stem, "compress", descriptive=opts.descriptive_filenames
        )
        on_log(
            f"Compressing to single file, no split (~{CODEC_LABELS[preferred_codec]}, "
            f"{_encode_rate_label(hw_encoder, video_kbps)})"
        )
        _encode_file(
            info, opts, preferred_codec, video_kbps, out, None, on_progress, on_log, cancel
        )
        return [out], encode_ctx

    single_ok = opts.mode in ("compress", "compress_split") and fits_single_compress(
        duration,
        opts.resolution,
        preferred_codec,
        opts.limit_mb,
        source_kbps,
        info.height,
        opts.bitrate_mode,
    )

    if single_ok:
        video_kbps = min(
            target_encode_bitrate(
                opts.limit_mb,
                duration,
                opts.resolution,
                preferred_codec,
                source_kbps,
                info.height,
                opts.bitrate_mode,
            ),
            bitrate_for_single_file(opts.limit_mb, duration),
        )
        encode_ctx["video_kbps"] = video_kbps
        stem = _output_stem(info, opts)
        if opts.mode == "compress":
            out = opts.output_dir / single_output_filename(
            stem, "compress", descriptive=opts.descriptive_filenames
        )
            on_log(
                f"Compressing to single file (~{CODEC_LABELS[preferred_codec]}, "
                f"{_encode_rate_label(hw_encoder, video_kbps)})"
            )
        else:
            out = opts.output_dir / f"{stem}_part001.mp4"
            on_log(
                f"Compressing to one part (~{CODEC_LABELS[preferred_codec]}, "
                f"{_encode_rate_label(hw_encoder, video_kbps)})"
            )
        _encode_file(
            info, opts, preferred_codec, video_kbps, out, None, on_progress, on_log, cancel
        )
        encode_ctx["codec"] = preferred_codec
        return [out], encode_ctx

    parts, seg, video_kbps = compute_compress_segments(
        duration,
        opts.resolution,
        preferred_codec,
        opts.limit_mb,
        source_kbps,
        info.height,
        opts.bitrate_mode,
    )
    encode_ctx["video_kbps"] = video_kbps
    encode_ctx["total_parts"] = parts
    on_log(
        f"Encoding {parts} parts ({CODEC_LABELS[preferred_codec]}, "
        f"{_encode_rate_label(hw_encoder, video_kbps)}, segment {seg:.1f}s)"
    )

    stem = _output_stem(info, opts)
    out_pattern = str(opts.output_dir / f"{stem}_part%03d.mp4")
    actual_codec = _encode_segmented(
        info,
        opts,
        preferred_codec,
        video_kbps,
        seg,
        out_pattern,
        parts,
        on_progress,
        on_log,
        cancel,
    )
    encode_ctx["codec"] = actual_codec
    return _collect_outputs(opts.output_dir, stem), encode_ctx


def _encode_file(
    info: VideoInfo,
    opts: ProcessOptions,
    codec: Codec,
    video_kbps: int,
    output: Path,
    segment_time: float | None,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
) -> Codec:
    def build_args(actual_codec: Codec, encoder: str, *, nvenc_compat: bool = False, qsv_compat: bool = False) -> list[str]:
        plan = build_encode_video_plan(opts.resolution, info, actual_codec)
        args = [
            str(ffmpeg_path()),
            "-y",
            *_ffmpeg_input_args(info.path),
            *_duration_input_args(opts),
        ]
        args.extend(_encode_output_maps(info))
        _append_video_encode(
            args,
            encoder,
            actual_codec,
            video_kbps,
            gpu_two_pass=opts.gpu_two_pass,
            plan=plan,
            nvenc_compat=nvenc_compat,
            qsv_compat=qsv_compat,
            encoder_info=opts.encoder_info,
        )
        args.extend(["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-movflags", "+faststart"])
        if segment_time is not None:
            args.extend(
                [
                    "-f",
                    "segment",
                    "-segment_time",
                    str(segment_time),
                    "-reset_timestamps",
                    "1",
                    "-segment_start_number",
                    "1",
                    str(output),
                ]
            )
        else:
            args.append(str(output))
        return args

    def run_fn(args: list[str]) -> None:
        _run_ffmpeg_with_progress(
            args,
            _work_duration(info, opts),
            on_progress,
            "Encoding",
            cancel,
            lock_duration=opts.max_duration is not None,
            on_log=on_log,
        )

    return _run_encode_with_fallback(build_args, codec, opts.encoder_info, on_log, run_fn)


def _encode_segmented(
    info: VideoInfo,
    opts: ProcessOptions,
    codec: Codec,
    video_kbps: int,
    segment_time: float,
    out_pattern: str,
    total_parts: int,
    on_progress: ProgressCallback,
    on_log: LogCallback,
    cancel: Optional[CancelToken],
) -> Codec:
    prefix = f"Encoding {total_parts} parts"

    def build_args(actual_codec: Codec, encoder: str, *, nvenc_compat: bool = False, qsv_compat: bool = False) -> list[str]:
        plan = build_encode_video_plan(opts.resolution, info, actual_codec)
        args = [
            str(ffmpeg_path()),
            "-y",
            *_ffmpeg_input_args(info.path),
            *_duration_input_args(opts),
        ]
        args.extend(_encode_output_maps(info))
        _append_video_encode(
            args,
            encoder,
            actual_codec,
            video_kbps,
            gpu_two_pass=opts.gpu_two_pass,
            plan=plan,
            nvenc_compat=nvenc_compat,
            qsv_compat=qsv_compat,
            encoder_info=opts.encoder_info,
        )
        args.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                f"{AUDIO_KBPS}k",
                "-movflags",
                "+faststart",
                "-f",
                "segment",
                "-segment_time",
                str(segment_time),
                "-reset_timestamps",
                "1",
                "-segment_start_number",
                "1",
                out_pattern,
            ]
        )
        return args

    def run_fn(args: list[str]) -> None:
        _run_ffmpeg_with_progress(
            args,
            _work_duration(info, opts),
            on_progress,
            prefix,
            cancel,
            lock_duration=opts.max_duration is not None,
            on_log=on_log,
        )

    return _run_encode_with_fallback(build_args, codec, opts.encoder_info, on_log, run_fn)
