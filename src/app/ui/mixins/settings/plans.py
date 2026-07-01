"""Processing plan cards and panel layout."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk
import tkinter as tk

from app.profiles import (
    effective_video_bitrate_kbps,
    estimate_compress_plan,
    estimate_job_duration_seconds,
    encode_time_estimate_uncertain,
    estimate_split_parts,
    format_bytes,
    format_time_estimate,
    source_video_bitrate_kbps,
)
from app.ui.constants import (
    LIMIT_CHIP_SELECTED,
    PLAN_BY_ID,
    PLAN_LABEL_WRAP,
)


class SettingPlansMixin:
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
