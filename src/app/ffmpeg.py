"""FFmpeg/ffprobe subprocess helpers and video probing."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.cancel import CancelToken, CancelledError, stop_process
from app.paths import ffmpeg_dir, ffmpeg_path, ffprobe_path

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


class ProbeError(RuntimeError):
    """Invalid or unreadable video file."""


@dataclass
class VideoInfo:
    path: Path
    duration: float
    file_size: int
    width: int
    height: int
    bitrate: int
    video_codec: str
    audio_codec: str | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    pixel_fmt: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_space: str | None = None
    bits_per_raw_sample: int | None = None

    @property
    def resolution_label(self) -> str:
        if self.height >= 2160:
            return f"{self.width}×{self.height} (4K)"
        if self.height >= 1080:
            return f"{self.width}×{self.height} (1080p)"
        if self.height >= 720:
            return f"{self.width}×{self.height} (720p)"
        return f"{self.width}×{self.height}"

    @property
    def is_4k(self) -> bool:
        return self.height >= 2160 or self.width >= 3840


def ensure_ffmpeg() -> None:
    if not ffmpeg_path().is_file():
        raise FileNotFoundError(
            f"ffmpeg.exe not found at {ffmpeg_path()}. "
            "Download FFmpeg and place ffmpeg.exe and ffprobe.exe in the ffmpeg/ folder. "
            "See ffmpeg/README.md for instructions."
        )
    if not ffprobe_path().is_file():
        raise FileNotFoundError(
            f"ffprobe.exe not found at {ffprobe_path()}. See ffmpeg/README.md for instructions."
        )


def format_ffmpeg_cmd(args: list[str]) -> str:
    """Format argv as a single shell-quoted command line for logs."""
    parts: list[str] = []
    for arg in args:
        if " " in arg or "\t" in arg:
            parts.append(f'"{arg}"')
        else:
            parts.append(arg)
    return " ".join(parts)


def run_command(
    args: list[str],
    on_stderr_line: Callable[[str], None] | None = None,
    cancel: Optional[CancelToken] = None,
) -> subprocess.CompletedProcess[str]:
    ensure_ffmpeg()
    if cancel is not None:
        cancel.check()

    creationflags = CREATE_NO_WINDOW
    stderr_chunks: list[str] = []
    cwd = _subprocess_cwd(args)

    if on_stderr_line is not None:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
            cwd=cwd,
        )
        if cancel is not None:
            cancel.set_proc(proc)
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                if cancel is not None:
                    cancel.check()
                stderr_chunks.append(line)
                on_stderr_line(line.rstrip())
            proc.wait()
        except CancelledError:
            stop_process(proc)
            raise
        finally:
            if cancel is not None:
                cancel.clear_proc()

        if cancel is not None and cancel.cancelled:
            raise CancelledError("Cancelled by user")
        if proc.returncode != 0:
            stderr = "".join(stderr_chunks)
            raise FFmpegError(f"FFmpeg failed (exit {proc.returncode})", stderr)
        return subprocess.CompletedProcess(args, proc.returncode or 0, "", "")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
        cwd=cwd,
    )
    if cancel is not None:
        cancel.set_proc(proc)
    try:
        stdout, stderr = proc.communicate()
        if cancel is not None:
            cancel.check()
    except CancelledError:
        stop_process(proc)
        raise
    finally:
        if cancel is not None:
            cancel.clear_proc()

    if cancel is not None and cancel.cancelled:
        raise CancelledError("Cancelled by user")
    if proc.returncode != 0:
        detail = (stderr or "").strip()
        message = detail or f"FFmpeg failed (exit {proc.returncode})"
        raise FFmpegError(message, detail)
    return subprocess.CompletedProcess(args, proc.returncode or 0, stdout, stderr)


def list_encoders() -> set[str]:
    result = run_command([str(ffmpeg_path()), "-encoders"])
    encoders: set[str] = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^\s+V\S+\s+(\S+)", line)
        if match:
            encoders.add(match.group(1))
    return encoders


# NVENC requires at least ~145x145; 256x256 is safe for all hardware encoders.
_ENCODER_PROBE_SIZE = "256x256"
_GENERIC_PROBE_ERRORS = (
    "nothing was written into output file",
    "could not open encoder before eof",
    "task finished with error code",
    "terminating thread with return code",
    "error sending frames to consumers",
    "generic error in an external library",
)


def _clip_probe_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in reversed(lines):
        text = line.rsplit("] ", 1)[-1].strip() if "] " in line else line
        low = text.lower()
        if any(marker in low for marker in _GENERIC_PROBE_ERRORS):
            continue
        if text:
            return text[:160]
    for line in reversed(lines):
        text = line.rsplit("] ", 1)[-1].strip() if "] " in line else line
        if text:
            return text[:160]
    return "encode probe failed"


def ffmpeg_error_summary(stderr: str) -> str:
    """Return the most useful single-line message from FFmpeg stderr."""
    return _clip_probe_error(stderr)


def _subprocess_cwd(args: list[str]) -> str | None:
    try:
        if Path(args[0]).name.lower() in ("ffmpeg.exe", "ffprobe.exe"):
            return str(ffmpeg_dir())
    except (IndexError, OSError, ValueError):
        pass
    return None


def _probe_input_arg() -> str:
    return f"color=c=black:s={_ENCODER_PROBE_SIZE}:r=30:d=0.2"


def _encoder_probe_attempts(encoder: str) -> list[tuple[list[str], str]]:
    """Probe configs to try; returns (extra_args, quality_tier)."""
    rate_args = ["-b:v", "2M", "-maxrate", "4M", "-bufsize", "8M"]
    if "nvenc" in encoder:
        return [
            (
                [
                    "-gpu",
                    "0",
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    "p4",
                    "-rc",
                    "vbr",
                    *rate_args,
                ],
                "full",
            ),
        ]
    if "qsv" in encoder:
        scale = ["-vf", "scale=-2:720:flags=lanczos,format=yuv420p"]
        return [
            (
                [
                    *scale,
                    *rate_args,
                    "-extbrc",
                    "1",
                    "-look_ahead_depth",
                    "40",
                ],
                "full",
            ),
            (
                [
                    *scale,
                    *rate_args,
                    "-preset",
                    "medium",
                ],
                "compat",
            ),
        ]
    return [([], "full")]


def _run_encoder_probe(
    encoder: str, extra_args: list[str], timeout: float, *, frames: int = 1
) -> tuple[bool, str]:
    args = [
        str(ffmpeg_path()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        _probe_input_arg(),
        "-frames:v",
        str(frames),
        "-an",
        "-c:v",
        encoder,
        *extra_args,
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
            check=False,
            cwd=str(ffmpeg_dir()),
        )
    except subprocess.TimeoutExpired:
        return False, f"probe timed out after {timeout:.0f}s"
    except OSError as exc:
        return False, str(exc)[:160]
    if proc.returncode == 0:
        return True, ""
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, _clip_probe_error(detail)


def test_video_encoder(encoder: str, timeout: float = 30.0) -> tuple[bool, str, str]:
    """Run a one-frame null encode; return (ok, error, quality_tier)."""
    ensure_ffmpeg()
    last_err = "encode probe failed"
    for extra, tier in _encoder_probe_attempts(encoder):
        frames = 60 if "qsv" in encoder and tier == "full" else 1
        ok, err = _run_encoder_probe(encoder, extra, timeout, frames=frames)
        if ok:
            return True, "", tier
        if err:
            last_err = err
    return False, last_err, ""


def probe_video(path: Path, cancel: Optional[CancelToken] = None) -> VideoInfo:
    ensure_ffmpeg()
    result = run_command(
        [
            str(ffprobe_path()),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        cancel=cancel,
    )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError("Could not read video metadata. The file may be corrupt.") from exc

    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0))
    file_size = int(fmt.get("size", path.stat().st_size))
    bitrate = int(fmt.get("bit_rate", 0) or 0)

    width, height, video_codec = 0, 0, "unknown"
    audio_codec: str | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    pixel_fmt: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_space: str | None = None
    bits_per_raw_sample: int | None = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_codec == "unknown":
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            video_codec = stream.get("codec_name", "unknown")
            pixel_fmt = stream.get("pix_fmt") or None
            color_primaries = stream.get("color_primaries") or None
            color_transfer = stream.get("color_transfer") or None
            color_space = stream.get("color_space") or None
            raw_bits = stream.get("bits_per_raw_sample")
            if raw_bits not in (None, "", "N/A"):
                bits_per_raw_sample = int(raw_bits)
        elif stream.get("codec_type") == "audio" and audio_codec is None:
            audio_codec = stream.get("codec_name")
            ch = stream.get("channels")
            sr = stream.get("sample_rate")
            audio_channels = int(ch) if ch not in (None, "", "N/A") else None
            audio_sample_rate = int(sr) if sr not in (None, "", "N/A") else None

    if bitrate == 0 and duration > 0:
        bitrate = int(file_size * 8 / duration)

    if duration <= 0:
        raise ProbeError(
            "Could not read video duration. The file may be corrupt or still recording."
        )
    if video_codec == "unknown" or width <= 0 or height <= 0:
        raise ProbeError("No video stream found in this file.")

    return VideoInfo(
        path=path,
        duration=duration,
        file_size=file_size,
        width=width,
        height=height,
        bitrate=bitrate,
        video_codec=video_codec,
        audio_codec=audio_codec,
        audio_channels=audio_channels,
        audio_sample_rate=audio_sample_rate,
        pixel_fmt=pixel_fmt,
        color_primaries=color_primaries,
        color_transfer=color_transfer,
        color_space=color_space,
        bits_per_raw_sample=bits_per_raw_sample,
    )


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")


def parse_ffmpeg_time(line: str) -> float | None:
    match = _TIME_RE.search(line)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_ffmpeg_duration(line: str) -> float | None:
    match = _DURATION_RE.search(line)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)
