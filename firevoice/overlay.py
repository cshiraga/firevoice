"""Floating status overlay manager (launches statusbar.py as a child process)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional


class StatusOverlay:
    """Manages the floating status overlay as a child process."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        script = str(Path(__file__).with_name("statusbar.py"))
        try:
            self._proc = subprocess.Popen(
                [sys.executable, script],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            print(f"  ⚠️  Could not start status overlay: {exc}", flush=True)
            self._proc = None

    def set_state(self, state: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(f"{state}\n".encode())
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._proc = None

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.write(b"quit\n")
                self._proc.stdin.flush()
                self._proc.stdin.close()
            self._proc.wait(timeout=3)
        except Exception:
            self._proc.kill()
            try:
                self._proc.wait(timeout=3)
            except Exception:
                pass
        self._proc = None
