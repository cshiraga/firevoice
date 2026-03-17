"""Trigger-key detection: keyboard matching and macOS fn/Globe key monitor."""

from __future__ import annotations

import sys
from typing import Callable, Optional, Union

from pynput import keyboard

Trigger = Union[keyboard.Key, keyboard.KeyCode]
FN_TRIGGER_NAME = "fn"

try:
    import Quartz
except ImportError:
    Quartz = None


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
    """Monitor the macOS fn/Globe key via a Quartz CGEventTap."""

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
        # Re-enable the event tap if macOS disabled it due to timeout.
        # This can happen under heavy system load or GIL contention and
        # would silently drop all subsequent fn key events (including
        # the release), leaving the microphone stuck on.
        if event_type == Quartz.kCGEventTapDisabledByTimeout:
            print("  ⚠️  Event tap disabled by macOS, re-enabling...", flush=True)
            Quartz.CGEventTapEnable(self._tap, True)
            return event

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
