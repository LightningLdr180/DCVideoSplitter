"""Limit, resolution, and bitrate chip styling."""

from __future__ import annotations

from app.profiles import (
    bitrate_mode_exceeds_source,
    effective_limit_bytes,
    ensure_valid_bitrate_mode,
    format_bytes,
    resolution_is_available,
    safety_padding,
    source_video_bitrate_kbps,
)
from app.ui.constants import (
    DISCORD_LIMIT_LABELS,
    LIMIT_CHIP_DISABLED,
    LIMIT_CHIP_DISABLED_TEXT,
    LIMIT_CHIP_NORMAL,
    LIMIT_CHIP_NORMAL_HOVER,
    LIMIT_CHIP_SELECTED,
    LIMIT_CHIP_SELECTED_HOVER,
    LIMIT_PRESETS,
)


class SettingChipsMixin:
    def _update_limit_hint(self) -> None:
        if not self.allow_split.get():
            self.limit_hint.configure(
                text="Don't split — one output file (may exceed size limits)"
            )
            self._update_limit_chip_styles()
            return
        mb = self.limit_mb.get()
        eff = effective_limit_bytes(mb)
        pad = int(safety_padding(mb) * 100)
        preset_match = self._matching_limit_preset(mb)
        if preset_match is not None:
            selected = f"{DISCORD_LIMIT_LABELS[int(preset_match)]} ({preset_match:g} MB)"
        else:
            selected = f"custom {mb:g} MB"
        self.limit_hint.configure(
            text=(
                f"Selected: {selected} — targeting ~{format_bytes(eff)} per part, "
                f"{pad}% safety padding"
            )
        )
        self._update_limit_chip_styles()

    def _matching_limit_preset(self, mb: float) -> float | None:
        for preset in LIMIT_PRESETS:
            if abs(mb - preset) < 0.01:
                return float(preset)
        return None

    def _update_limit_chip_styles(self) -> None:
        if not self.allow_split.get():
            self.dont_split_btn.configure(
                fg_color=LIMIT_CHIP_SELECTED,
                hover_color=LIMIT_CHIP_SELECTED_HOVER,
                text_color=("white", "white"),
            )
            for btn in self._limit_chip_buttons.values():
                btn.configure(
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
            self.custom_limit_entry.configure(
                state="disabled",
                border_color=("gray70", "gray30"),
            )
            return

        self.dont_split_btn.configure(
            fg_color=LIMIT_CHIP_NORMAL,
            hover_color=LIMIT_CHIP_NORMAL_HOVER,
            text_color=("gray10", "gray90"),
        )
        self.custom_limit_entry.configure(state="normal")
        mb = self.limit_mb.get()
        active_preset = self._matching_limit_preset(mb)
        for preset, btn in self._limit_chip_buttons.items():
            if preset == active_preset:
                btn.configure(
                    fg_color=LIMIT_CHIP_SELECTED,
                    hover_color=LIMIT_CHIP_SELECTED_HOVER,
                    text_color=("white", "white"),
                )
            else:
                btn.configure(
                    fg_color=LIMIT_CHIP_NORMAL,
                    hover_color=LIMIT_CHIP_NORMAL_HOVER,
                    text_color=("gray10", "gray90"),
                )
        if active_preset is None:
            self.custom_limit_entry.configure(border_color=LIMIT_CHIP_SELECTED)
        else:
            self.custom_limit_entry.configure(border_color=("gray70", "gray30"))

    def _update_resolution_chip_styles(self) -> None:
        active = self.resolution.get()
        source_h = self.video_info.height if self.video_info else None
        split_only = self._active_plan() == "split"
        for val, btn in self._resolution_chip_buttons.items():
            if split_only:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
                continue
            available = (
                source_h is None
                or resolution_is_available(val, source_h)  # type: ignore[arg-type]
            )
            if not available:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
            elif val == active:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_SELECTED,
                    hover_color=LIMIT_CHIP_SELECTED_HOVER,
                    text_color=("white", "white"),
                )
            else:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_NORMAL,
                    hover_color=LIMIT_CHIP_NORMAL_HOVER,
                    text_color=("gray10", "gray90"),
                )

    def _ensure_valid_bitrate(self) -> None:
        if not self.video_info or self._active_plan() == "split":
            return
        v = self.video_info
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        self.bitrate_mode.set(
            ensure_valid_bitrate_mode(
                self.resolution.get(),  # type: ignore[arg-type]
                self.codec.get(),  # type: ignore[arg-type]
                source_kbps,
                v.height,
                self.bitrate_mode.get(),  # type: ignore[arg-type]
            )
        )

    def _update_bitrate_chip_styles(self) -> None:
        active = self.bitrate_mode.get()
        split_only = self._active_plan() == "split"
        source_kbps = 0
        if self.video_info:
            v = self.video_info
            source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        for val, btn in self._bitrate_chip_buttons.items():
            if split_only:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
                continue
            exceeds = False
            if self.video_info:
                exceeds = bitrate_mode_exceeds_source(
                    self.resolution.get(),  # type: ignore[arg-type]
                    self.codec.get(),  # type: ignore[arg-type]
                    source_kbps,
                    self.video_info.height,
                    val,  # type: ignore[arg-type]
                )
            if exceeds:
                btn.configure(
                    state="disabled",
                    fg_color=LIMIT_CHIP_DISABLED,
                    hover_color=LIMIT_CHIP_DISABLED,
                    text_color=LIMIT_CHIP_DISABLED_TEXT,
                )
            elif val == active:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_SELECTED,
                    hover_color=LIMIT_CHIP_SELECTED_HOVER,
                    text_color=("white", "white"),
                )
            else:
                btn.configure(
                    state="normal",
                    fg_color=LIMIT_CHIP_NORMAL,
                    hover_color=LIMIT_CHIP_NORMAL_HOVER,
                    text_color=("gray10", "gray90"),
                )
