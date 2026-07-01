"""UI constants, theme colors, and layout presets."""

from __future__ import annotations

# Discord upload limits: (MB, tier label)
DISCORD_LIMIT_PRESETS: tuple[tuple[int, str], ...] = (
    (10, "Regular"),
    (50, "Nitro Basic"),
    (500, "Nitro"),
)
LIMIT_PRESETS = tuple(mb for mb, _ in DISCORD_LIMIT_PRESETS)
DISCORD_LIMIT_LABELS = {mb: label for mb, label in DISCORD_LIMIT_PRESETS}
LIMIT_CHIP_SELECTED = "#2a4a6e"
LIMIT_CHIP_SELECTED_HOVER = "#3a5a7e"
LIMIT_CHIP_NORMAL = ("gray78", "gray28")
LIMIT_CHIP_NORMAL_HOVER = ("gray70", "gray35")
LIMIT_CHIP_DISABLED = ("gray90", "gray20")
LIMIT_CHIP_DISABLED_TEXT = ("gray55", "gray45")

START_BTN_READY = "#2d8a4e"
START_BTN_READY_HOVER = "#247a42"
TEST_BTN_READY = "#c9a227"
TEST_BTN_READY_HOVER = "#b08f1f"
ACTION_BTN_DISABLED = ("gray70", "gray30")
ACTION_BTN_DISABLED_HOVER = ("gray60", "gray40")

UI_SCALE = 0.9

# Window size is not scaled — widgets are, so the shell stays roomy at 0.9 widget scale.
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
WINDOW_MIN_WIDTH = 1200
WINDOW_MIN_HEIGHT = 720


def _ui(n: float) -> int:
    return max(1, round(n * UI_SCALE))
# Right panel: unified processing plans (mode + codec in one choice)
PROCESSING_PLANS: tuple[tuple[str, str, str], ...] = (
    ("split", "Split only", "Fast · no re-encode"),
    ("hevc", "HEVC", "Smaller files"),
    ("h264", "H.264", "Larger files"),
    ("av1", "AV1", "Smallest files"),
)
PLAN_BY_ID: dict[str, tuple[str, str, str]] = {p[0]: p for p in PROCESSING_PLANS}
PLAN_ORDER: tuple[str, ...] = ("split", "hevc", "h264", "av1")
PLAN_LABEL_WRAP = _ui(520)
SETTINGS_COLUMN_MIN = PLAN_LABEL_WRAP + _ui(36)
SOURCE_COLUMN_WIDTH = _ui(380)
SOURCE_COLUMN_WRAP = _ui(340)
SYSTEM_COLUMN_WIDTH = _ui(300)
SYSTEM_COLUMN_WRAP = _ui(248)
GPU_SCROLL_HEIGHT = 48
LIMIT_CHIP_WIDTH = 76
RESOLUTION_PRESETS: tuple[tuple[str, str], ...] = (
    ("original", "Source"),
    ("4k", "4K"),
    ("1080p", "1080p"),
    ("720p", "720p"),
)
BITRATE_PRESETS: tuple[tuple[str, str], ...] = (
    ("source", "Source"),
    ("super_high", "Super High"),
    ("high", "High"),
    ("balanced", "Balanced"),
    ("compact", "Compact"),
)
