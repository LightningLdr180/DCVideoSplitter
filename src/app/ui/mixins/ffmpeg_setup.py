"""FFmpeg download and GPU encoder detection."""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from app.cancel import CancelToken, CancelledError
from app.encoders import EncoderInfo, probe_encoders
from app.ffmpeg import ffmpeg_available
from app.ffmpeg_download import download_ffmpeg
from app.paths import ffmpeg_dir
from app.ui.errors import _error_message


class FfmpegSetupMixin:
    def _init_encoders(self) -> None:
        self._encoders_ready = False
        if not ffmpeg_available():
            self._prompt_ffmpeg_download()
            return

        self._update_gpu_label()
        self._encoder_probing = True
        self._probe_cancel = CancelToken()
        self._set_status("Detecting GPU encoders…", None)
        self.cancel_btn.configure(state="normal")
        threading.Thread(target=self._probe_encoders_worker, daemon=True).start()

    def _clear_encoder_probe_state(self) -> None:
        self._encoder_probing = False
        self._probe_cancel = None
        self.progress.stop()
        self.progress.configure(mode="determinate")

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
        token = self._probe_cancel

        def on_probe(encoder: str) -> None:
            def update(e: str = encoder) -> None:
                if self._encoder_probing:
                    self._set_status(f"Testing {e}…", None)

            self.after(0, update)

        try:
            info = probe_encoders(cancel=token, on_probe=on_probe)
            self.after(
                0,
                lambda i=info: self._finish_encoder_probe(
                    i, None, cancelled=i.probe_cancelled
                ),
            )
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._finish_encoder_probe(None, e))

    def _finish_encoder_probe(
        self,
        info: EncoderInfo | None,
        error: str | None,
        *,
        cancelled: bool = False,
    ) -> None:
        if not self.winfo_exists():
            return
        self._clear_encoder_probe_state()
        self.cancel_btn.configure(state="disabled")
        self._encoders_ready = True
        self.encoder_info = info
        if self._closing:
            self._finish_close()
            return
        if cancelled and info is not None:
            self._log(
                "GPU encoder detection cancelled — using encoders verified so far."
            )
        if error:
            messagebox.showerror("Encoder detection failed", error)
        elif info is not None:
            self.codec.set(self._pick_default_codec())
        self._update_gpu_label()
        if self.video_info:
            self._on_settings_changed()
        else:
            self._update_action_buttons()
        self._set_status("Ready", 0)
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
