"""CustomTkinter application window."""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from app.cancel import CancelToken, CancelledError
from app.dpi_pause import attach_move_pause
from app.encoders import EncoderInfo, default_hidden_cpu_plans, probe_encoders
from app.ffmpeg import ProbeError, VideoInfo, ffmpeg_available, probe_video
from app.ffmpeg_download import download_ffmpeg
from app.paths import ffmpeg_dir
from app.version import __version__
from app.profiles import (
    can_stream_copy_audio_to_mp4,
    audio_stream_copyable,
    can_stream_copy_to_mp4,
    clear_stem_outputs,
    clear_test_outputs,
    default_mode,
    default_resolution,
    descriptive_output_stem,
    ensure_valid_bitrate_mode,
    ensure_valid_resolution,
    bitrate_mode_exceeds_source,
    resolution_is_available,
    effective_video_bitrate_kbps,
    effective_limit_bytes,
    estimate_compress_plan,
    estimate_job_duration_seconds,
    encode_time_estimate_uncertain,
    estimate_split_parts,
    format_bytes,
    format_duration,
    format_time_estimate,
    is_original_4k,
    output_dir_has_existing_files,
    safety_padding,
    should_nudge_split_instead,
    should_warn_quality_loss,
    source_video_bitrate_kbps,
    test_output_stem,
    unique_output_dir,
)
from app.splitter import (
    IncompatibleCodecError,
    OutputSizeError,
    ProcessOptions,
    TEST_CLIP_SECONDS,
    process_video,
)


def _error_message(exc: BaseException) -> str:
    """Human-readable error text; never returns empty or the literal 'None'."""
    msg = str(exc).strip()
    if not msg or msg == "None":
        name = type(exc).__name__
        if isinstance(exc, OSError) and getattr(exc, "filename", None):
            return f"{name}: could not access {exc.filename}"
        return f"{name}: an unexpected error occurred."
    return msg


def _dialog_error(msg: str, max_len: int = 500) -> str:
    """Short summary for error dialogs; full text stays in the log."""
    text = (msg or "").strip() or "An unexpected error occurred."
    if len(text) <= max_len:
        return text
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line or "ffmpeg version" in line.lower():
            continue
        if len(line) <= max_len - 30:
            return f"{line}\n\n(See log for full details.)"
    return text[: max_len - 3] + "…\n\n(See log for full details.)"


# Discord upload limits: (MB, tier label)
DISCORD_LIMIT_PRESETS: tuple[tuple[int, str], ...] = (
    (10, "Regular"),
    (50, "Nitro Basic"),
    (500, "Nitro"),
)
LIMIT_PRESETS = tuple(mb for mb, _ in DISCORD_LIMIT_PRESETS)
DISCORD_LIMIT_LABELS = {mb: label for mb, label in DISCORD_LIMIT_PRESETS}
LIMIT_CHIP_SELECTED = "#2a4a6e"
LIMIT_CHIP_SELECTED_HOVER = "#3a5a7e"
LIMIT_CHIP_NORMAL = ("gray78", "gray28")
LIMIT_CHIP_NORMAL_HOVER = ("gray70", "gray35")
LIMIT_CHIP_DISABLED = ("gray90", "gray20")
LIMIT_CHIP_DISABLED_TEXT = ("gray55", "gray45")

START_BTN_READY = "#2d8a4e"
START_BTN_READY_HOVER = "#247a42"
TEST_BTN_READY = "#c9a227"
TEST_BTN_READY_HOVER = "#b08f1f"
ACTION_BTN_DISABLED = ("gray70", "gray30")
ACTION_BTN_DISABLED_HOVER = ("gray60", "gray40")

UI_SCALE = 0.9

# Window size is not scaled — widgets are, so the shell stays roomy at 0.9 widget scale.
WINDOW_WIDTH = 1520
WINDOW_HEIGHT = 860
WINDOW_MIN_WIDTH = 1200
WINDOW_MIN_HEIGHT = 720


def _ui(n: float) -> int:
    return max(1, round(n * UI_SCALE))


def _stabilize_scrollable_frame(frame: ctk.CTkScrollableFrame) -> None:
    """Debounce CTkScrollableFrame layout updates during window move/resize."""
    state: dict[str, int | None] = {"after_id": None, "last_w": 0, "last_h": 0}

    def _on_configure(event: tk.Event) -> None:
        if event.widget is not frame:
            return
        w, h = event.width, event.height
        if w == state["last_w"] and h == state["last_h"]:
            return
        state["last_w"], state["last_h"] = w, h
        if state["after_id"] is not None:
            frame.after_cancel(state["after_id"])

        def _update_scrollregion() -> None:
            state["after_id"] = None
            canvas = frame._parent_canvas
            canvas.configure(scrollregion=canvas.bbox("all"))

        state["after_id"] = frame.after(32, _update_scrollregion)

    frame.unbind("<Configure>")
    frame.bind("<Configure>", _on_configure)


def _windows_monitor_work_area_at_cursor() -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) work area for the monitor under the cursor."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return _windows_monitor_work_area_at_point(pt.x, pt.y)
    except (AttributeError, OSError):
        return None


def _windows_monitor_work_area_at_point(x: int, y: int) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        pt = wintypes.POINT(x, y)
        monitor = ctypes.windll.user32.MonitorFromPoint(pt, 2)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    except (AttributeError, OSError):
        return None


def _windows_primary_work_area() -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        pt = wintypes.POINT(0, 0)
        monitor = ctypes.windll.user32.MonitorFromPoint(pt, 1)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    except (AttributeError, OSError):
        return None


def _windows_monitor_work_area_for_window(tk_window: tk.Misc) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        hwnd = _windows_window_hwnd(tk_window)
        if not hwnd:
            return _windows_primary_work_area()
        monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return _windows_primary_work_area()
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    except (AttributeError, OSError):
        return _windows_primary_work_area()


def _windows_window_hwnd(tk_window: tk.Misc) -> int:
    import ctypes

    hwnd = ctypes.windll.user32.GetParent(tk_window.winfo_id())
    return hwnd if hwnd else tk_window.winfo_id()


def _windows_window_outer_size(tk_window: tk.Misc) -> tuple[int, int]:
    if sys.platform != "win32":
        return WINDOW_WIDTH, WINDOW_HEIGHT
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        hwnd = _windows_window_hwnd(tk_window)
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 0 and h > 0:
                return w, h
    except (AttributeError, OSError):
        pass
    return WINDOW_WIDTH, WINDOW_HEIGHT


def _windows_move_window(tk_window: tk.Misc, x: int, y: int) -> bool:
    return _windows_set_window_bounds(tk_window, x, y, 0, 0, move_only=True)


def _windows_set_window_bounds(
    tk_window: tk.Misc,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    move_only: bool = False,
) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        hwnd = _windows_window_hwnd(tk_window)
        flags = 0x0004  # SWP_NOZORDER
        if move_only:
            flags |= 0x0001  # SWP_NOSIZE
        else:
            flags |= 0x0040  # SWP_SHOWWINDOW
        return bool(
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, x, y, width, height, flags
            )
        )
    except (AttributeError, OSError):
        return False


