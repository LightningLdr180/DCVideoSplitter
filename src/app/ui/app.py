"""CustomTkinter application window."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from app.cancel import CancelToken
from app.dpi_pause import attach_move_pause
from app.encoders import EncoderInfo
from app.ffmpeg import VideoInfo
from app.ui.constants import UI_SCALE, WINDOW_HEIGHT, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH, WINDOW_WIDTH
from app.ui.mixins.ffmpeg_setup import FfmpegSetupMixin
from app.ui.mixins.job import JobMixin
from app.ui.mixins.layout import LayoutMixin
from app.ui.mixins.settings import SettingsMixin
from app.ui.mixins.status import StatusMixin
from app.ui.mixins.video import VideoMixin
from app.ui.mixins.window import WindowMixin
from app.version import __version__


class App(
    JobMixin,
    VideoMixin,
    SettingsMixin,
    FfmpegSetupMixin,
    LayoutMixin,
    WindowMixin,
    StatusMixin,
    ctk.CTk,
):
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
        self._probe_cancel: CancelToken | None = None
        self._cancel_token: CancelToken | None = None
        self._download_cancel: CancelToken | None = None
        self._last_output_dir: Path | None = None
        self._job_output_dir: Path | None = None
        self._job_output_stem: str | None = None
        self._job_is_test: bool = False

        self.limit_mb = tk.DoubleVar(value=500.0)
        self.custom_limit = tk.StringVar(value="500")
        self.allow_split = tk.BooleanVar(value=True)
        self.mode = tk.StringVar(value="compress_split")
        self.resolution = tk.StringVar(value="original")
        self.bitrate_mode = tk.StringVar(value="source")
        self.codec = tk.StringVar(value="h264")
        self.show_cpu_encoders = tk.BooleanVar(value=False)
        self.gpu_two_pass = tk.BooleanVar(value=False)
        self.descriptive_filenames = tk.BooleanVar(value=True)
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


def run_app() -> None:
    app = App()
    app.mainloop()
