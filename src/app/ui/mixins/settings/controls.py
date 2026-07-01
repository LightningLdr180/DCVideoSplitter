"""Plan selection, mode setters, and start/test button state."""

from __future__ import annotations

from tkinter import messagebox

from app.encoders import default_hidden_cpu_plans
from app.profiles import (
    bitrate_mode_exceeds_source,
    estimate_compress_plan,
    resolution_is_available,
    source_video_bitrate_kbps,
)
from app.ui.constants import (
    ACTION_BTN_DISABLED,
    ACTION_BTN_DISABLED_HOVER,
    PLAN_ORDER,
    START_BTN_READY,
    START_BTN_READY_HOVER,
    TEST_BTN_READY,
    TEST_BTN_READY_HOVER,
)


class SettingControlsMixin:
    def _update_action_buttons(self) -> None:
        enabled = (
            bool(self.video_info)
            and self._encoders_ready
            and bool(self._visible_plans())
            and not self.processing
        )
        if enabled:
            self.start_btn.configure(
                state="normal",
                fg_color=START_BTN_READY,
                hover_color=START_BTN_READY_HOVER,
            )
            self.test_btn.configure(
                state="normal",
                fg_color=TEST_BTN_READY,
                hover_color=TEST_BTN_READY_HOVER,
            )
        else:
            self.start_btn.configure(
                state="disabled",
                fg_color=ACTION_BTN_DISABLED,
                hover_color=ACTION_BTN_DISABLED_HOVER,
            )
            self.test_btn.configure(
                state="disabled",
                fg_color=ACTION_BTN_DISABLED,
                hover_color=ACTION_BTN_DISABLED_HOVER,
            )

    def _hidden_cpu_plans(self) -> frozenset[str]:
        if not self._encoders_ready:
            return frozenset(PLAN_ORDER)
        if self.show_cpu_encoders.get():
            return frozenset()
        return default_hidden_cpu_plans(self.encoder_info)

    def _visible_plans(self) -> tuple[str, ...]:
        hidden = self._hidden_cpu_plans()
        return tuple(plan for plan in PLAN_ORDER if plan not in hidden)

    def _pick_default_codec(self) -> str:
        if not self.encoder_info:
            return "h264"
        suggested = self.encoder_info.suggested_codec
        if suggested in self._hidden_cpu_plans():
            return self._fallback_from_hidden_plan()
        return suggested

    def _fallback_from_hidden_plan(self) -> str:
        hidden = self._hidden_cpu_plans()
        for plan in PLAN_ORDER:
            if plan != "split" and plan not in hidden:
                return plan
        if self.encoder_info:
            for codec in ("hevc", "h264", "av1"):
                _, encoder, _ = self.encoder_info.pick_encoder(codec)  # type: ignore[arg-type]
                if not encoder.startswith("lib"):
                    return codec
        return "hevc"

    def _ensure_visible_plan(self) -> None:
        if self.mode.get() == "split":
            return
        if self.codec.get() in self._hidden_cpu_plans():
            self.codec.set(self._fallback_from_hidden_plan())
            self.mode.set("compress_split")

    def _on_cpu_encoders_toggled(self) -> None:
        self._ensure_visible_plan()
        self._on_settings_changed()

    def _set_limit(self, mb: float) -> None:
        self.allow_split.set(True)
        self.limit_mb.set(mb)
        self.custom_limit.set(str(int(mb) if mb == int(mb) else mb))
        self._on_settings_changed()

    def _set_dont_split(self) -> None:
        self.allow_split.set(False)
        self._on_settings_changed()

    def _apply_custom_limit(self) -> None:
        if not self.allow_split.get():
            return
        try:
            val = float(self.custom_limit.get())
            if val <= 0:
                raise ValueError
            self.allow_split.set(True)
            self.limit_mb.set(val)
            self._on_settings_changed()
        except ValueError:
            messagebox.showerror("Invalid limit", "Enter a positive number for file size (MB).")

    def _set_bitrate(self, bitrate_mode: str) -> None:
        if self._active_plan() == "split":
            return
        if self.video_info:
            v = self.video_info
            source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
            if bitrate_mode_exceeds_source(
                self.resolution.get(),  # type: ignore[arg-type]
                self.codec.get(),  # type: ignore[arg-type]
                source_kbps,
                v.height,
                bitrate_mode,  # type: ignore[arg-type]
            ):
                return
        self.bitrate_mode.set(bitrate_mode)
        self._on_settings_changed()

    def _set_resolution(self, resolution: str) -> None:
        if self._active_plan() == "split":
            return
        if self.video_info and not resolution_is_available(
            resolution, self.video_info.height  # type: ignore[arg-type]
        ):
            return
        self.resolution.set(resolution)
        self._on_settings_changed()

    def _active_plan(self) -> str:
        if self.mode.get() == "split":
            return "split"
        return self.codec.get()

    def _apply_compress_mode(self) -> None:
        """Use single-file compress when one part fits; otherwise compress & split."""
        if self.mode.get() == "split" or not self.video_info:
            return
        if not self.allow_split.get():
            self.mode.set("compress")
            return
        v = self.video_info
        mb = self.limit_mb.get()
        res = self.resolution.get()  # type: ignore[assignment]
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        parts, _ = estimate_compress_plan(
            v.duration,
            res,
            self.codec.get(),  # type: ignore[arg-type]
            mb,
            source_kbps,
            v.height,
            self.bitrate_mode.get(),  # type: ignore[arg-type]
            allow_split=self.allow_split.get(),
        )
        self.mode.set("compress" if parts == 1 else "compress_split")

    def _select_plan(self, plan: str) -> None:
        if plan == "split":
            self.mode.set("split")
        else:
            self.codec.set(plan)
            # Leave split mode before applying; otherwise _apply_compress_mode no-ops.
            self.mode.set("compress_split")
        self._on_settings_changed()
