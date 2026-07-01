"""Scrollable frame layout helpers."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

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
