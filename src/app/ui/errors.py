"""UI error message helpers."""

from __future__ import annotations

def _error_message(exc: BaseException) -> str:
    """Human-readable error text; never returns empty or the literal 'None'."""
    msg = str(exc).strip()
    if not msg or msg == "None":
        name = type(exc).__name__
        if isinstance(exc, OSError) and getattr(exc, "filename", None):
            return f"{name}: could not access {exc.filename}"
        return f"{name}: an unexpected error occurred."
    return msg


def _dialog_error(msg: str, max_len: int = 500) -> str:
    """Short summary for error dialogs; full text stays in the log."""
    text = (msg or "").strip() or "An unexpected error occurred."
    if len(text) <= max_len:
        return text
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line or "ffmpeg version" in line.lower():
            continue
        if len(line) <= max_len - 30:
            return f"{line}\n\n(See log for full details.)"
    return text[: max_len - 3] + "…\n\n(See log for full details.)"
