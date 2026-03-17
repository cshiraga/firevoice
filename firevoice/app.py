#!/usr/bin/env python3

"""VoiceInputApp – the core voice-to-text application."""

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np
import pyautogui
from faster_whisper import WhisperModel
from pynput import keyboard

from firevoice.config import (
    Config,
    apply_replacements,
    build_initial_prompt,
    ensure_default_replacements,
    load_replacements,
    ready_file,
)
from firevoice.overlay import StatusOverlay
from firevoice.recorder import AudioRecorder
from firevoice.trigger import (
    FN_TRIGGER_NAME,
    FnKeyMonitor,
    key_matches,
    normalize_trigger_key_name,
    parse_trigger_key,
)


class VoiceInputApp:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.trigger_key_name = normalize_trigger_key_name(config.trigger_key_name)
        self.trigger_key = (
            None
            if self.trigger_key_name == FN_TRIGGER_NAME
            else parse_trigger_key(self.trigger_key_name)
        )
        self.recorder = AudioRecorder(config)
        self.trigger_held = False
        self._trigger_key_physically_down = False
        self._busy = False

        self._muted_by_us = False
        self.replacements = load_replacements(config.replacements_file)
        if not config.initial_prompt:
            config.initial_prompt = build_initial_prompt(self.replacements)
        self._trigger_events: queue.Queue[str] = queue.Queue()
        self._trigger_worker = threading.Thread(target=self._trigger_loop, daemon=True)
        self._model: Optional[WhisperModel] = None
        self._model_lock = threading.Lock()
        self._fn_monitor: Optional[FnKeyMonitor] = None
        self._listener: Optional[keyboard.Listener] = None
        self._status_icon: Optional[StatusOverlay] = None
        if sys.platform == "darwin":
            self._status_icon = StatusOverlay()
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0

    def run(self) -> None:
        self._trigger_worker.start()
        print("", flush=True)
        print(f"  🔑  Trigger: {self.trigger_key_name}  |  🧠 Model: {self.config.model_size}  |  📝 {len(self.replacements)} rules", flush=True)
        print("", flush=True)

        # Pre-load the model and warm up the full transcription pipeline
        # so the first real transcription is fast.  Two warmup calls are
        # needed:
        #   1. vad_filter=True  – loads the Silero VAD model (lazy-init).
        #   2. vad_filter=False – forces CTranslate2 to run actual Whisper
        #      inference on dummy audio, warming up internal CPU caches.
        #      (With vad_filter=True the silent dummy is filtered out and
        #       Whisper never runs, leaving the first real call slow.)
        print("  ⏳  Loading Whisper model...", flush=True)
        self._get_model()
        dummy = np.zeros(self.config.sample_rate // 10, dtype=np.float32)
        # Warm up Silero VAD
        list(self._get_model().transcribe(
            dummy, language=self.config.language, vad_filter=True,
        )[0])
        # Warm up CTranslate2 inference
        list(self._get_model().transcribe(
            dummy, language=self.config.language, vad_filter=False,
        )[0])
        print("  ✅  Model loaded. Ready!", flush=True)
        print("", flush=True)

        # Signal to the CLI that the app is fully ready.
        ready_file().write_text(str(os.getpid()))

        if self._status_icon is not None:
            self._status_icon.start()

        if self.trigger_key_name == FN_TRIGGER_NAME:
            self._fn_monitor = FnKeyMonitor(
                on_press=self._enqueue_press,
                on_release=self._enqueue_release,
            )
            self._fn_monitor.start()
            return

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
        )
        with self._listener as listener:
            listener.join()

    def _enqueue_press(self) -> None:
        self._trigger_events.put("press")

    def _enqueue_release(self) -> None:
        self._trigger_events.put("release")

    def _trigger_loop(self) -> None:
        """Process trigger key events sequentially.

        Running press/release handling in a dedicated thread ensures that
        the Quartz event-tap callback (or pynput listener callback) returns
        immediately, preventing macOS from disabling the tap due to timeout.

        A 5-second timeout on the queue acts as a safety net: if the
        trigger key was physically released but the event was lost (e.g.
        the CGEventTap was temporarily disabled), the recording is
        automatically stopped.
        """
        _SAFETY_TIMEOUT = 5.0
        while True:
            try:
                event = self._trigger_events.get(timeout=_SAFETY_TIMEOUT)
            except queue.Empty:
                # Safety: recording is active but no events arrived.
                # Check if the trigger key is actually still held.
                if not self.trigger_held:
                    continue
                key_still_down = False
                if self._fn_monitor is not None:
                    key_still_down = self._fn_monitor._fn_down
                elif self.trigger_key is not None:
                    key_still_down = self._trigger_key_physically_down
                if not key_still_down:
                    print(
                        "  ⚠️  Safety: trigger released but event missed. "
                        "Auto-stopping recording.",
                        flush=True,
                    )
                    self._handle_trigger_release()
                continue

            if event == "press":
                self._handle_trigger_press()
            elif event == "release":
                self._handle_trigger_release()

    def _on_press(self, key: object) -> None:
        if self.trigger_key is not None and key_matches(key, self.trigger_key):
            self._trigger_key_physically_down = True
            self._enqueue_press()

    def _on_release(self, key: object) -> None:
        if self.trigger_key is not None and key_matches(key, self.trigger_key):
            self._trigger_key_physically_down = False
            self._enqueue_release()

    def _handle_trigger_press(self) -> None:
        # If the previous release event was lost (e.g. CGEventTap was
        # temporarily disabled), force-stop the stale recording so the
        # user can start fresh with this press.
        if self.trigger_held:
            print("  ⚠️  Stale recording detected, force-stopping...", flush=True)
            try:
                self.recorder.stop()
            except Exception:
                pass
            if self._muted_by_us:
                self._set_mute_state(False)
                self._muted_by_us = False
            self.trigger_held = False
            if self._status_icon is not None:
                self._status_icon.set_state("idle")

        if self._busy:
            print("  ⏳  Still processing previous recording. Please wait.", flush=True)
            return

        self.trigger_held = True
        try:
            if self._status_icon is not None:
                self._status_icon.set_state("recording")
            if self.config.mute_during_recording:
                was_already_muted = self._mute_and_check_previous()
                if not was_already_muted:
                    self._muted_by_us = True
            self.recorder.start()
        except Exception as exc:
            self.trigger_held = False
            if self._muted_by_us:
                self._set_mute_state(False)
                self._muted_by_us = False
            print(f"  ❌  Failed to start recording: {exc}", flush=True)

    def _handle_trigger_release(self) -> None:
        if not self.trigger_held:
            return

        self.trigger_held = False
        audio = None
        try:
            audio = self.recorder.stop()
        except Exception as exc:
            print(f"  ❌  Failed to stop recording: {exc}", flush=True)

        if self._muted_by_us:
            self._set_mute_state(False)
            self._muted_by_us = False

        if audio is not None:
            self._busy = True
            if self._status_icon is not None:
                self._status_icon.set_state("transcribing")
            threading.Thread(
                target=self._process_audio, args=(audio,), daemon=True
            ).start()
        else:
            if self._status_icon is not None:
                self._status_icon.set_state("idle")

    def _process_audio(self, audio: np.ndarray) -> None:
        """Transcribe audio and insert the resulting text."""
        try:
            text = self._transcribe(audio)
            if text:
                normalized_text = apply_replacements(text, self.replacements)
                self._insert_text(normalized_text)
        except Exception as exc:
            print(f"  ❌  Transcription failed: {exc}", flush=True)
        finally:
            self._busy = False
            if self._status_icon is not None:
                self._status_icon.set_state("idle")

    def _get_model(self) -> WhisperModel:
        with self._model_lock:
            if self._model is None:
                print("  ⏳  Loading Whisper model...", flush=True)
                self._model = WhisperModel(
                    self.config.model_size,
                    device="cpu",
                    compute_type="int8",
                )
            return self._model

    def _transcribe(self, audio: np.ndarray) -> str:
        # Convert int16 samples to float32 in [-1.0, 1.0] range as expected
        # by faster-whisper when passing a numpy array directly.
        audio_f32 = audio.astype(np.float32).flatten() / 32768.0

        model = self._get_model()
        segments, _info = model.transcribe(
            audio_f32,
            language=self.config.language,
            vad_filter=True,
            beam_size=5,
            initial_prompt=self.config.initial_prompt,
        )
        return "".join(segment.text for segment in segments).strip()

    def _insert_text(self, text: str) -> None:
        if self.config.output_mode == "type":
            pyautogui.write(text, interval=0.01)
            return

        # Wait until the trigger key is physically released before pasting.
        # For FN triggers, check _fn_monitor._fn_down; for pynput triggers,
        # check _trigger_key_physically_down.  Both track the physical key
        # state independently of _busy / trigger_held to avoid pasting
        # while a modifier is held (which would alter the Cmd+V shortcut).
        while (
            self.trigger_held
            or self._trigger_key_physically_down
            or (self._fn_monitor is not None and self._fn_monitor._fn_down)
        ):
            time.sleep(0.05)

        self._write_clipboard(text)
        pyautogui.hotkey("command", "v", interval=0.02)
        # Allow enough time for the paste to complete before any
        # subsequent clipboard operation (e.g. the next transcription).
        time.sleep(0.15)

    def _set_mute_state(self, mute: bool) -> None:
        if sys.platform != "darwin":
            return
        state = "with" if mute else "without"
        subprocess.run(["osascript", "-e", f"set volume {state} output muted"], check=False)

    def _mute_and_check_previous(self) -> bool:
        """Mute the system output and return whether it was already muted.

        Combines the mute-state check and mute-set into a single osascript
        invocation to reduce the latency before recording starts.
        """
        if sys.platform != "darwin":
            return False
        script = (
            "set old to output muted of (get volume settings)\n"
            "set volume with output muted\n"
            "return old"
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip().lower() == "true"

    @staticmethod
    def _write_clipboard(text: str) -> None:
        subprocess.run(
            ["pbcopy"],
            input=text,
            text=True,
            check=True,
        )


def run_app() -> int:
    """Run the voice input application (foreground)."""
    ensure_default_replacements()

    try:
        app = VoiceInputApp(Config())
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2

    def _shutdown(signum: int, _frame: object) -> None:
        print(f"\n  🚫  Received signal {signum}, shutting down.", flush=True)
        if app._status_icon is not None:
            app._status_icon.stop()
        if app._fn_monitor is not None:
            app._fn_monitor.stop()
        if app._listener is not None:
            app._listener.stop()

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n  👋  Exiting.", flush=True)
    finally:
        if app._muted_by_us:
            app._set_mute_state(False)
        ready_file().unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_app())
