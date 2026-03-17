"""Audio recording via sounddevice."""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from firevoice.config import Config


class AudioRecorder:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._frames: list[np.ndarray] = []
        self._stream = sd.InputStream(
            samplerate=config.sample_rate,
            channels=config.channels,
            dtype=config.dtype,
            callback=self._callback,
        )
        self._lock = threading.Lock()
        self._recording = False

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return

            self._frames = []
            self._stream.start()
            self._recording = True
            print("  🔴  Recording...", flush=True)

    def stop(self) -> Optional[np.ndarray]:
        with self._lock:
            if not self._recording:
                return None

            self._stream.stop()
            self._recording = False

        if not self._frames:
            print("  ⚠️  No audio captured.", flush=True)
            return None

        print("  ⏹️  Recording stopped. Transcribing...", flush=True)
        return np.concatenate(self._frames, axis=0)

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        del frames, time_info
        if status:
            print(f"  ⚠️  Audio status: {status}", flush=True)
        self._frames.append(indata.copy())
