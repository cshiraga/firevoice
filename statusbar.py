"""Floating status overlay for FireVoice  (runs as a child process).

Displays an Aqua-Voice-inspired pill-shaped widget at the bottom centre
of the screen.  The widget contains a coloured dot and animated waveform
bars that reflect the current application state.

State changes are sent via **stdin** as single-line commands:
  ``idle``, ``recording``, ``transcribing``, ``quit``

This module is launched as a **subprocess** so that its ``NSApplication``
event loop is fully isolated from the ``CGEventTap`` in the parent process.
"""

from __future__ import annotations

import math
import sys
import threading

if sys.platform != "darwin":
    raise ImportError("statusbar module is only supported on macOS")

import AppKit
import objc
from Quartz import (
    CGDisplayBounds,
    CGMainDisplayID,
)


# ---------------------------------------------------------------------------
# Design constants
# ---------------------------------------------------------------------------

# Pill dimensions
PILL_WIDTH = 80
PILL_HEIGHT = 36
PILL_RADIUS = PILL_HEIGHT / 2.0
BOTTOM_MARGIN = 32  # px above the bottom edge of the screen

# Waveform bars
BAR_COUNT = 5
BAR_WIDTH = 3.0
BAR_GAP = 2.5
BAR_MIN_HEIGHT = 5.0
BAR_MAX_HEIGHT = 20.0

# Dot
DOT_RADIUS = 5.0

# Flame spinner (transcribing state)
FLAME_RADIUS = 10.0
FLAME_LINE_WIDTH = 2.5
FLAME_SEGMENTS = 10
FLAME_ARC_TOTAL = 150.0  # total degrees of flame trail
FLAME_SPEED = 14.0  # degrees per frame

# Colours  (R, G, B)
PILL_BG = (0.12, 0.12, 0.14, 1.0)    # near-black, fully opaque

STATE_COLORS: dict[str, tuple[float, float, float]] = {
    "idle": (0.55, 0.55, 0.58),
    "recording": (1.0, 0.231, 0.188),     # #FF3B30
    "transcribing": (1.0, 0.231, 0.188),  # #FF3B30 (same red as recording)
}

ANIMATION_INTERVAL = 0.1  # 10 fps


# ---------------------------------------------------------------------------
# Custom NSView – draws the pill background, dot and waveform
# ---------------------------------------------------------------------------

class _PillView(AppKit.NSView):
    """Draws the entire pill widget in a single ``drawRect:`` pass."""

    def initWithFrame_(self, frame):  # noqa: N802
        self = objc.super(_PillView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._state = "idle"
        self._frame_index = 0
        self._lock = threading.Lock()
        return self

    def drawRect_(self, rect):  # noqa: N802
        with self._lock:
            state = self._state
            frame_idx = self._frame_index

        # -- pill background --
        bg = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*PILL_BG)
        bounds = self.bounds()
        pill_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, PILL_RADIUS, PILL_RADIUS,
        )
        bg.setFill()
        pill_path.fill()

        # -- accent colour --
        r, g, b = STATE_COLORS.get(state, STATE_COLORS["idle"])
        accent = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)

        # -- dot (centred based on state) --
        bounds = self.bounds()
        mid_y = bounds.size.height / 2.0

        if state == "transcribing":
            # Spinner: dot centred in pill
            dot_x = bounds.size.width / 2.0
        else:
            # Dot + bars: compute total content width and centre it
            #   dot(10) + gap(8) + bars(5*3 + 4*2.5 = 25) = 43
            content_w = DOT_RADIUS * 2 + 8.0 + BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP
            content_start = (bounds.size.width - content_w) / 2.0
            dot_x = content_start + DOT_RADIUS

        dot_rect = AppKit.NSMakeRect(
            dot_x - DOT_RADIUS, mid_y - DOT_RADIUS,
            DOT_RADIUS * 2, DOT_RADIUS * 2,
        )
        dot_path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(dot_rect)
        accent.setFill()
        dot_path.fill()

        # Outer glow for non-idle
        if state != "idle":
            glow_r = DOT_RADIUS + 3.0
            glow_rect = AppKit.NSMakeRect(
                dot_x - glow_r, mid_y - glow_r, glow_r * 2, glow_r * 2,
            )
            glow_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                r, g, b, 0.25,
            )
            glow_path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(glow_rect)
            glow_color.setFill()
            glow_path.fill()

        # -- waveform bars (idle + recording only) --
        if state != "transcribing":
            bar_heights = _compute_bar_heights(state, frame_idx)
            bars_start_x = dot_x + DOT_RADIUS + 8.0
            center_y = mid_y

            for i, h in enumerate(bar_heights):
                x = bars_start_x + i * (BAR_WIDTH + BAR_GAP)
                y = center_y - h / 2.0
                bar_rect = AppKit.NSMakeRect(x, y, BAR_WIDTH, h)
                bar_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    bar_rect, BAR_WIDTH / 2.0, BAR_WIDTH / 2.0,
                )
                accent.setFill()
                bar_path.fill()
        else:
            # -- flame trail around the dot --
            center = AppKit.NSMakePoint(dot_x, mid_y)
            base_angle = frame_idx * FLAME_SPEED

            # Draw segments from tail to head (head renders on top)
            for i in range(FLAME_SEGMENTS):
                t = i / float(FLAME_SEGMENTS - 1)  # 0=tail, 1=head

                # Arc position
                seg_len = FLAME_ARC_TOTAL / FLAME_SEGMENTS
                seg_start = base_angle - FLAME_ARC_TOTAL + i * seg_len
                seg_end = seg_start + seg_len + 2.0  # slight overlap

                # Colour: tail (faded red) -> head (bright red)
                cr = 1.0
                cg = 0.1 + t * 0.15
                cb = 0.05 + t * 0.1
                ca = 0.12 + t * 0.88

                # Organic flicker
                flicker = 0.82 + 0.18 * math.sin(frame_idx * 0.7 + i * 1.2)
                ca = min(ca * flicker, 1.0)

                radius = FLAME_RADIUS

                # Line width: thin tail -> thick head
                lw = FLAME_LINE_WIDTH * (0.4 + t * 1.0)

                seg = AppKit.NSBezierPath.bezierPath()
                seg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                    center, radius, seg_start, seg_end, False,
                )
                seg.setLineWidth_(lw)
                color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    cr, cg, cb, ca,
                )
                color.setStroke()
                seg.stroke()

            # Ember sparks near the flame head
            for j in range(3):
                spark_offset = -j * 12.0 + 4.0 * math.sin(
                    frame_idx * 1.5 + j * 3.0,
                )
                spark_angle_rad = math.radians(base_angle + spark_offset)
                sx = dot_x + FLAME_RADIUS * math.cos(spark_angle_rad)
                sy = mid_y + FLAME_RADIUS * math.sin(spark_angle_rad)
                spark_size = 1.5 + 1.0 * abs(math.sin(frame_idx * 1.2 + j))

                spark_rect = AppKit.NSMakeRect(
                    sx - spark_size / 2, sy - spark_size / 2,
                    spark_size, spark_size,
                )
                spark_path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    spark_rect,
                )
                spark_a = 0.75 - j * 0.2
                spark_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.3, 0.15, spark_a,
                )
                spark_color.setFill()
                spark_path.fill()

    # -- state updates (thread-safe) -----------------------------------------

    def set_state(self, state: str) -> None:
        with self._lock:
            if state == self._state:
                return
            self._state = state
            self._frame_index = 0

    def advance_frame(self) -> bool:
        """Advance animation frame.  Returns True if a redraw is needed."""
        with self._lock:
            state = self._state
        if state == "idle":
            # Still need to redraw once after transition to idle
            with self._lock:
                needs = self._frame_index == 0
                if needs:
                    self._frame_index = -1  # sentinel: drawn idle once
                return needs
        with self._lock:
            self._frame_index += 1
        return True