# Right panel: unified processing plans (mode + codec in one choice)
PROCESSING_PLANS: tuple[tuple[str, str, str], ...] = (
    ("split", "Split only", "Fast · no re-encode"),
    ("hevc", "HEVC", "Smaller files"),
    ("h264", "H.264", "Larger files"),
    ("av1", "AV1", "Smallest files"),
)
PLAN_BY_ID: dict[str, tuple[str, str, str]] = {p[0]: p for p in PROCESSING_PLANS}
PLAN_ORDER: tuple[str, ...] = ("split", "hevc", "h264", "av1")
PLAN_LABEL_WRAP = _ui(520)
SOURCE_COLUMN_WRAP = _ui(340)
SYSTEM_COLUMN_WRAP = _ui(248)
GPU_SCROLL_HEIGHT = 48
LIMIT_CHIP_WIDTH = 76
RESOLUTION_PRESETS: tuple[tuple[str, str], ...] = (
    ("original", "Source"),
    ("4k", "4K"),
    ("1080p", "1080p"),
    ("720p", "720p"),
)
BITRATE_PRESETS: tuple[tuple[str, str], ...] = (
    ("source", "Source"),
    ("super_high", "Super High"),
    ("high", "High"),
    ("balanced", "Balanced"),
    ("compact", "Compact"),
)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        ctk.set_widget_scaling(UI_SCALE)

        self.title(f"DC Video Splitter v{__version__}")
        self._drag_ghost_active = False
        self._ghost_frame: ctk.CTkFrame | None = None
        self._suppress_drag_ghost = False
        self._placing_window = False
        self._window_zoomed = False
        self._lock_window_size()
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self.encoder_info: EncoderInfo | None = None
        self._encoders_ready = False
        self.video_info: VideoInfo | None = None
        self.video_path: Path | None = None
        self.processing = False
        self._closing = False
        self._ffmpeg_downloading = False
        self._encoder_probing = False
        self._cancel_token: CancelToken | None = None
        self._download_cancel: CancelToken | None = None
        self._last_output_dir: Path | None = None

        self.limit_mb = tk.DoubleVar(value=500.0)
        self.custom_limit = tk.StringVar(value="500")
        self.allow_split = tk.BooleanVar(value=True)
        self.mode = tk.StringVar(value="compress_split")
        self.resolution = tk.StringVar(value="original")
        self.bitrate_mode = tk.StringVar(value="source")
        self.codec = tk.StringVar(value="h264")
        self.show_cpu_encoders = tk.BooleanVar(value=False)
        self.gpu_two_pass = tk.BooleanVar(value=False)
        self.descriptive_filenames = tk.BooleanVar(value=False)
        self.output_dir = tk.StringVar(value="")
        self._limit_chip_buttons: dict[float, ctk.CTkButton] = {}
        self._resolution_chip_buttons: dict[str, ctk.CTkButton] = {}
        self._bitrate_chip_buttons: dict[str, ctk.CTkButton] = {}

        self._build_ui()
        attach_move_pause(
            self,
            on_drag_start=self._enter_drag_ghost,
            on_drag_end=self._exit_drag_ghost,
        )
        self._init_encoders()
        self.after_idle(self._place_window)
        self.after(100, self._place_window)
        self.after(1200, self._place_window)
        self.bind("<Configure>", self._sync_window_mode, add="+")

    def _sync_window_mode(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        zoomed = self.state() == "zoomed"
        if zoomed == self._window_zoomed:
            return
        self._window_zoomed = zoomed
        if zoomed:
            self._unlock_for_maximize()
        else:
            self._lock_window_size()

    def _unlock_for_maximize(self) -> None:
        work = _windows_monitor_work_area_for_window(self)
        if work:
            px_w = work[2] - work[0]
            px_h = work[3] - work[1]
            try:
                lw = max(WINDOW_MIN_WIDTH, round(self._reverse_window_scaling(px_w)))
                lh = max(WINDOW_MIN_HEIGHT, round(self._reverse_window_scaling(px_h)))
            except AttributeError:
                lw, lh = px_w, px_h
            self.maxsize(lw, lh)
        else:
            self.maxsize(10000, 10000)
        self.after_idle(self._fill_work_area)

    def _fill_work_area(self) -> None:
        if sys.platform != "win32":
            return
        work = _windows_monitor_work_area_for_window(self)
        if not work:
            return
        left, top, right, bottom = work
        _windows_set_window_bounds(self, left, top, right - left, bottom - top)

    def _lock_window_size(self) -> None:
        """Keep CustomTkinter from growing the window after layout/Configure events."""
        if self.state() == "zoomed":
            return
        self._current_width = WINDOW_WIDTH
        self._current_height = WINDOW_HEIGHT
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.maxsize(WINDOW_WIDTH, WINDOW_HEIGHT)

    def _place_window(self, *, _retry: bool = False) -> None:
        if (
            getattr(self, "_placing_window", False)
            or getattr(self, "_dpi_move_active", False)
            or getattr(self, "_drag_ghost_active", False)
            or self.state() == "zoomed"
        ):
            return

        self._placing_window = True
        try:
            self._place_window_impl(_retry=_retry)
        finally:
            self._placing_window = False

    def _place_window_impl(self, *, _retry: bool = False) -> None:
        self._lock_window_size()
        self.update_idletasks()

        w, h = WINDOW_WIDTH, WINDOW_HEIGHT
        outer = _windows_window_outer_size(self)
        if outer[0] >= WINDOW_MIN_WIDTH:
            w = outer[0]
        if outer[1] >= WINDOW_MIN_HEIGHT:
            h = outer[1]

        work_area = _windows_monitor_work_area_for_window(self)
        if work_area is None:
            work_area = _windows_primary_work_area()
        if work_area is None:
            work_area = _windows_monitor_work_area_at_cursor()
        if work_area:
            left, top, right, bottom = work_area
            x = left + (right - left - w) // 2
            y = top + (bottom - top - h) // 2
            x = max(left, min(x, right - w))
            y = max(top, min(y, bottom - h))
        else:
            x = max(0, (self.winfo_screenwidth() - w) // 2)
            y = max(0, (self.winfo_screenheight() - h) // 2)

        self._block_update_dimensions_event = True
        self._suppress_drag_ghost = True
        try:
            moved = _windows_move_window(self, x, y)
            if not moved:
                if sys.platform == "win32" and not _retry:
                    self.after(50, lambda: self._place_window(_retry=True))
                    return
                try:
                    rx = round(self._reverse_window_scaling(x))
                    ry = round(self._reverse_window_scaling(y))
                    self.geometry(f"+{rx}+{ry}")
                except (AttributeError, tk.TclError):
                    self.geometry(f"+{x}+{y}")
        finally:
            def _clear_place_flags() -> None:
                self._block_update_dimensions_event = False
                self._suppress_drag_ghost = False

            self.after(50, _clear_place_flags)

    def _enter_drag_ghost(self) -> None:
        if self._drag_ghost_active:
            return
        self._drag_ghost_active = True
        self.content_scroll.pack_forget()
        self.bottom_frame.pack_forget()
        if self._ghost_frame is None:
            self._ghost_frame = ctk.CTkFrame(
                self,
                fg_color=("#1c1c1c", "#1c1c1c"),
                corner_radius=0,
            )
        self._ghost_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        try:
            self._saved_window_alpha = float(self.attributes("-alpha"))
            self.attributes("-alpha", 0.55)
        except (tk.TclError, ValueError, TypeError):
            pass

    def _exit_drag_ghost(self) -> None:
        if not self._drag_ghost_active:
            return
        self._drag_ghost_active = False
        if self._ghost_frame is not None:
            self._ghost_frame.place_forget()
        self.bottom_frame.pack(fill="x", side="bottom", padx=12, pady=(0, 10))
        self.content_scroll.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        try:
            self.attributes("-alpha", getattr(self, "_saved_window_alpha", 1.0))
        except tk.TclError:
            pass

    def _background_busy(self) -> bool:
        return self.processing or self._ffmpeg_downloading or self._encoder_probing

    def _close_busy_message(self) -> str:
        if self.processing:
            return "An encoding job is still running."
        if self._ffmpeg_downloading:
            return "FFmpeg is still downloading."
        return "GPU encoders are still being detected."

    def _on_close_request(self) -> None:
        if self._closing:
            return
        if not self._background_busy():
            self.destroy()
            return
        if not messagebox.askyesno(
            "Cancel and exit?",
            f"{self._close_busy_message()}\n\n"
            "Cancel it and close the app?\n\n"
            "Partial files may remain in the output folder.",
        ):
            return
        self._closing = True
        if self.processing and self._cancel_token is not None:
            self._cancel_token.request_cancel()
            self.status_label.configure(text="Cancelling...")
        if self._ffmpeg_downloading and self._download_cancel is not None:
            self._download_cancel.request_cancel()
            self.status_label.configure(text="Cancelling download...")
        self._finish_close()

    def _finish_close(self) -> None:
        if self.processing or self._ffmpeg_downloading or self._encoder_probing:
            if self.winfo_exists():
                self.after(100, self._finish_close)
            return
        if self.winfo_exists():
            self.destroy()

    def _section(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=10, pady=(8, 4))
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="x", padx=10, pady=(0, 8))
        return body

    def _build_ui(self) -> None:
        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_frame.pack(fill="x", side="bottom", padx=12, pady=(0, 10))

        self.progress = ctk.CTkProgressBar(self.bottom_frame)
        self.progress.pack(fill="x", pady=(0, 4))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(self.bottom_frame, text="Ready")
        self.status_label.pack(anchor="w", pady=(0, 6))

        self.action_row = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        self.action_row.pack(fill="x")
        self.start_btn = ctk.CTkButton(
            self.action_row,
            text="Start",
            height=36,
            command=self._start,
            state="disabled",
            fg_color=ACTION_BTN_DISABLED,
            hover_color=ACTION_BTN_DISABLED_HOVER,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.test_btn = ctk.CTkButton(
            self.action_row,
            text="Test 15 sec",
            height=36,
            width=96,
            command=self._start_test,
            state="disabled",
            fg_color=ACTION_BTN_DISABLED,
            hover_color=ACTION_BTN_DISABLED_HOVER,
        )
        self.test_btn.pack(side="left", padx=(0, 6))
        self.cancel_btn = ctk.CTkButton(
            self.action_row,
            text="Cancel",
            height=36,
            width=90,
            command=self._cancel,
            state="disabled",
            fg_color="#8b3a3a",
            hover_color="#6e2d2d",
        )
        self.cancel_btn.pack(side="right")
        self.open_folder_btn = ctk.CTkButton(
            self.action_row,
            text="Open folder",
            height=36,
            width=90,
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_folder_btn.pack(side="right", padx=(0, 6))

        self.log_frame = ctk.CTkFrame(self.bottom_frame)
        ctk.CTkLabel(self.log_frame, text="Log").pack(anchor="w", padx=10, pady=(6, 0))
        self.log_box = ctk.CTkTextbox(self.log_frame, height=88)
        self.log_box.pack(fill="x", padx=10, pady=(4, 8))
        self.log_frame.pack(fill="x", pady=(8, 0))

        self.content_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.content_scroll.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        _stabilize_scrollable_frame(self.content_scroll)

        self.main_frame = ctk.CTkFrame(self.content_scroll, fg_color="transparent")
        self.main_frame.pack(fill="x", anchor="n")
        self.main_frame.grid_columnconfigure(0, weight=3, minsize=_ui(280))
        self.main_frame.grid_columnconfigure(1, weight=2, minsize=_ui(240))
        self.main_frame.grid_columnconfigure(2, weight=5, minsize=_ui(560))

        col_source = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        col_source.grid(row=0, column=0, sticky="new", padx=(0, 4))
        col_system = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        col_system.grid(row=0, column=1, sticky="new", padx=4)
        col_settings = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        col_settings.grid(row=0, column=2, sticky="new", padx=(4, 0))

        # --- Column 1: source video, metadata, output ---
        file_body = self._section(col_source, "Source video")
        file_row = ctk.CTkFrame(file_body, fg_color="transparent")
        file_row.pack(fill="x")
        self.file_label = ctk.CTkLabel(
            file_row, text="No video selected", anchor="w", wraplength=SOURCE_COLUMN_WRAP
        )
        self.file_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(file_row, text="Browse…", width=80, command=self._browse_video).pack(
            side="right", padx=(6, 0)
        )

        info_body = self._section(col_source, "Source info")
        self.info_text = ctk.CTkLabel(
            info_body,
            text="Select a video to see details.",
            justify="left",
            anchor="w",
            wraplength=SOURCE_COLUMN_WRAP,
        )
        self.info_text.pack(anchor="w")
        self.nudge_label = ctk.CTkLabel(
            info_body,
            text="",
            text_color="#f0ad4e",
            wraplength=SOURCE_COLUMN_WRAP,
            justify="left",
        )
        self.nudge_label.pack(anchor="w", pady=(6, 0))

        out_body = self._section(col_source, "Output folder")
        self.out_section = out_body.master
        out_row = ctk.CTkFrame(out_body, fg_color="transparent")
        out_row.pack(fill="x")
        ctk.CTkEntry(out_row, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        ctk.CTkButton(out_row, text="Browse…", width=80, command=self._browse_output).pack(
            side="right"
        )
        ctk.CTkCheckBox(
            out_body,
            text="Include resolution & codec in filenames",
            variable=self.descriptive_filenames,
            command=self._on_settings_changed,
        ).pack(anchor="w", pady=(6, 0))
        self.output_filename_hint = ctk.CTkLabel(
            out_body,
            text="",
            anchor="w",
            justify="left",
            wraplength=SOURCE_COLUMN_WRAP,
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self.output_filename_hint.pack(anchor="w", pady=(4, 0))

        # --- Column 2: GPU detection, split limits ---
        gpu_body = self._section(col_system, "GPU & encoders")
        gpu_scroll = ctk.CTkScrollableFrame(
            gpu_body, height=GPU_SCROLL_HEIGHT, fg_color="transparent"
        )
        gpu_scroll.pack(fill="x")
        _stabilize_scrollable_frame(gpu_scroll)
        self.gpu_text = ctk.CTkLabel(
            gpu_scroll,
            text="Detecting GPU encoders…",
            justify="left",
            anchor="nw",
            wraplength=SYSTEM_COLUMN_WRAP,
            text_color="gray",
        )
        self.gpu_text.pack(anchor="nw", fill="x", expand=True)

        limit_body = self._section(col_system, "Split (Max file size)")
        chips_row1 = ctk.CTkFrame(limit_body, fg_color="transparent")
        chips_row1.pack(fill="x")
        self.dont_split_btn = ctk.CTkButton(
            chips_row1,
            text="Don't\nsplit",
            width=LIMIT_CHIP_WIDTH,
            height=40,
            command=self._set_dont_split,
        )
        self.dont_split_btn.pack(side="left", padx=(0, 6))
        for mb, tier in DISCORD_LIMIT_PRESETS[:2]:
            btn = ctk.CTkButton(
                chips_row1,
                text=f"{tier}\n{mb} MB",
                width=LIMIT_CHIP_WIDTH,
                height=40,
                command=lambda m=mb: self._set_limit(m),
            )
            btn.pack(side="left", padx=(0, 6))
            self._limit_chip_buttons[float(mb)] = btn
        chips_row2 = ctk.CTkFrame(limit_body, fg_color="transparent")
        chips_row2.pack(fill="x", pady=(6, 0))
        for mb, tier in DISCORD_LIMIT_PRESETS[2:]:
            btn = ctk.CTkButton(
                chips_row2,
                text=f"{tier}\n{mb} MB",
                width=LIMIT_CHIP_WIDTH,
                height=40,
                command=lambda m=mb: self._set_limit(m),
            )
            btn.pack(side="left", padx=(0, 6))
            self._limit_chip_buttons[float(mb)] = btn
        custom_row = ctk.CTkFrame(limit_body, fg_color="transparent")
        custom_row.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(custom_row, text="Custom:").pack(side="left")
        self.custom_limit_entry = ctk.CTkEntry(
            custom_row, textvariable=self.custom_limit, width=64, height=28
        )
        self.custom_limit_entry.pack(side="left", padx=(4, 4))
        ctk.CTkButton(
            custom_row, text="Apply", width=52, height=28, command=self._apply_custom_limit
        ).pack(side="left")
        self.limit_hint = ctk.CTkLabel(
            limit_body, text="", text_color="gray", wraplength=SYSTEM_COLUMN_WRAP
        )
        self.limit_hint.pack(anchor="w", pady=(6, 0))
        self.limit_frame = limit_body

        # --- Column 3: processing settings ---
        self.settings_placeholder = ctk.CTkLabel(
            col_settings,
            text="Select a video to configure processing settings.",
            text_color="gray",
            wraplength=PLAN_LABEL_WRAP,
            justify="left",
        )

        self.settings_panel = ctk.CTkFrame(col_settings, fg_color="transparent")

        self.plan_section_frame = ctk.CTkFrame(self.settings_panel)
        self.plan_section_frame.pack(fill="x", anchor="n")
        ctk.CTkLabel(
            self.plan_section_frame,
            text="Processing settings",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 4))
        plan_body = ctk.CTkFrame(self.plan_section_frame, fg_color="transparent")
        plan_body.pack(fill="x", anchor="n", padx=10, pady=(0, 8))

        self.processing_stack = ctk.CTkFrame(plan_body, fg_color="transparent")
        self.processing_stack.pack(fill="x", anchor="n")
        self.processing_stack.grid_columnconfigure(0, weight=1)

        self.resolution_row = ctk.CTkFrame(self.processing_stack, fg_color="transparent")
        ctk.CTkLabel(
            self.resolution_row,
            text="Resolution:",
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", pady=(0, 4))
        res_chips = ctk.CTkFrame(self.resolution_row, fg_color="transparent")
        res_chips.pack(fill="x", anchor="w")
        for val, label in RESOLUTION_PRESETS:
            btn = ctk.CTkButton(
                res_chips,
                text=label,
                width=76,
                height=32,
                font=ctk.CTkFont(size=12),
                command=lambda v=val: self._set_resolution(v),
            )
            btn.pack(side="left", padx=(0, 6))
            self._resolution_chip_buttons[val] = btn

        self.bitrate_row = ctk.CTkFrame(self.processing_stack, fg_color="transparent")
        ctk.CTkLabel(
            self.bitrate_row,
            text="Bitrate:",
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", pady=(0, 4))
        br_chips = ctk.CTkFrame(self.bitrate_row, fg_color="transparent")
        br_chips.pack(fill="x", anchor="w")
        for val, label in BITRATE_PRESETS:
            btn = ctk.CTkButton(
                br_chips,
                text=label,
                width=92,
                height=32,
                font=ctk.CTkFont(size=12),
                command=lambda v=val: self._set_bitrate(v),
            )
            btn.pack(side="left", padx=(0, 6))
            self._bitrate_chip_buttons[val] = btn

        self.cpu_encoders_row = ctk.CTkFrame(self.processing_stack, fg_color="transparent")
        opt_row = ctk.CTkFrame(self.cpu_encoders_row, fg_color="transparent")
        opt_row.pack(fill="x", anchor="w")
        ctk.CTkCheckBox(
            opt_row,
            text="Show CPU encoders",
            variable=self.show_cpu_encoders,
            font=ctk.CTkFont(size=12),
            command=self._on_cpu_encoders_toggled,
        ).pack(side="left", padx=(0, 16))
        self.gpu_two_pass_check = ctk.CTkCheckBox(
            opt_row,
            text="GPU 2-pass (slower, sharper)",
            variable=self.gpu_two_pass,
            font=ctk.CTkFont(size=12),
            command=self._on_settings_changed,
        )
        self.gpu_two_pass_check.pack(side="left")

        self.plan_container = ctk.CTkFrame(self.processing_stack, fg_color="transparent")
        self.plan_container.grid(row=3, column=0, sticky="ew")
        self.plan_container.grid_columnconfigure(0, weight=1)

        self._update_limit_hint()
        self._update_plan_panel_layout()
        self._set_settings_available(False)

    def _set_settings_available(self, available: bool) -> None:
        if available:
            self.settings_placeholder.pack_forget()
            self.settings_panel.pack(fill="x", anchor="n")
        else:
            self.settings_panel.pack_forget()
            self.settings_placeholder.pack(fill="x", padx=4, pady=16, anchor="n")
            self.nudge_label.configure(text="")
            self._clear_plan_cards()

    def _init_encoders(self) -> None:
        self._encoders_ready = False
        if not ffmpeg_available():
            self._prompt_ffmpeg_download()
            return

        self._update_gpu_label()
        self._encoder_probing = True
        threading.Thread(target=self._probe_encoders_worker, daemon=True).start()

    def _prompt_ffmpeg_download(self) -> None:
        folder = ffmpeg_dir()
        if messagebox.askyesno(
            "FFmpeg not found",
            "FFmpeg is required but was not found in:\n"
            f"{folder}\n\n"
            "Download and install it automatically now?\n"
            "(~160 MB, Windows 64-bit build from BtbN FFmpeg Builds)",
        ):
            self._log(f"FFmpeg missing — downloading to {folder}")
            self._set_status("Downloading FFmpeg…", None)
            self.progress.stop()
            self.progress.configure(mode="indeterminate")
            self.progress.start()
            self._ffmpeg_downloading = True
            self._download_cancel = CancelToken()
            threading.Thread(target=self._download_ffmpeg_worker, daemon=True).start()
            return

        self._encoders_ready = True
        self.encoder_info = None
        self._update_gpu_label()
        self._update_action_buttons()

    def _download_ffmpeg_worker(self) -> None:
        token = self._download_cancel
        try:

            def on_progress(msg: str) -> None:
                self.after(0, lambda m=msg: self._set_status(m, None))

            download_ffmpeg(on_progress, cancel=token)
            self.after(0, self._on_ffmpeg_download_done)
        except CancelledError:
            self.after(0, self._on_ffmpeg_download_cancelled)
        except Exception as exc:
            self.after(0, lambda e=exc: self._on_ffmpeg_download_failed(e))

    def _clear_ffmpeg_download_state(self) -> None:
        self._ffmpeg_downloading = False
        self._download_cancel = None
        self.progress.stop()
        self.progress.configure(mode="determinate")

    def _on_ffmpeg_download_done(self) -> None:
        self._clear_ffmpeg_download_state()
        self.progress.set(1.0)
        self._log(f"FFmpeg installed in {ffmpeg_dir()}")
        self._set_status("FFmpeg installed.", 1.0)
        if self._closing:
            self._finish_close()
            return
        self._init_encoders()

    def _on_ffmpeg_download_cancelled(self) -> None:
        self._clear_ffmpeg_download_state()
        self.progress.set(0)
        self._log("FFmpeg download cancelled.")
        self._set_status("FFmpeg download cancelled.", 0)
        self._encoders_ready = True
        self.encoder_info = None
        self._update_gpu_label()
        self._update_action_buttons()
        if self._closing:
            self._finish_close()

    def _on_ffmpeg_download_failed(self, exc: BaseException) -> None:
        self._clear_ffmpeg_download_state()
        self.progress.set(0)
        self._encoders_ready = True
        self.encoder_info = None
        msg = _error_message(exc)
        self._log(f"FFmpeg download failed: {msg}")
        if self._closing:
            self._finish_close()
            return
        messagebox.showerror(
            "FFmpeg download failed",
            msg + f"\n\nInstall manually into:\n{ffmpeg_dir()}",
        )
        self._update_gpu_label()
        self._update_action_buttons()

    def _probe_encoders_worker(self) -> None:
        try:
            info = probe_encoders()
            self.after(0, lambda: self._finish_encoder_probe(info, None))
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._finish_encoder_probe(None, e))

    def _finish_encoder_probe(self, info: EncoderInfo | None, error: str | None) -> None:
        if not self.winfo_exists():
            return
        self._encoder_probing = False
        self._encoders_ready = True
        self.encoder_info = info
        if self._closing:
            self._finish_close()
            return
        if error:
            messagebox.showerror("Encoder detection failed", error)
        elif info is not None:
            self.codec.set(self._pick_default_codec())
        self._update_gpu_label()
        if self.video_info:
            self._on_settings_changed()
        else:
            self._update_action_buttons()
        self.after(50, self._place_window)

    def _update_gpu_label(self) -> None:
        if not hasattr(self, "gpu_text"):
            return
        if not self._encoders_ready:
            self.gpu_text.configure(
                text="Detecting GPU encoders…",
                text_color="gray",
            )
            return
        info = self.encoder_info
        if info is None:
            if not ffmpeg_available():
                self.gpu_text.configure(
                    text=(
                        f"FFmpeg not found in {ffmpeg_dir()}.\n"
                        "Restart the app to download, or add ffmpeg.exe and ffprobe.exe manually."
                    ),
                    text_color="#e07070",
                )
            else:
                self.gpu_text.configure(
                    text="Encoder detection failed — is FFmpeg installed?",
                    text_color="#e07070",
                )
            return

        text = "\n".join(info.hardware_summary_lines())
        if info.hw_encoders:
            color = ("gray60", "gray70")
        elif info.gpu_names and info.failed_hw_encoders:
            color = "#f0ad4e"
        elif info.gpu_names:
            color = "#f0ad4e"
        else:
            color = ("gray60", "gray70")
        self.gpu_text.configure(text=text, text_color=color)

    def _update_action_buttons(self) -> None:
        enabled = (
            bool(self.video_info)
            and self._encoders_ready
            and bool(self._visible_plans())
            and not self.processing
        )
        if enabled:
            self.start_btn.configure(
                state="normal",
                fg_color=START_BTN_READY,
                hover_color=START_BTN_READY_HOVER,
            )
            self.test_btn.configure(
                state="normal",
                fg_color=TEST_BTN_READY,
                hover_color=TEST_BTN_READY_HOVER,
            )
        else:
            self.start_btn.configure(
                state="disabled",
                fg_color=ACTION_BTN_DISABLED,
                hover_color=ACTION_BTN_DISABLED_HOVER,
            )
            self.test_btn.configure(
                state="disabled",
                fg_color=ACTION_BTN_DISABLED,
                hover_color=ACTION_BTN_DISABLED_HOVER,
            )

    def _hidden_cpu_plans(self) -> frozenset[str]:
        if not self._encoders_ready:
            return frozenset(PLAN_ORDER)
        if self.show_cpu_encoders.get():
            return frozenset()
        return default_hidden_cpu_plans(self.encoder_info)

    def _visible_plans(self) -> tuple[str, ...]:
        hidden = self._hidden_cpu_plans()
        return tuple(plan for plan in PLAN_ORDER if plan not in hidden)

    def _pick_default_codec(self) -> str:
        if not self.encoder_info:
            return "h264"
        suggested = self.encoder_info.suggested_codec
        if suggested in self._hidden_cpu_plans():
            return self._fallback_from_hidden_plan()
        return suggested

    def _fallback_from_hidden_plan(self) -> str:
        hidden = self._hidden_cpu_plans()
        for plan in PLAN_ORDER:
            if plan != "split" and plan not in hidden:
                return plan
        if self.encoder_info:
            for codec in ("hevc", "h264", "av1"):
                _, encoder, _ = self.encoder_info.pick_encoder(codec)  # type: ignore[arg-type]
                if not encoder.startswith("lib"):
                    return codec
        return "hevc"

    def _ensure_visible_plan(self) -> None:
        if self.mode.get() == "split":
            return
        if self.codec.get() in self._hidden_cpu_plans():
            self.codec.set(self._fallback_from_hidden_plan())
            self.mode.set("compress_split")

    def _on_cpu_encoders_toggled(self) -> None:
        self._ensure_visible_plan()
        self._on_settings_changed()

    def _browse_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Select video",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.webm"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._load_video(Path(path))

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_dir.set(path)

    def _set_limit(self, mb: float) -> None:
        self.allow_split.set(True)
        self.limit_mb.set(mb)
        self.custom_limit.set(str(int(mb) if mb == int(mb) else mb))
        self._on_settings_changed()

    def _set_dont_split(self) -> None:
        self.allow_split.set(False)
        self._on_settings_changed()

    def _apply_custom_limit(self) -> None:
        if not self.allow_split.get():
            return
        try:
            val = float(self.custom_limit.get())
            if val <= 0:
                raise ValueError
            self.allow_split.set(True)
            self.limit_mb.set(val)
            self._on_settings_changed()
        except ValueError:
            messagebox.showerror("Invalid limit", "Enter a positive number for file size (MB).")

    def _set_bitrate(self, bitrate_mode: str) -> None:
        if self._active_plan() == "split":
            return
        if self.video_info:
            v = self.video_info
            source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
            if bitrate_mode_exceeds_source(
                self.resolution.get(),  # type: ignore[arg-type]
                self.codec.get(),  # type: ignore[arg-type]
                source_kbps,
                v.height,
                bitrate_mode,  # type: ignore[arg-type]
            ):
                return
        self.bitrate_mode.set(bitrate_mode)
        self._on_settings_changed()

    def _set_resolution(self, resolution: str) -> None:
        if self._active_plan() == "split":
            return
        if self.video_info and not resolution_is_available(
            resolution, self.video_info.height  # type: ignore[arg-type]
        ):
            return
        self.resolution.set(resolution)
        self._on_settings_changed()

    def _active_plan(self) -> str:
        if self.mode.get() == "split":
            return "split"
        return self.codec.get()

    def _apply_compress_mode(self) -> None:
        """Use single-file compress when one part fits; otherwise compress & split."""
        if self.mode.get() == "split" or not self.video_info:
            return
        if not self.allow_split.get():
            self.mode.set("compress")
            return
        v = self.video_info
        mb = self.limit_mb.get()
        res = self.resolution.get()  # type: ignore[assignment]
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        parts, _ = estimate_compress_plan(
            v.duration,
            res,
            self.codec.get(),  # type: ignore[arg-type]
            mb,
            source_kbps,
            v.height,
            self.bitrate_mode.get(),  # type: ignore[arg-type]
            allow_split=self.allow_split.get(),
        )
        self.mode.set("compress" if parts == 1 else "compress_split")

    def _select_plan(self, plan: str) -> None:
        if plan == "split":
            self.mode.set("split")
        else:
            self.codec.set(plan)
            # Leave split mode before applying; otherwise _apply_compress_mode no-ops.
            self.mode.set("compress_split")
        self._on_settings_changed()

    def _open_output_folder(self) -> None:
        if self._last_output_dir and self._last_output_dir.is_dir():
            os.startfile(self._last_output_dir)

    def _load_video(self, path: Path) -> None:
        try:
            info = probe_video(path)
        except (FileNotFoundError, RuntimeError, ProbeError) as exc:
            messagebox.showerror("Error", str(exc))
            return

        self.video_path = path
        self.video_info = info
        self.file_label.configure(text=str(path))
        self.output_dir.set(str(path.parent / f"{path.stem}_discord_parts"))

        self.mode.set(default_mode(info.height))
        self.resolution.set(
            ensure_valid_resolution(default_resolution(info.height), info.height)
        )

        if self.encoder_info:
            self.codec.set(self._pick_default_codec())

        v = self.video_info
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        self.bitrate_mode.set(
            ensure_valid_bitrate_mode(
                self.resolution.get(),  # type: ignore[arg-type]
                self.codec.get(),  # type: ignore[arg-type]
                source_kbps,
                v.height,
                "source",
            )
        )

        self._set_settings_available(True)
        self._refresh_info()
        self._update_action_buttons()
        self._on_settings_changed()

    def _refresh_info(self) -> None:
        if not self.video_info:
            self.info_text.configure(text="")
            return
        v = self.video_info
        bitrate_mbps = v.bitrate / 1_000_000 if v.bitrate else 0
        audio_label = v.audio_codec if v.audio_codec else "none"
        self.info_text.configure(
            text=(
                f"Resolution: {v.resolution_label}\n"
                f"Duration:   {format_duration(v.duration)}\n"
                f"File size:  {format_bytes(v.file_size)}\n"
                f"Bitrate:    ~{bitrate_mbps:.1f} Mbps\n"
                f"Video:      {v.video_codec}\n"
                f"Audio:      {audio_label}"
            )
        )

    def _update_limit_hint(self) -> None:
        if not self.allow_split.get():
            self.limit_hint.configure(
                text="Don't split — one output file (may exceed size limits)"
            )
            self._update_limit_chip_styles()
            return
        mb = self.limit_mb.get()
        eff = effective_limit_bytes(mb)
        pad = int(safety_padding(mb) * 100)
        preset_match = self._matching_limit_preset(mb)
        if preset_match is not None:
            selected = f"{DISCORD_LIMIT_LABELS[int(preset_match)]} ({preset_match:g} MB)"
        else:
            selected = f"custom {mb:g} MB"
        self.limit_hint.configure(
            text=(
                f"Selected: {selected} — targeting ~{format_bytes(eff)} per part, "
                f"{pad}% safety padding"
            )
        )
        self._update_limit_chip_styles()

    def _matching_limit_preset(self, mb: float) -> float | None:
        for preset in LIMIT_PRESETS:
            if abs(mb - preset) < 0.01:
                return float(preset)
        return None

    def _update_limit_chip_styles(self) -> None:
        if not self.allow_split.get():
            self.dont_split_btn.configure(
                fg_color=LIMIT_CHIP_SELECTED,
                hover_color=LIMIT_CHIP_SELECTED_HOVER,
                text_color=("white", "white"),
            )
            for btn in self._limit_chip_buttons.values():
                btn.configure(
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
            self.custom_limit_entry.configure(
                state="disabled",
                border_color=("gray70", "gray30"),
            )
            return

        self.dont_split_btn.configure(
            fg_color=LIMIT_CHIP_NORMAL,
            hover_color=LIMIT_CHIP_NORMAL_HOVER,
            text_color=("gray10", "gray90"),
        )
        self.custom_limit_entry.configure(state="normal")
        mb = self.limit_mb.get()
        active_preset = self._matching_limit_preset(mb)
        for preset, btn in self._limit_chip_buttons.items():
            if preset == active_preset:
                btn.configure(
                    fg_color=LIMIT_CHIP_SELECTED,
                    hover_color=LIMIT_CHIP_SELECTED_HOVER,
                    text_color=("white", "white"),
                )
            else:
                btn.configure(
                    fg_color=LIMIT_CHIP_NORMAL,
                    hover_color=LIMIT_CHIP_NORMAL_HOVER,
                    text_color=("gray10", "gray90"),
                )
        if active_preset is None:
            self.custom_limit_entry.configure(border_color=LIMIT_CHIP_SELECTED)
        else:
            self.custom_limit_entry.configure(border_color=("gray70", "gray30"))

    def _update_resolution_chip_styles(self) -> None:
        active = self.resolution.get()
        source_h = self.video_info.height if self.video_info else None
        split_only = self._active_plan() == "split"
        for val, btn in self._resolution_chip_buttons.items():
            if split_only:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
                continue
            available = (
                source_h is None
                or resolution_is_available(val, source_h)  # type: ignore[arg-type]
            )
            if not available:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
            elif val == active:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_SELECTED,
                    hover_color=LIMIT_CHIP_SELECTED_HOVER,
                    text_color=("white", "white"),
                )
            else:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_NORMAL,
                    hover_color=LIMIT_CHIP_NORMAL_HOVER,
                    text_color=("gray10", "gray90"),
                )

    def _ensure_valid_bitrate(self) -> None:
        if not self.video_info or self._active_plan() == "split":
            return
        v = self.video_info
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        self.bitrate_mode.set(
            ensure_valid_bitrate_mode(
                self.resolution.get(),  # type: ignore[arg-type]
                self.codec.get(),  # type: ignore[arg-type]
                source_kbps,
                v.height,
                self.bitrate_mode.get(),  # type: ignore[arg-type]
            )
        )

    def _update_bitrate_chip_styles(self) -> None:
        active = self.bitrate_mode.get()
        split_only = self._active_plan() == "split"
        source_kbps = 0
        if self.video_info:
            v = self.video_info
            source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        for val, btn in self._bitrate_chip_buttons.items():
            if split_only:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
                continue
            exceeds = False
            if self.video_info:
                exceeds = bitrate_mode_exceeds_source(
                    self.resolution.get(),  # type: ignore[arg-type]
                    self.codec.get(),  # type: ignore[arg-type]
                    source_kbps,
                    self.video_info.height,
                    val,  # type: ignore[arg-type]
                )
            if exceeds:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
            elif val == active:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_SELECTED,
                    hover_color=LIMIT_CHIP_SELECTED_HOVER,
                    text_color=("white", "white"),
                )
            else:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_NORMAL,
                    hover_color=LIMIT_CHIP_NORMAL_HOVER,
                    text_color=("gray10", "gray90"),
                )

    def _clear_plan_cards(self) -> None:
        for child in self.plan_container.winfo_children():
            child.destroy()

    def _plan_speed_hint(self, plan: str) -> str:
        if plan == "split":
            return "fastest"
        if not self.encoder_info:
            return ""
        _, encoder, _ = self.encoder_info.pick_encoder(plan)  # type: ignore[arg-type]
        if encoder.startswith("lib"):
            return "CPU"
        return "GPU"

    def _plan_time_hint(self, plan: str) -> str:
        if not self.video_info:
            return ""
        v = self.video_info
        res = self.resolution.get()  # type: ignore[assignment]
        if plan == "split":
            encoder = "split"
            mode = "split"
        else:
            if not self.encoder_info:
                return ""
            _, encoder, _ = self.encoder_info.pick_encoder(plan)  # type: ignore[arg-type]
            mode = self.mode.get()  # type: ignore[assignment]
            if mode == "split":
                mode = "compress_split"
        seconds = estimate_job_duration_seconds(
            v.duration,
            v.file_size,
            mode,
            res,
            encoder,
            v.height,
            codec=plan if plan != "split" else "hevc",  # type: ignore[arg-type]
            gpu_two_pass=self.gpu_two_pass.get(),
            info=v,
        )
        cpu = plan != "split" and encoder.startswith("lib")
        uncertain = plan != "split" and encode_time_estimate_uncertain(
            res,
            v.height,
            encoder,
            plan,  # type: ignore[arg-type]
            self.gpu_two_pass.get(),
            v,
        )
        return format_time_estimate(seconds, cpu_encoder=cpu, uncertain=uncertain)

    def _bind_plan_card(self, widget: tk.Misc, command: Callable[[], None]) -> None:
        def handler(_event: tk.Event | None = None) -> None:
            command()

        widget.bind("<Button-1>", handler)
        if hasattr(widget, "_canvas"):
            widget._canvas.bind("<Button-1>", handler)
        if hasattr(widget, "_text_label"):
            widget._text_label.bind("<Button-1>", handler)
        for child in widget.winfo_children():
            self._bind_plan_card(child, command)

    def _plan_show_recommended(self, plan: str) -> bool:
        if plan == "split" or not self.encoder_info:
            return False
        if plan != self.encoder_info.suggested_codec:
            return False
        # CPU AV1 can take hours — never badge it as recommended.
        if plan == "av1":
            _, encoder, _ = self.encoder_info.pick_encoder("av1")  # type: ignore[arg-type]
            if encoder.startswith("lib"):
                return False
        return True

    def _plan_stats_line(self, plan: str) -> str:
        estimate = self._plan_estimate_line(plan)
        speed = self._plan_speed_hint(plan)
        return " · ".join(p for p in (estimate, speed) if p)

    def _plan_title_line(self, plan: str, title: str) -> str:
        if self._plan_show_recommended(plan):
            return f"{title} (recommended)"
        return title

    def _plan_meta_line(self, plan: str) -> str:
        stats = self._plan_stats_line(plan)
        time_est = self._plan_time_hint(plan)
        return "\n".join(line for line in (stats, time_est) if line)

    def _add_plan_label(
        self,
        parent: ctk.CTkFrame,
        text: str,
        *,
        font: ctk.CTkFont,
        text_color: tuple[str, str] | str | None,
        pady: tuple[int, int] = (0, 0),
        height: int | None = None,
    ) -> None:
        kwargs: dict = {
            "text": text,
            "anchor": "w",
            "justify": "left",
            "wraplength": PLAN_LABEL_WRAP,
            "font": font,
            "text_color": text_color,
        }
        if height is not None:
            kwargs["height"] = height
        label = ctk.CTkLabel(parent, **kwargs)
        label.pack(fill="x", anchor="w", padx=(12, 18), pady=pady)

    def _add_plan_card(self, plan: str, row: int) -> None:
        _, title, blurb = PLAN_BY_ID[plan]
        selected = plan == self._active_plan()
        if selected:
            fg_color = LIMIT_CHIP_SELECTED
            title_color = ("white", "white")
            blurb_color = ("gray92", "gray78")
            detail_color = ("gray88", "gray68")
        else:
            fg_color = ("gray90", "gray20")
            title_color = ("gray10", "gray90")
            blurb_color = ("gray40", "gray60")
            detail_color = ("gray45", "gray55")

        card = ctk.CTkFrame(
            self.plan_container,
            fg_color=fg_color,
            corner_radius=8,
            border_width=2 if selected else 1,
            border_color=LIMIT_CHIP_SELECTED if selected else ("gray75", "gray30"),
            cursor="hand2",
        )
        card.grid(row=row, column=0, sticky="ew", pady=2)

        self._add_plan_label(
            card,
            self._plan_title_line(plan, title),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=title_color,
            pady=(5, 0),
            height=22,
        )
        self._add_plan_label(
            card,
            blurb,
            font=ctk.CTkFont(size=12, slant="italic"),
            text_color=blurb_color,
            pady=(0, 0),
            height=18,
        )
        meta = self._plan_meta_line(plan)
        if meta:
            line_count = meta.count("\n") + 1
            self._add_plan_label(
                card,
                meta,
                font=ctk.CTkFont(size=12),
                text_color=detail_color,
                pady=(0, 5),
                height=8 + line_count * 17,
            )

        self._bind_plan_card(card, lambda p=plan: self._select_plan(p))

    def _update_plan_cards(self) -> None:
        self._clear_plan_cards()
        if not self.video_info:
            return

        if not self._encoders_ready:
            ctk.CTkLabel(
                self.plan_container,
                text="Detecting GPU encoders…",
                wraplength=PLAN_LABEL_WRAP,
                justify="left",
                text_color="gray",
            ).grid(row=0, column=0, sticky="w")
            self._update_action_buttons()
            return

        plans = self._visible_plans()
        if not plans:
            ctk.CTkLabel(
                self.plan_container,
                text=(
                    "No GPU encoders detected.\n"
                    "Update GPU drivers, or enable 'Show CPU encoders' below "
                    "(CPU encoding is much slower)."
                ),
                wraplength=PLAN_LABEL_WRAP,
                justify="left",
                text_color="#f0ad4e",
            ).grid(row=0, column=0, sticky="w")
            self._update_action_buttons()
            return

        for row, plan in enumerate(plans):
            self._add_plan_card(plan, row)
        self._update_action_buttons()

    def _plan_estimate_line(self, plan: str) -> str:
        if not self.video_info:
            return ""
        v = self.video_info
        mb = self.limit_mb.get()
        res = self.resolution.get()  # type: ignore[assignment]
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)

        if plan == "split":
            if not self.allow_split.get():
                return f"1 file · {format_bytes(v.file_size)} total"
            parts = estimate_split_parts(v.file_size, mb)
            return f"{parts} part{'s' if parts != 1 else ''} · {format_bytes(v.file_size)} total"

        parts, total = estimate_compress_plan(
            v.duration,
            res,
            plan,
            mb,
            source_kbps,
            v.height,
            self.bitrate_mode.get(),  # type: ignore[arg-type]
            allow_split=self.allow_split.get(),
        )
        br = self.bitrate_mode.get()  # type: ignore[assignment]
        video_kbps = effective_video_bitrate_kbps(
            res, plan, source_kbps, v.height, br  # type: ignore[arg-type]
        )
        mbps = video_kbps / 1000
        return (
            f"{parts} part{'s' if parts != 1 else ''} · ~{format_bytes(total)} · "
            f"~{mbps:.1f} Mbps"
        )

    def _update_encode_option_rows(self) -> None:
        split_only = self._active_plan() == "split"
        if split_only:
            self.gpu_two_pass_check.configure(state="disabled")
        else:
            self.gpu_two_pass_check.configure(state="normal")

    def _update_plan_panel_layout(self) -> None:
        self.resolution_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.bitrate_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.cpu_encoders_row.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self._update_resolution_chip_styles()
        self._update_bitrate_chip_styles()
        self._update_encode_option_rows()

    def _update_nudges(self) -> None:
        if not self.video_info:
            self.nudge_label.configure(text="")
            return

        v = self.video_info
        mb = self.limit_mb.get()
        res = self.resolution.get()  # type: ignore[assignment]
        split_parts = estimate_split_parts(v.file_size, mb)
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        br = self.bitrate_mode.get()  # type: ignore[assignment]
        nudge = ""

        if self.mode.get() != "split" and br == "source":
            nudge = (
                "Source bitrate — matches input quality; files may be as large as split-only."
            )
        elif (
            self.mode.get() != "split"
            and should_warn_quality_loss(
                source_kbps,
                res,
                self.codec.get(),  # type: ignore[arg-type]
                v.height,
                br,
            )
        ):
            nudge = (
                "Bitrate is much lower than source — expect visible quality loss. "
                "Try Super High, High, or Source, or use Split only."
            )
        elif self.mode.get() != "split" and is_original_4k(res, v.height):
            nudge = (
                "4K source at original resolution — files stay large. "
                "Consider 1080p for smaller uploads."
            )
        elif (
            self.mode.get() != "split"
            and self.allow_split.get()
            and should_nudge_split_instead(
                v.file_size,
                v.duration,
                res,
                self.codec.get(),  # type: ignore[arg-type]
                source_kbps,
                v.height,
                br,
            )
        ):
            nudge = (
                "Source is already efficiently encoded — Split only avoids a larger re-encode."
            )
        elif self.mode.get() == "split" and not can_stream_copy_to_mp4(v.video_codec):
            nudge = (
                f"Video codec '{v.video_codec}' cannot split to Discord MP4 — "
                "pick H.264 or HEVC above."
            )
        elif (
            self.mode.get() == "split"
            and v.audio_codec
            and not audio_stream_copyable(
                v.audio_codec, v.audio_channels, v.audio_sample_rate
            )
        ):
            if not can_stream_copy_audio_to_mp4(v.audio_codec):
                nudge = (
                    f"Audio codec '{v.audio_codec}' will be converted to AAC when splitting."
                )
            else:
                nudge = (
                    "Audio will be remuxed to AAC when splitting "
                    "(source audio metadata is incomplete)."
                )
        elif split_parts > 8 and self.mode.get() == "split" and self.allow_split.get():
            nudge = "Consider compressing — fewer parts to upload."
        self.nudge_label.configure(text=nudge)

    def _update_output_filename_hint(self) -> None:
        if not hasattr(self, "output_filename_hint"):
            return
        if not self.video_path:
            self.output_filename_hint.configure(
                text="Select a video to see an example filename."
            )
            return

        stem = self.video_path.stem
        mode = self.mode.get()  # type: ignore[assignment]
        if self.descriptive_filenames.get() and self.video_info:
            stem = descriptive_output_stem(
                stem,
                self.resolution.get(),  # type: ignore[arg-type]
                self.video_info.height,
                mode,
                self.codec.get(),  # type: ignore[arg-type]
                self.bitrate_mode.get(),  # type: ignore[arg-type]
            )

        if mode == "split" and not self.allow_split.get():
            example = f"{stem}.mp4"
        elif mode == "compress":
            example = f"{stem}_compressed.mp4"
        else:
            example = f"{stem}_part001.mp4"
            if self.video_info and self.allow_split.get():
                mb = self.limit_mb.get()
                v = self.video_info
                if mode == "split":
                    parts = estimate_split_parts(v.file_size, mb)
                else:
                    parts, _ = estimate_compress_plan(
                        v.duration,
                        self.resolution.get(),  # type: ignore[arg-type]
                        self.codec.get(),  # type: ignore[arg-type]
                        mb,
                        source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size),
                        v.height,
                        self.bitrate_mode.get(),  # type: ignore[arg-type]
                    )
                if parts > 1:
                    example += f"  (+ {parts - 1} more)"

        self.output_filename_hint.configure(text=f"Example: {example}")

    def _on_settings_changed(self) -> None:
        self._ensure_valid_bitrate()
        self._apply_compress_mode()
        self._update_limit_hint()
        self._update_plan_panel_layout()
        self._update_plan_cards()
        self._update_nudges()
        self._update_action_buttons()
        self._update_output_filename_hint()

    def _log(self, msg: str) -> None:
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _set_status(self, msg: str, progress: float | None) -> None:
        self.status_label.configure(text=msg)
        self.progress.stop()
        if progress is not None:
            self.progress.configure(mode="determinate")
            self.progress.set(progress)
        else:
            self.progress.configure(mode="indeterminate")
            self.progress.start()

    def _ui_progress(self, msg: str, progress: float | None) -> None:
        self.after(0, lambda m=msg, p=progress: self._set_status(m, p))

    def _ui_log(self, msg: str) -> None:
        self.after(0, lambda m=msg: self._log(m))

    def _cancel(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.request_cancel()
            self.status_label.configure(text="Cancelling...")

    def _start_test(self) -> None:
        self._start(test_clip=True)

    def _start(self, test_clip: bool = False) -> None:
        if self.processing or not self.video_info or not self.video_path:
            return
        if not self._encoders_ready:
            messagebox.showinfo("Please wait", "Still detecting GPU encoders…")
            return
        if not self.encoder_info:
            messagebox.showerror("Error", "Encoder detection failed. Is FFmpeg installed?")
            return

        if self.mode.get() == "split" and not can_stream_copy_to_mp4(self.video_info.video_codec):
            if messagebox.askyesno(
                "Incompatible codec",
                (
                    f"This file uses '{self.video_info.video_codec}', which cannot be split "
                    "to Discord-compatible MP4 without re-encoding.\n\n"
                    "Switch to H.264 compression?"
                ),
            ):
                self._select_plan("h264")
            else:
                return

        out = self.output_dir.get().strip()
        if not out:
            messagebox.showerror("Error", "Select an output folder.")
            return

        out_path = Path(out)
        stem = self.video_path.stem
        if test_clip:
            test_stem = test_output_stem(
                stem,
                self.resolution.get(),  # type: ignore[arg-type]
                self.video_info.height,
                self.mode.get(),  # type: ignore[arg-type]
                self.codec.get(),  # type: ignore[arg-type]
                self.bitrate_mode.get(),  # type: ignore[arg-type]
            )
            try:
                clear_test_outputs(out_path, test_stem)
            except OSError as exc:
                messagebox.showerror(
                    "Error",
                    _error_message(exc)
                    + "\n\nClose any programs using those files and try again.",
                )
                return
        else:
            output_stem = stem
            if self.descriptive_filenames.get():
                output_stem = descriptive_output_stem(
                    stem,
                    self.resolution.get(),  # type: ignore[arg-type]
                    self.video_info.height,
                    self.mode.get(),  # type: ignore[arg-type]
                    self.codec.get(),  # type: ignore[arg-type]
                    self.bitrate_mode.get(),  # type: ignore[arg-type]
                )
            if output_dir_has_existing_files(out_path, output_stem):
                choice = messagebox.askyesnocancel(
                    "Existing output files",
                    (
                        f"The output folder already contains files for '{output_stem}'.\n\n"
                        "Yes — overwrite existing files\n"
                        "No — use a new folder\n"
                        "Cancel — abort"
                    ),
                )
                if choice is None:
                    return
                if choice is True:
                    try:
                        clear_stem_outputs(out_path, output_stem)
                    except OSError as exc:
                        messagebox.showerror(
                            "Error",
                            _error_message(exc)
                            + "\n\nClose any programs using those files and try again.",
                        )
                        return
                elif choice is False:
                    out_path = unique_output_dir(out_path)
                    self.output_dir.set(str(out_path))

        opts = ProcessOptions(
            mode=self.mode.get(),  # type: ignore[arg-type]
            limit_mb=self.limit_mb.get(),
            resolution=self.resolution.get(),  # type: ignore[arg-type]
            codec=self.codec.get(),  # type: ignore[arg-type]
            output_dir=out_path,
            encoder_info=self.encoder_info,
            max_duration=TEST_CLIP_SECONDS if test_clip else None,
            bitrate_mode=self.bitrate_mode.get(),  # type: ignore[arg-type]
            allow_split=self.allow_split.get(),
            gpu_two_pass=self.gpu_two_pass.get(),
            descriptive_filenames=self.descriptive_filenames.get(),
        )

        self.processing = True
        self._cancel_token = CancelToken()
        self._update_action_buttons()
        self.cancel_btn.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.progress.stop()
        self.progress.set(0)
        self._set_status("Starting...", 0)

        token = self._cancel_token

        def worker() -> None:
            try:
                result = process_video(
                    self.video_info,  # type: ignore[arg-type]
                    opts,
                    self._ui_progress,
                    self._ui_log,
                    token,
                )
                self.after(
                    0,
                    lambda r=result, d=out_path, t=test_clip: self._on_done(
                        True,
                        (
                            f"Test clip done — {len(r.output_files)} file(s) in {d}"
                            if t
                            else f"Done — {len(r.output_files)} file(s) in {d}"
                        ),
                        cancelled=False,
                        output_dir=d,
                    ),
                )
            except CancelledError:
                self.after(
                    0,
                    lambda: self._on_done(
                        False,
                        "Cancelled — partial files may remain in the output folder.",
                        cancelled=True,
                    ),
                )
            except IncompatibleCodecError as exc:
                err = _error_message(exc)
                self.after(0, lambda e=err: self._on_done(False, e, cancelled=False))
            except OutputSizeError as exc:
                err = _error_message(exc)
                self.after(0, lambda e=err: self._on_done(False, e, cancelled=False))
            except Exception as exc:
                err = _error_message(exc)
                self._ui_log(f"ERROR: {err}")
                self.after(0, lambda e=err: self._on_done(False, e, cancelled=False))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(
        self,
        success: bool,
        msg: str,
        cancelled: bool = False,
        output_dir: Path | None = None,
    ) -> None:
        self.processing = False
        self._cancel_token = None
        self.cancel_btn.configure(state="disabled")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0 if cancelled else (1.0 if success else 0))
        self.status_label.configure(text=msg)
        self._update_action_buttons()
        if success and output_dir is not None:
            self._last_output_dir = output_dir
            self.open_folder_btn.configure(state="normal")
        else:
            self.open_folder_btn.configure(state="disabled")
        if cancelled:
            self._log(msg)
        elif not success:
            self._log(msg)
            if not self._closing:
                messagebox.showerror("Error", _dialog_error(msg))
        else:
            self._log(msg)
        if self._closing:
            self._finish_close()


def run_app() -> None:
    app = App()
    app.mainloop()
