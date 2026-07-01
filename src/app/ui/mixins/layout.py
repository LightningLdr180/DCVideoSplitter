"""Main window layout and widget tree."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.constants import (
    ACTION_BTN_DISABLED,
    ACTION_BTN_DISABLED_HOVER,
    BITRATE_PRESETS,
    DISCORD_LIMIT_PRESETS,
    GPU_SCROLL_HEIGHT,
    LIMIT_CHIP_WIDTH,
    PLAN_LABEL_WRAP,
    RESOLUTION_PRESETS,
    SOURCE_COLUMN_WRAP,
    SYSTEM_COLUMN_WRAP,
    _ui,
)
from app.ui.scroll import _stabilize_scrollable_frame


class LayoutMixin:
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
