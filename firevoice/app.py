#!/usr/bin/env python3

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

import numpy as np
import pyautogui
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard


Trigger = Union[keyboard.Key, keyboard.KeyCode]
FN_TRIGGER_NAME = "fn"

try:
    import Quartz
except ImportError:
    Quartz = None


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


def _runtime_dir() -> Path:
    """Return the runtime directory (~/.firevoice)."""
    return Path.home() / ".firevoice"


def _ready_file() -> Path:
    return _runtime_dir() / "firevoice.ready"


def _default_replacements_path() -> Path:
    override = os.getenv("VOICE_REPLACEMENTS_FILE")
    if override:
        return Path(override).expanduser()
    return _runtime_dir() / "voice-replacements.json"


def _ensure_default_replacements() -> None:
    """Copy the bundled voice-replacements.json to the runtime directory
    if it does not already exist there."""
    dest = _runtime_dir() / "voice-replacements.json"
    if dest.exists():
        return

    bundled = Path(__file__).parent / "data" / "voice-replacements.json"
    if not bundled.exists():
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")


@dataclass
class Config:
    sample_rate: int = 16_000
    channels: int = 1
    dtype: str = "int16"
    language: str = "ja"
    model_size: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    trigger_key_name: str = field(default_factory=lambda: os.getenv("VOICE_TRIGGER_KEY", "fn"))
    output_mode: str = field(default_factory=lambda: os.getenv("VOICE_OUTPUT_MODE", "paste"))
    replacements_file: Path = field(default_factory=_default_replacements_path)
    mute_during_recording: bool = field(
        default_factory=lambda: os.getenv("VOICE_MUTE_DURING_RECORDING", "true").lower() == "true"
    )
    initial_prompt: str = ""


def load_replacements(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        if os.getenv("VOICE_REPLACEMENTS_FILE"):
            raise FileNotFoundError(f"Replacement file not found: {path}")
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse replacement file {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Replacement file {path} must be a JSON object mapping spoken text to output text."
        )

    replacements: list[tuple[str, str]] = []
    for source, target in data.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError(
                f"Replacement file {path} must contain only string-to-string mappings."
            )
        if not source:
            raise ValueError(f"Replacement file {path} cannot contain an empty key.")
        replacements.append((source, target))

    return replacements


def build_initial_prompt(replacements: list[tuple[str, str]]) -> str:
    """Build a Whisper initial_prompt from replacement target values.

    Whisper uses the initial_prompt as a vocabulary hint, so listing the
    expected output terms helps it transcribe technical jargon correctly.
    The prompt is assembled by collecting unique replacement targets and
    joining them with the Japanese reading-point (、).
    """
    seen: set[str] = set()
    keywords: list[str] = []
    for _source, target in replacements:
        if target not in seen:
            seen.add(target)
            keywords.append(target)
    return "、".join(keywords)


def apply_replacements(text: str, replacements: list[tuple[str, str]]) -> str:
    normalized = text
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized


def available_trigger_keys() -> dict[str, Trigger]:
    mapping: dict[str, Optional[Trigger]] = {
        "f8": keyboard.Key.f8,
        "f9": keyboard.Key.f9,
        "f10": keyboard.Key.f10,
        "f18": keyboard.Key.f18,
        "right_alt": keyboard.Key.alt_r,
        "right_option": keyboard.Key.alt_r,
        "left_alt": keyboard.Key.alt_l,
        "left_option": keyboard.Key.alt_l,
        "media_play_pause": getattr(keyboard.Key, "media_play_pause", None),
        "media_volume_mute": getattr(keyboard.Key, "media_volume_mute", None),
    }
    return {name: value for name, value in mapping.items() if value is not None}


def parse_trigger_key(name: str) -> Trigger:
    normalized = name.strip().lower()

    mapping = available_trigger_keys()
    if normalized in mapping:
        return mapping[normalized]

    if len(normalized) == 1:
        return keyboard.KeyCode.from_char(normalized)

    supported = ", ".join(sorted(mapping))
    raise ValueError(
        f"Unsupported VOICE_TRIGGER_KEY={name!r}. "
        f"Use a single character or one of: {supported}"
    )


def normalize_trigger_key_name(name: str) -> str:
    normalized = name.strip().lower()
    if normalized == FN_TRIGGER_NAME:
        if sys.platform != "darwin":
            raise ValueError("VOICE_TRIGGER_KEY=fn is supported only on macOS.")
        return normalized
    parse_trigger_key(normalized)
    return normalized


def key_matches(event_key: object, trigger_key: Trigger) -> bool:
    if isinstance(trigger_key, keyboard.KeyCode):
        return (
            isinstance(event_key, keyboard.KeyCode)
            and event_key.char == trigger_key.char
        )
    return event_key == trigger_key


class FnKeyMonitor:
    KEYCODE_FN = 63

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        if Quartz is None:
            raise RuntimeError(
                "VOICE_TRIGGER_KEY=fn requires the pyobjc Quartz bindings. "
                "Install them in the Python environment that runs this tool: "
                "pip install pyobjc-framework-Quartz"
            )

        self.on_press = on_press
        self.on_release = on_release
        self._fn_down = False
        self._tap = None
        self._run_loop_source = None
        self._run_loop: object = None

    def start(self) -> None:
        event_mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            event_mask,
            self._handle_event,
            None,
        )
        if self._tap is None:
            raise RuntimeError(
                "Failed to monitor the fn/globe key. "
                "Add this app's Python/Terminal process to "
                "System Settings > Privacy & Security > Accessibility."
            )

        self._run_loop_source = Quartz.CFMachPortCreateRunLoopSource(
            None,
            self._tap,
            0,
        )
        self._run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(
            self._run_loop,
            self._run_loop_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(self._tap, True)
        Quartz.CFRunLoopRun()

    def stop(self) -> None:
        if self._run_loop is not None:
            Quartz.CFRunLoopStop(self._run_loop)

    def _handle_event(self, _proxy, event_type, event, _refcon):
        if event_type != Quartz.kCGEventFlagsChanged:
            return event

        keycode = Quartz.CGEventGetIntegerValueField(
            event,
            Quartz.kCGKeyboardEventKeycode,
        )
        if keycode != self.KEYCODE_FN:
            return event

        flags = Quartz.CGEventGetFlags(event)
        fn_down = bool(flags & Quartz.kCGEventFlagMaskSecondaryFn)

        if fn_down and not self._fn_down:
            self._fn_down = True
            self.on_press()
        elif not fn_down and self._fn_down:
            self._fn_down = False
            self.on_release()

        return event


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

        # Pre-load the model so the first transcription is fast.
        print("  ⏳  Loading Whisper model...", flush=True)
        self._get_model()
        print("  ✅  Model loaded. Ready!", flush=True)
        print("", flush=True)

        # Signal to the CLI that the app is fully ready.
        _ready_file().write_text(str(os.getpid()))

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
        """
        while True:
            event = self._trigger_events.get()
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
        if self.trigger_held:
            return
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
            # Drain stale trigger events that accumulated while busy,
            # so they don't cause unintended recordings.
            while not self._trigger_events.empty():
                try:
                    self._trigger_events.get_nowait()
                except queue.Empty:
                    break
            self.trigger_held = False
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
    _ensure_default_replacements()

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
        _ready_file().unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_app())
