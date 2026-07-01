"""Status bar and log helpers."""

from __future__ import annotations


class StatusMixin:
    def _log(self, msg: str) -> None:
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _set_status(self, msg: str, progress: float | None) -> None:
        self.status_label.configure(text=msg)
        self.progress.stop()
        if progress is not None:
            self.progress.configure(mode="determinate")
            self.progress.set(progress)
        else:
            self.progress.configure(mode="indeterminate")
            self.progress.start()

    def _ui_progress(self, msg: str, progress: float | None) -> None:
        self.after(0, lambda m=msg, p=progress: self._set_status(m, p))

    def _ui_log(self, msg: str) -> None:
        self.after(0, lambda m=msg: self._log(m))
