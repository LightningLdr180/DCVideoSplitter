"""GPU detection, encoder probing, and codec suggestion."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.ffmpeg import list_encoders, test_video_encoder

if TYPE_CHECKING:
    from app.cancel import CancelToken
from app.profiles import Codec

ENCODER_PRIORITY: dict[Codec, list[str]] = {
    "h264": ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"],
    "hevc": ["hevc_nvenc", "hevc_amf", "hevc_qsv", "libx265"],
    "av1": ["av1_nvenc", "av1_amf", "av1_qsv", "libsvtav1"],
}

CPU_ENCODERS = {"h264": "libx264", "hevc": "libx265", "av1": "libsvtav1"}

CPU_VIDEO_ENCODERS = ("libx264", "libx265", "libsvtav1")

HW_VIDEO_ENCODERS = tuple(
    encoder
    for codec_encoders in ENCODER_PRIORITY.values()
    for encoder in codec_encoders
    if not encoder.startswith("lib")
)

_NV_GPU_MARKERS = ("nvidia", "geforce", "quadro", "rtx", "tesla")
_AMD_GPU_MARKERS = ("amd", "radeon")
_INTEL_GPU_MARKERS = ("intel", "uhd", "iris", "arc")


@dataclass
class EncoderInfo:
    gpu_names: list[str]
    available_encoders: set[str]
    failed_hw_encoders: tuple[str, ...]
    hw_probe_errors: dict[str, str] = field(default_factory=dict)
    qsv_quality_tiers: dict[str, str] = field(default_factory=dict)
    suggested_codec: Codec = "h264"
    suggestion_reason: str = ""
    probe_cancelled: bool = False

    def pick_encoder(self, codec: Codec) -> tuple[Codec, str, str]:
        """Return (actual_codec, ffmpeg_encoder_name, backend_label). May fallback."""
        resolved = codec
        while True:
            encoder = self._first_available(resolved)
            if encoder:
                return resolved, encoder, self._backend_label(encoder)
            fallback = self._fallback_codec(resolved)
            if fallback is None:
                return "h264", "libx264", "CPU (libx264)"
            resolved = fallback

    def _first_available(self, codec: Codec) -> str | None:
        for name in ENCODER_PRIORITY[codec]:
            if name in self.available_encoders:
                return name
        return None

    def _fallback_codec(self, codec: Codec) -> Codec | None:
        order: list[Codec] = ["av1", "hevc", "h264"]
        idx = order.index(codec)
        for candidate in order[idx + 1 :]:
            if self._first_available(candidate):
                return candidate
        return None

    def _backend_label(self, encoder: str) -> str:
        if "nvenc" in encoder:
            return f"NVENC ({encoder})"
        if "amf" in encoder:
            return f"AMF ({encoder})"
        if "qsv" in encoder:
            return f"QSV ({encoder})"
        return f"CPU ({encoder})"

    @property
    def primary_gpu(self) -> str:
        for name in self.gpu_names:
            if not _is_virtual_display_adapter(name):
                return name
        return self.gpu_names[0] if self.gpu_names else "Not detected"

    @property
    def hw_encoders(self) -> list[str]:
        return sorted(e for e in self.available_encoders if not e.startswith("lib"))

    def hardware_summary_lines(self) -> list[str]:
        """Human-readable GPU + encoder status for the UI."""
        lines: list[str] = []
        display_names = _display_gpu_names(self.gpu_names)
        if display_names:
            if len(display_names) == 1:
                lines.append(f"GPU: {display_names[0]}")
            else:
                lines.append("GPUs:")
                lines.extend(f"  • {name}" for name in display_names)
        else:
            lines.append("GPU: not detected")

        hw = self.hw_encoders
        if hw:
            lines.append(f"Hardware encoders: {', '.join(hw)}")
        else:
            lines.append("Hardware encoders: none (using CPU)")

        lines.append(
            "Probe: FFmpeg encodes one test frame (same check as a real job)."
        )

        if self.probe_cancelled:
            lines.append(
                "Encoder detection was cancelled — only verified encoders are available."
            )

        if self.failed_hw_encoders:
            lines.append(
                "Listed but failed probe: " + ", ".join(self.failed_hw_encoders)
            )
            for encoder in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
                if encoder in self.hw_probe_errors:
                    lines.append(f"NVENC error: {self.hw_probe_errors[encoder]}")
                    break
            if not self.hw_encoders and _gpu_vendors(self.gpu_names) & {"nvidia"}:
                lines.append(
                    "GPU is visible to Windows but FFmpeg cannot open NVENC — "
                    "update NVIDIA drivers, run locally (not Remote Desktop), "
                    "then restart the app."
                )

        if _gpu_encoding_likely_blocked(self.gpu_names, self.hw_encoders):
            lines.append(
                "GPU encoding is usually blocked over Remote Desktop — "
                "run the app on the PC directly for NVENC."
            )

        qsv_compat = sorted(
            encoder
            for encoder in self.hw_encoders
            if "qsv" in encoder and self.qsv_quality_tiers.get(encoder) == "compat"
        )
        if qsv_compat:
            lines.append(
                "QSV reduced settings: "
                + ", ".join(qsv_compat)
                + " (lookahead/extbrc unavailable — using faster compatible preset)"
            )

        _, _, backend = self.pick_encoder(self.suggested_codec)
        lines.append(f"Active backend: {backend}")
        return lines

    def iter_encode_attempts(self, codec: Codec) -> list[tuple[Codec, str]]:
        """Ordered (codec, encoder) pairs to try at runtime."""
        codecs_to_try: list[Codec] = []
        current: Codec | None = codec
        while current is not None:
            if current not in codecs_to_try:
                codecs_to_try.append(current)
            current = self._fallback_codec(current)
        if "h264" not in codecs_to_try:
            codecs_to_try.append("h264")

        attempts: list[tuple[Codec, str]] = []
        seen: set[tuple[Codec, str]] = set()
        hw_attempts: list[tuple[Codec, str]] = []
        cpu_attempts: list[tuple[Codec, str]] = []
        for c in codecs_to_try:
            for encoder in ENCODER_PRIORITY[c]:
                if encoder not in self.available_encoders:
                    continue
                pair = (c, encoder)
                if pair in seen:
                    continue
                seen.add(pair)
                if encoder.startswith("lib"):
                    cpu_attempts.append(pair)
                else:
                    hw_attempts.append(pair)
        attempts = hw_attempts + cpu_attempts
        if not attempts:
            attempts.append(("h264", "libx264"))
        return attempts


def iter_encoders(codec: Codec, available: set[str]) -> list[str]:
    return [e for e in ENCODER_PRIORITY[codec] if e in available]


CODEC_LABELS = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1"}

COMPRESS_CODECS: tuple[Codec, ...] = ("hevc", "h264", "av1")


def codec_has_hw_encoder(info: EncoderInfo, codec: Codec) -> bool:
    return any(
        name in info.available_encoders and not name.startswith("lib")
        for name in ENCODER_PRIORITY[codec]
    )


def cpu_only_codecs(info: EncoderInfo) -> frozenset[Codec]:
    """Codecs with no working hardware encoder on this machine."""
    return frozenset(codec for codec in COMPRESS_CODECS if not codec_has_hw_encoder(info, codec))


def default_hidden_cpu_plans(info: EncoderInfo | None) -> frozenset[str]:
    """Plans hidden when 'Show CPU encoders' is off."""
    all_plans = frozenset({"split", *COMPRESS_CODECS})
    if info is None:
        return frozenset()
    if info.hw_encoders:
        return frozenset(cpu_only_codecs(info))
    return all_plans


def _is_virtual_display_adapter(name: str) -> bool:
    low = name.lower()
    return "remote display" in low or "microsoft basic" in low


def _display_gpu_names(gpu_names: list[str]) -> list[str]:
    physical = [name for name in gpu_names if not _is_virtual_display_adapter(name)]
    virtual = [name for name in gpu_names if _is_virtual_display_adapter(name)]
    return physical + virtual


def _gpu_vendors(gpu_names: list[str]) -> set[str]:
    combined = " ".join(gpu_names).lower()
    vendors: set[str] = set()
    if any(marker in combined for marker in _NV_GPU_MARKERS):
        vendors.add("nvidia")
    if any(marker in combined for marker in _AMD_GPU_MARKERS):
        vendors.add("amd")
    if any(marker in combined for marker in _INTEL_GPU_MARKERS):
        vendors.add("intel")
    return vendors


def _encoder_matches_gpu_vendor(encoder: str, vendors: set[str]) -> bool:
    if "nvenc" in encoder:
        return "nvidia" in vendors
    if "_amf" in encoder:
        return "amd" in vendors
    if "_qsv" in encoder:
        return "intel" in vendors
    return True


def _is_windows_remote_session() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))
    except (AttributeError, OSError):
        return False


def _gpu_encoding_likely_blocked(gpu_names: list[str], hw_encoders: list[str]) -> bool:
    if hw_encoders:
        return False
    has_discrete_gpu = any(
        any(marker in name.lower() for marker in _NV_GPU_MARKERS + _AMD_GPU_MARKERS)
        for name in gpu_names
        if not _is_virtual_display_adapter(name)
    )
    if not has_discrete_gpu:
        return False
    return _is_windows_remote_session() or any(
        _is_virtual_display_adapter(name) for name in gpu_names
    )


def detect_gpu_names() -> list[str]:
    names: list[str] = []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_VideoController).Name",
            ],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            timeout=10,
            check=False,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and line.lower() != "name":
                names.append(line)
    except (OSError, subprocess.TimeoutExpired):
        pass

    if not names:
        try:
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "Name"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                timeout=10,
                check=False,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and line.lower() != "name":
                    names.append(line)
        except (OSError, subprocess.TimeoutExpired):
            pass

    if not names:
        names = _detect_gpu_names_nvidia_smi()

    return _display_gpu_names(names)


def _detect_gpu_names_nvidia_smi() -> list[str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def filter_working_encoders(
    listed: set[str],
    gpu_names: list[str],
    cancel: CancelToken | None = None,
    on_probe: Callable[[str], None] | None = None,
) -> tuple[set[str], tuple[str, ...], dict[str, str], dict[str, str], bool]:
    """Keep encoders that pass a quick one-frame encode test (hardware) or are CPU libs."""
    from app.cancel import CancelledError

    working: set[str] = set()
    probe_errors: dict[str, str] = {}
    qsv_quality_tiers: dict[str, str] = {}
    vendors = _gpu_vendors(gpu_names)
    cancelled = False

    for encoder in CPU_VIDEO_ENCODERS:
        if cancel is not None:
            try:
                cancel.check()
            except CancelledError:
                cancelled = True
                break
        if encoder in listed:
            working.add(encoder)

    probed_hw: set[str] = set()
    for encoder in HW_VIDEO_ENCODERS:
        if cancel is not None and cancel.cancelled:
            cancelled = True
            break
        if cancel is not None:
            try:
                cancel.check()
            except CancelledError:
                cancelled = True
                break
        if encoder not in listed:
            continue
        if vendors and not _encoder_matches_gpu_vendor(encoder, vendors):
            continue
        if on_probe is not None:
            on_probe(encoder)
        probed_hw.add(encoder)
        try:
            ok, err, tier = test_video_encoder(encoder, cancel=cancel)
        except CancelledError:
            cancelled = True
            break
        if ok:
            working.add(encoder)
            if "qsv" in encoder and tier:
                qsv_quality_tiers[encoder] = tier
        else:
            probe_errors[encoder] = err

    failed_hw = tuple(sorted(probed_hw - working))
    return working, failed_hw, probe_errors, qsv_quality_tiers, cancelled


def suggest_codec(encoders: set[str]) -> tuple[Codec, str]:
    """Pick the best codec based on verified-working encoders."""

    def hw_encoders(codec: Codec) -> list[str]:
        return [
            e
            for e in ENCODER_PRIORITY[codec]
            if e in encoders and not e.startswith("lib")
        ]

    av1_hw = hw_encoders("av1")
    if av1_hw:
        if av1_hw[0] == "av1_nvenc":
            return "av1", "Smallest files — your GPU supports AV1 hardware encoding"
        return "av1", "Smallest files — GPU AV1 encoding available"
    if hw_encoders("hevc"):
        return "hevc", "Good compression — GPU HEVC available"
    if hw_encoders("h264"):
        return "h264", "Fast GPU encoding — H.264 for max compatibility"
    if "libsvtav1" in encoders:
        return "av1", "Smallest files — CPU AV1 (very slow)"
    if "libx265" in encoders:
        return "hevc", "Good compression — CPU HEVC (slower)"
    return "h264", "Using CPU H.264 (slower)"


def probe_encoders(
    cancel: CancelToken | None = None,
    on_probe: Callable[[str], None] | None = None,
) -> EncoderInfo:
    from app.cancel import CancelledError

    if cancel is not None:
        cancel.check()
    gpu_names = detect_gpu_names()
    if cancel is not None:
        cancel.check()
    try:
        listed = list_encoders(cancel=cancel)
    except FileNotFoundError:
        listed = set()
    except CancelledError:
        listed = set()
    working, failed_hw, probe_errors, qsv_quality_tiers, cancelled = (
        filter_working_encoders(listed, gpu_names, cancel=cancel, on_probe=on_probe)
    )
    if cancel is not None and cancel.cancelled:
        cancelled = True
    suggested, reason = suggest_codec(working)
    if cancelled:
        reason = f"Detection cancelled — {reason}"
    return EncoderInfo(
        gpu_names=gpu_names,
        available_encoders=working,
        failed_hw_encoders=failed_hw,
        hw_probe_errors=probe_errors,
        qsv_quality_tiers=qsv_quality_tiers,
        suggested_codec=suggested,
        suggestion_reason=reason,
        probe_cancelled=cancelled,
    )
