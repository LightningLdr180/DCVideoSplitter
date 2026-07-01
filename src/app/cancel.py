"""Cancellation support for long-running FFmpeg jobs."""

from __future__ import annotations

import subprocess
import time
from typing import Optional

KILL_TIMEOUT_SEC = 3.0


class CancelledError(Exception):
    """Raised when the user cancels a running job."""


def stop_process(proc: subprocess.Popen, kill_timeout: float = KILL_TIMEOUT_SEC) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    deadline = time.monotonic() + kill_timeout
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if proc.poll() is None:
        proc.kill()
        proc.wait()


class CancelToken:
    def __init__(self) -> None:
        self.cancelled = False
        self._proc: Optional[subprocess.Popen] = None

    def set_proc(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def clear_proc(self) -> None:
        self._proc = None

    def request_cancel(self) -> None:
        self.cancelled = True
        if self._proc is not None:
            stop_process(self._proc)

    def check(self) -> None:
        if self.cancelled:
            raise CancelledError("Cancelled by user")
