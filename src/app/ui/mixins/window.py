"""Window placement, maximize, and close handling."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from app.ui.constants import WINDOW_HEIGHT, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH, WINDOW_WIDTH
from app.ui.win32 import (
    _windows_monitor_work_area_at_cursor,
    _windows_monitor_work_area_for_window,
    _windows_move_window,
    _windows_primary_work_area,
    _windows_set_window_bounds,
    _windows_window_outer_size,
)


class WindowMixin:
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
        """Keep CustomTkinter from resizing the window when content changes."""
        if self.state() == "zoomed":
            return
        self._current_width = WINDOW_WIDTH
        self._current_height = WINDOW_HEIGHT
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        # Match min to max so nudge/hint text changes cannot shrink or grow the shell.
        self.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
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
            "You will be asked whether to delete any partial output files.",
        ):
            return
        self._closing = True
        if self.processing and self._cancel_token is not None:
            self._cancel_token.request_cancel()
            self.status_label.configure(text="Cancelling...")
        if self._ffmpeg_downloading and self._download_cancel is not None:
            self._download_cancel.request_cancel()
            self.status_label.configure(text="Cancelling download...")
        if self._encoder_probing and self._probe_cancel is not None:
            self._probe_cancel.request_cancel()
            self.status_label.configure(text="Cancelling encoder detection…")
        self._finish_close()

    def _finish_close(self) -> None:
        if self.processing or self._ffmpeg_downloading or self._encoder_probing:
            if self.winfo_exists():
                self.after(100, self._finish_close)
            return
        if self.winfo_exists():
            self.destroy()
