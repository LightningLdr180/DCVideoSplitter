"""Encode job start, cancel, and completion."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from app.cancel import CancelToken, CancelledError
from app.profiles import (
    can_stream_copy_to_mp4,
    clear_stem_outputs,
    clear_test_outputs,
    descriptive_output_stem,
    output_dir_has_existing_files,
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
from app.ui.errors import _dialog_error, _error_message


class JobMixin:
    def _cancel(self) -> None:
        if self._encoder_probing and self._probe_cancel is not None:
            self._probe_cancel.request_cancel()
            self.status_label.configure(text="Cancelling encoder detection…")
            return
        if self._cancel_token is not None:
            self._cancel_token.request_cancel()
            self.status_label.configure(text="Cancelling...")

    def _clear_job_output_tracking(self) -> None:
        self._job_output_dir = None
        self._job_output_stem = None
        self._job_is_test = False

    def _offer_partial_cleanup_after_cancel(self) -> str:
        out_dir = self._job_output_dir
        stem = self._job_output_stem
        is_test = self._job_is_test
        self._clear_job_output_tracking()

        if out_dir is None or stem is None:
            return "Cancelled."
        if not output_dir_has_existing_files(out_dir, stem):
            return "Cancelled."

        if not messagebox.askyesno(
            "Delete partial files?",
            (
                "Encoding was cancelled.\n\n"
                "Delete partial output files from the output folder?\n\n"
                "Yes — remove them\n"
                "No — keep them"
            ),
        ):
            return "Cancelled — partial files kept in the output folder."

        try:
            removed = (
                clear_test_outputs(out_dir, stem)
                if is_test
                else clear_stem_outputs(out_dir, stem)
            )
        except OSError as exc:
            err = _error_message(exc)
            if not self._closing:
                messagebox.showerror(
                    "Error",
                    err + "\n\nClose any programs using those files and try again.",
                )
            return "Cancelled — could not delete all partial files."

        if removed:
            return f"Cancelled — removed {removed} partial file(s)."
        return "Cancelled."

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
            job_output_stem = test_output_stem(
                stem,
                self.resolution.get(),  # type: ignore[arg-type]
                self.video_info.height,
                self.mode.get(),  # type: ignore[arg-type]
                self.codec.get(),  # type: ignore[arg-type]
                self.bitrate_mode.get(),  # type: ignore[arg-type]
            )
            try:
                clear_test_outputs(out_path, job_output_stem)
            except OSError as exc:
                messagebox.showerror(
                    "Error",
                    _error_message(exc)
                    + "\n\nClose any programs using those files and try again.",
                )
                return
        else:
            job_output_stem = stem
            if self.descriptive_filenames.get():
                job_output_stem = descriptive_output_stem(
                    stem,
                    self.resolution.get(),  # type: ignore[arg-type]
                    self.video_info.height,
                    self.mode.get(),  # type: ignore[arg-type]
                    self.codec.get(),  # type: ignore[arg-type]
                    self.bitrate_mode.get(),  # type: ignore[arg-type]
                )
            if output_dir_has_existing_files(out_path, job_output_stem):
                choice = messagebox.askyesnocancel(
                    "Existing output files",
                    (
                        f"The output folder already contains files for '{job_output_stem}'.\n\n"
                        "Yes — overwrite existing files\n"
                        "No — use a new folder\n"
                        "Cancel — abort"
                    ),
                )
                if choice is None:
                    return
                if choice is True:
                    try:
                        clear_stem_outputs(out_path, job_output_stem)
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
        self._job_output_dir = out_path
        self._job_output_stem = job_output_stem
        self._job_is_test = test_clip
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
                self.after(0, lambda: self._on_done(False, "", cancelled=True))
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
        if cancelled:
            msg = self._offer_partial_cleanup_after_cancel()
        else:
            self._clear_job_output_tracking()
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
