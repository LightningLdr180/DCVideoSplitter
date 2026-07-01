"""Source video selection and metadata display."""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from app.ffmpeg import ProbeError, VideoInfo, probe_video
from app.profiles import (
    default_mode,
    default_resolution,
    ensure_valid_bitrate_mode,
    ensure_valid_resolution,
    format_bytes,
    format_duration,
    source_video_bitrate_kbps,
)


class VideoMixin:
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
