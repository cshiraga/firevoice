"""FireVoice CLI – process management for the voice-to-text engine.

Provides subcommands mirroring the original shell scripts:
  firevoice start    – launch in background
  firevoice stop     – stop the background process
  firevoice restart  – stop + start
  firevoice status   – check if running
  firevoice logs     – show recent log output
  firevoice run      – run in foreground (for debugging)
"""

from __future__ import annotations

import argparse
import collections
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _runtime_dir() -> Path:
    """Return the runtime directory (~/.firevoice)."""
    return Path.home() / ".firevoice"


def _pid_file() -> Path:
    return _runtime_dir() / "firevoice.pid"


def _log_file() -> Path:
    return _runtime_dir() / "firevoice.log"


def _ready_file() -> Path:
    return _runtime_dir() / "firevoice.ready"


def _ensure_runtime_dir() -> None:
    _runtime_dir().mkdir(parents=True, exist_ok=True)


def _read_pid() -> int | None:
    pid_file = _pid_file()
    if not pid_file.exists():
        return None
    text = pid_file.read_text().strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _is_firevoice_process(pid: int) -> bool:
    """Check whether *pid* belongs to a FireVoice process."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
        return "firevoice" in result.stdout.lower()
    except OSError:
        return False


def _is_running() -> bool:
    pid = _read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return _is_firevoice_process(pid)


def _cleanup_stale_pid() -> None:
    if _pid_file().exists() and not _is_running():
        _pid_file().unlink(missing_ok=True)
        _ready_file().unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------

SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _spinner(message: str, duration: float) -> None:
    """Display a spinner for *duration* seconds, then clear the line."""
    end_time = time.monotonic() + duration
    i = 0
    while time.monotonic() < end_time:
        ch = SPINNER_CHARS[i % len(SPINNER_CHARS)]
        print(f"\r  {ch}  {message}", end="", flush=True)
        i += 1
        time.sleep(0.08)
    print("\r\033[K", end="", flush=True)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _cmd_start() -> int:
    print("  🔥  Igniting FireVoice...")
    _ensure_runtime_dir()

    # Force unmute on start in case a previous instance was killed
    # while the system was muted.
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", "set volume without output muted"],
            check=False,
            capture_output=True,
        )

    _cleanup_stale_pid()

    if _is_running():
        print(f"  ℹ️  Already running (PID {_read_pid()}).")
        return 0

    # Clear the log file
    log_file = _log_file()
    log_file.write_text("")

    # Launch the app as a background process
    env = os.environ.copy()
    # firevoice.app:run_app is the entry point
    log_fh = open(log_file, "a")  # noqa: SIM115
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "firevoice.app"],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    finally:
        # Close the FD in the parent – the child process inherits its own copy.
        log_fh.close()

    pid = proc.pid
    _pid_file().write_text(str(pid))

    # Remove stale ready file from previous runs
    _ready_file().unlink(missing_ok=True)

    # Wait for the app to fully initialize (model loading etc.)
    timeout = 120
    end_time = time.monotonic() + timeout
    i = 0
    while time.monotonic() < end_time:
        # Check if the process is still alive
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            print("\r\033[K", end="", flush=True)
            print("  ❌  Process exited during startup. Check logs:", file=sys.stderr)
            if log_file.exists():
                lines = log_file.read_text().splitlines()
                for line in lines[-20:]:
                    print(f"    {line}", file=sys.stderr)
            _pid_file().unlink(missing_ok=True)
            return 1

        # Check if the ready signal has been written
        if _ready_file().exists():
            print("\r\033[K", end="", flush=True)
            break

        ch = SPINNER_CHARS[i % len(SPINNER_CHARS)]
        print(f"\r  {ch}  Loading Whisper model...", end="", flush=True)
        i += 1
        time.sleep(0.08)
    else:
        print("\r\033[K", end="", flush=True)
        print("  ❌  Timed out waiting for model to load.", file=sys.stderr)
        # Kill the orphaned background process
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        else:
            # Wait briefly for graceful shutdown
            time.sleep(2)
            try:
                os.kill(pid, 0)
                # Still alive – force kill
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        # Clean up PID / ready files
        _pid_file().unlink(missing_ok=True)
        _ready_file().unlink(missing_ok=True)
        # Show recent log output for diagnosis
        if log_file.exists():
            lines = log_file.read_text().splitlines()
            if lines:
                print("  📄  Recent logs:", file=sys.stderr)
                for line in lines[-10:]:
                    print(f"    {line}", file=sys.stderr)
        return 1

    trigger_key = os.environ.get("VOICE_TRIGGER_KEY", "fn")
    print("")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("")
    print("   🔥  F I R E V O I C E")
    print("       Voice-to-Text Engine")
    print("")
    print(f"   ✅  Running  (PID: {pid})")
    print(f"   ⌨   Trigger: {trigger_key}")
    print("")
    print("   📖  How to use")
    print(f"   ├─  Hold [{trigger_key}] key to start recording")
    print("   ├─  Release to transcribe")
    print("   └─  Text is pasted at cursor position")
    print("")
    print("   💡  firevoice logs  → view logs")
    print("       firevoice stop  → stop service")
    print("")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("")

    return 0


def _cmd_stop_inner() -> bool:
    """Stop the background process.  Returns True on success."""
    print("  🛑  Extinguishing FireVoice...")
    _cleanup_stale_pid()

    if not _is_running():
        print("  ℹ️  FireVoice is not running.")
        return True

    pid = _read_pid()
    if pid is None:
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        _pid_file().unlink(missing_ok=True)
        _ready_file().unlink(missing_ok=True)
        print(f"  ✅  FireVoice stopped (PID: {pid})")
        return True

    # Wait up to 6 seconds for the process to exit, showing a spinner
    end_time = time.monotonic() + 6.0
    i = 0
    while time.monotonic() < end_time:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            print("\r\033[K", end="", flush=True)
            _pid_file().unlink(missing_ok=True)
            _log_file().unlink(missing_ok=True)
            _ready_file().unlink(missing_ok=True)
            print(f"  ✅  FireVoice stopped (PID: {pid})")
            return True
        ch = SPINNER_CHARS[i % len(SPINNER_CHARS)]
        print(f"\r  {ch}  Waiting for process to exit...", end="", flush=True)
        i += 1
        time.sleep(0.08)
    print("\r\033[K", end="", flush=True)

    # Force kill
    print(f"  ⚠️  Process {pid} did not stop in time, force killing...", file=sys.stderr)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    time.sleep(0.5)

    try:
        os.kill(pid, 0)
        print(f"  ❌  Failed to kill process {pid}.", file=sys.stderr)
        return False
    except (ProcessLookupError, PermissionError):
        _pid_file().unlink(missing_ok=True)
        _log_file().unlink(missing_ok=True)
        _ready_file().unlink(missing_ok=True)
        print(f"  ✅  FireVoice force killed (PID: {pid})")
        return True


def _cmd_stop() -> int:
    return 0 if _cmd_stop_inner() else 1


def _cmd_restart() -> int:
    _cmd_stop_inner()
    return _cmd_start()


def _cmd_status() -> int:
    _cleanup_stale_pid()
    if _is_running():
        print(f"  🔥  FireVoice is running (PID: {_read_pid()})")
        print(f"  📄  Log: {_log_file()}")
    else:
        print("  ⚪  FireVoice is not running.")
    return 0


def _cmd_logs() -> int:
    _ensure_runtime_dir()
    log_file = _log_file()
    if log_file.exists():
        # Read only the last 50 lines efficiently using deque
        with open(log_file) as f:
            tail = collections.deque(f, maxlen=50)
        for line in tail:
            print(line, end="")
    else:
        print("  ℹ️  No log file yet.")
    return 0


def _cmd_run() -> int:
    """Run the voice input application in the foreground."""
    from firevoice.app import run_app

    return run_app()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="firevoice",
        description="🔥 FireVoice – A blazing-fast, fully local voice-to-text tool",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start the background service")
    sub.add_parser("stop", help="Stop the background service")
    sub.add_parser("restart", help="Restart the background service")
    sub.add_parser("status", help="Check if the service is running")
    sub.add_parser("logs", help="Show recent log output")
    sub.add_parser("run", help="Run in foreground (for debugging)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "start": _cmd_start,
        "stop": _cmd_stop,
        "restart": _cmd_restart,
        "status": _cmd_status,
        "logs": _cmd_logs,
        "run": _cmd_run,
    }

    return commands[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
