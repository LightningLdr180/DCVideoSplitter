"""Pause DPI rescaling during window moves and support drag ghost callbacks."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

_HOOK_INSTALLED = False


def install_scaling_pause_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return

    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    if not hasattr(ScalingTracker, "_paused_windows"):
        ScalingTracker._paused_windows = set()
    if not hasattr(ScalingTracker, "_blocked_scaling_windows"):
        ScalingTracker._blocked_scaling_windows = set()

    _orig_update_callbacks = ScalingTracker.update_scaling_callbacks_for_window.__func__

    @classmethod
    def update_scaling_callbacks_for_window(cls, window) -> None:
        if window in cls._blocked_scaling_windows:
            return
        _orig_update_callbacks(cls, window)

    @classmethod
    def check_dpi_scaling(cls) -> None:
        new_scaling_detected = False
        paused = cls._paused_windows

        for window in cls.window_widgets_dict:
            if window in paused:
                continue
            if window.winfo_exists() and not window.state() == "iconic":
                if _apply_dpi_scaling(window):
                    new_scaling_detected = True

        for app in cls.window_widgets_dict.keys():
            try:
                if new_scaling_detected:
                    app.after(cls.loop_pause_after_new_scaling, cls.check_dpi_scaling)
                else:
                    app.after(cls.update_loop_interval, cls.check_dpi_scaling)
                return
            except Exception:
                continue

        cls.update_loop_running = False

    ScalingTracker.update_scaling_callbacks_for_window = update_scaling_callbacks_for_window
    ScalingTracker.check_dpi_scaling = check_dpi_scaling
    _HOOK_INSTALLED = True


def _apply_dpi_scaling(window: tk.Misc) -> bool:
    """Apply a pending DPI scale change for one window. Returns True if applied."""
    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    if not window.winfo_exists() or window.state() == "iconic":
        return False
    if getattr(window, "_dpi_scaling_applying", False):
        return False

    current_dpi_scaling_value = ScalingTracker.get_window_dpi_scaling(window)
    if current_dpi_scaling_value == ScalingTracker.window_dpi_scaling_dict[window]:
        return False

    ScalingTracker.window_dpi_scaling_dict[window] = current_dpi_scaling_value
    window._dpi_scaling_applying = True  # type: ignore[attr-defined]
    try:
        window.block_update_dimensions_event()
        ScalingTracker.update_scaling_callbacks_for_window(window)
        window.unblock_update_dimensions_event()
        window.update_idletasks()
    finally:
        window._dpi_scaling_applying = False  # type: ignore[attr-defined]

    return True


def _pause_scaling(window: tk.Misc) -> None:
    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    install_scaling_pause_hook()
    ScalingTracker._paused_windows.add(window)
    ScalingTracker._blocked_scaling_windows.add(window)
    window._dpi_move_active = True  # type: ignore[attr-defined]
    window._block_update_dimensions_event = True

    if getattr(window, "_suppress_drag_ghost", False):
        return
    on_start = getattr(window, "_dpi_on_drag_start", None)
    if on_start is not None:
        on_start()


def _end_move_pause(window: tk.Misc) -> None:
    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    if not getattr(window, "_dpi_move_active", False):
        return

    window._dpi_move_active = False  # type: ignore[attr-defined]
    window._block_update_dimensions_event = False
    ScalingTracker._blocked_scaling_windows.discard(window)
    _apply_dpi_scaling(window)

    if not getattr(window, "_suppress_drag_ghost", False):
        on_end = getattr(window, "_dpi_on_drag_end", None)
        if on_end is not None:
            on_end()

    ScalingTracker._paused_windows.discard(window)


def _cancel_pending_resume(window: tk.Misc) -> None:
    after_id = getattr(window, "_dpi_pause_after_id", None)
    if after_id is not None:
        window.after_cancel(after_id)
        window._dpi_pause_after_id = None  # type: ignore[attr-defined]


def attach_move_pause(
    window: tk.Misc,
    *,
    debounce_ms: int = 150,
    on_drag_start: Callable[[], None] | None = None,
    on_drag_end: Callable[[], None] | None = None,
) -> None:
    """Pause DPI rescaling while the user drags the window."""
    install_scaling_pause_hook()
    window._dpi_on_drag_start = on_drag_start  # type: ignore[attr-defined]
    window._dpi_on_drag_end = on_drag_end  # type: ignore[attr-defined]
    window._dpi_pause_after_id = None  # type: ignore[attr-defined]
    window._dpi_pause_last_geom = (0, 0, 0, 0)  # type: ignore[attr-defined]

    def on_configure(event: tk.Event) -> None:
        if event.widget is not window:
            return
        if getattr(window, "_dpi_scaling_applying", False):
            return
        if getattr(window, "_suppress_drag_ghost", False):
            return
        try:
            if window.state() == "zoomed":
                return
        except tk.TclError:
            pass

        w, h, x, y = event.width, event.height, event.x, event.y
        lw, lh, lx, ly = window._dpi_pause_last_geom  # type: ignore[attr-defined]
        window._dpi_pause_last_geom = (w, h, x, y)  # type: ignore[attr-defined]
        if lw == 0 and lh == 0:
            return
        if lx == x and ly == y:
            return

        if not getattr(window, "_dpi_move_active", False):
            _pause_scaling(window)

        _cancel_pending_resume(window)

        def _resume() -> None:
            window._dpi_pause_after_id = None  # type: ignore[attr-defined]
            _end_move_pause(window)

        window._dpi_pause_after_id = window.after(debounce_ms, _resume)  # type: ignore[attr-defined]

    window.bind("<Configure>", on_configure, add="+")
