"""Processing settings: plans, chips, hints, and nudges."""

from __future__ import annotations

from app.ui.mixins.settings.chips import SettingChipsMixin
from app.ui.mixins.settings.controls import SettingControlsMixin
from app.ui.mixins.settings.hints import SettingHintsMixin
from app.ui.mixins.settings.plans import SettingPlansMixin


class SettingsMixin(
    SettingHintsMixin,
    SettingPlansMixin,
    SettingChipsMixin,
    SettingControlsMixin,
):
    def _on_settings_changed(self) -> None:
        self._ensure_valid_bitrate()
        self._apply_compress_mode()
        self._update_limit_hint()
        self._update_plan_panel_layout()
        self._update_plan_cards()
        self._update_nudges()
        self._update_action_buttons()
        self._update_output_filename_hint()