def _compute_bar_heights(state: str, frame_index: int) -> list[float]:
    if state == "idle":
        ratios = [0.3, 0.5, 0.7, 0.5, 0.3]
        return [BAR_MIN_HEIGHT + r * (BAR_MAX_HEIGHT - BAR_MIN_HEIGHT) for r in ratios]

    if state == "recording":
        heights: list[float] = []
        for i in range(BAR_COUNT):
            phase = frame_index * 0.45 + i * 0.7
            ratio = 0.35 + 0.65 * abs(math.sin(phase))
            heights.append(BAR_MIN_HEIGHT + ratio * (BAR_MAX_HEIGHT - BAR_MIN_HEIGHT))
        return heights

    # transcribing
    heights = []
    for i in range(BAR_COUNT):
        phase = frame_index * 0.5 - i * 0.85
        ratio = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(phase))
        heights.append(BAR_MIN_HEIGHT + ratio * (BAR_MAX_HEIGHT - BAR_MIN_HEIGHT))
    return heights


# ---------------------------------------------------------------------------
# Timer delegate
# ---------------------------------------------------------------------------

class _TimerDelegate(AppKit.NSObject):

    def initWithView_(self, view: _PillView):  # noqa: N802
        self = objc.super(_TimerDelegate, self).init()
        if self is None:
            return None
        self._view = view
        return self

    def onTimer_(self, timer) -> None:  # noqa: N802
        if self._view.advance_frame():
            self._view.setNeedsDisplay_(True)


# ---------------------------------------------------------------------------
# stdin reader (background thread)
# ---------------------------------------------------------------------------

def _stdin_reader(view: _PillView) -> None:
    try:
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd == "quit":
                AppKit.NSApp.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "terminate:", None, False,
                )
                return
            if cmd in STATE_COLORS:
                view.set_state(cmd)
    except Exception:
        pass
    AppKit.NSApp.performSelectorOnMainThread_withObject_waitUntilDone_(
        "terminate:", None, False,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    # Position: bottom-centre of main display
    display_rect = CGDisplayBounds(CGMainDisplayID())
    screen_w = display_rect.size.width
    screen_h = display_rect.size.height
    x = (screen_w - PILL_WIDTH) / 2.0
    y = BOTTOM_MARGIN  # Cocoa y=0 is bottom

    window_rect = AppKit.NSMakeRect(x, y, PILL_WIDTH, PILL_HEIGHT)

    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        window_rect,
        AppKit.NSWindowStyleMaskBorderless,
        AppKit.NSBackingStoreBuffered,
        False,
    )
    window.setLevel_(AppKit.NSFloatingWindowLevel)
    window.setOpaque_(False)
    window.setBackgroundColor_(AppKit.NSColor.clearColor())
    window.setIgnoresMouseEvents_(True)
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
    )

    pill_view = _PillView.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, 0, PILL_WIDTH, PILL_HEIGHT),
    )
    window.setContentView_(pill_view)
    window.orderFrontRegardless()

    # Animation timer
    timer_delegate = _TimerDelegate.alloc().initWithView_(pill_view)
    AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        ANIMATION_INTERVAL, timer_delegate, b"onTimer:", None, True,
    )

    # stdin reader
    reader = threading.Thread(target=_stdin_reader, args=(pill_view,), daemon=True)
    reader.start()

    app.run()


if __name__ == "__main__":
    main()
