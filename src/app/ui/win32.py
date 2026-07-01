"""Windows-specific window placement helpers."""

from __future__ import annotations

import sys
import tkinter as tk

from app.ui.constants import WINDOW_HEIGHT, WINDOW_MIN_WIDTH, WINDOW_WIDTH

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
