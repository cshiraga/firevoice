#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$SCRIPT_DIR/.voice-input"
PID_FILE="$RUNTIME_DIR/voice-input.pid"
LOG_FILE="$RUNTIME_DIR/voice-input.log"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
APP_FILE="$SCRIPT_DIR/main.py"
VOICE_TRIGGER_KEY="${VOICE_TRIGGER_KEY:-fn}"

usage() {
  cat <<EOF
Usage: ./voice-input.sh {start|stop|restart|status|logs}
   or: ./{start|stop|restart|status|logs}

Environment overrides:
  VOICE_TRIGGER_KEY   Trigger key to use (default: fn)
  PYTHON_BIN          Python executable (default: ./.venv/bin/python)
  VOICE_REPLACEMENTS_FILE
                     JSON file with spoken-text replacements
EOF
}

ensure_runtime_dir() {
  mkdir -p "$RUNTIME_DIR"
}

read_pid() {
  if [[ -f "$PID_FILE" ]]; then
    tr -d '[:space:]' <"$PID_FILE"
  fi
}

is_running() {
  local pid
  pid="$(read_pid)"
  [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null
}

cleanup_stale_pid() {
  if [[ -f "$PID_FILE" ]] && ! is_running; then
    rm -f "$PID_FILE"
  fi
}

restore_mute() {
  if [[ "$(uname)" == "Darwin" ]]; then
    local muted
    muted="$(osascript -e 'output muted of (get volume settings)' 2>/dev/null || true)"
    if [[ "$muted" == "true" ]]; then
      osascript -e 'set volume without output muted' 2>/dev/null || true
      echo "Restored system audio (unmuted)."
    fi
  fi
}

start_app() {
  ensure_runtime_dir

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python executable not found: $PYTHON_BIN" >&2
    exit 1
  fi

  if [[ ! -f "$APP_FILE" ]]; then
    echo "Application file not found: $APP_FILE" >&2
    exit 1
  fi

  cleanup_stale_pid

  if is_running; then
    echo "voice-input is already running (PID $(read_pid))."
    exit 0
  fi

  : >"$LOG_FILE"
  nohup env VOICE_TRIGGER_KEY="$VOICE_TRIGGER_KEY" "$PYTHON_BIN" "$APP_FILE" >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" >"$PID_FILE"
  sleep 1

  if kill -0 "$pid" 2>/dev/null; then
    echo "Started voice-input in background."
    echo "PID: $pid"
    echo "Log: $LOG_FILE"
    exit 0
  fi

  echo "voice-input failed to stay running. Check logs:" >&2
  tail -n 20 "$LOG_FILE" >&2 || true
  rm -f "$PID_FILE"
  exit 1
}

stop_app_inner() {
  cleanup_stale_pid

  if ! is_running; then
    echo "voice-input is not running."
    return 0
  fi

  local pid
  pid="$(read_pid)"
  kill "$pid"

  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      rm -f "$LOG_FILE"
      echo "Stopped voice-input (PID $pid) and cleaned up logs."
      restore_mute
      return 0
    fi
    sleep 0.25
  done

  echo "Process $pid did not stop in time, force killing..." >&2
  kill -9 "$pid" 2>/dev/null || true
  sleep 0.5

  if kill -0 "$pid" 2>/dev/null; then
    echo "Failed to kill process $pid." >&2
    return 1
  fi

  rm -f "$PID_FILE"
  rm -f "$LOG_FILE"
  echo "Force killed voice-input (PID $pid)."
  restore_mute
  return 0
}

stop_app() {
  if stop_app_inner; then
    exit 0
  fi
  exit 1
}

status_app() {
  cleanup_stale_pid

  if is_running; then
    echo "voice-input is running (PID $(read_pid))."
    echo "Log: $LOG_FILE"
  else
    echo "voice-input is not running."
  fi
}

logs_app() {
  ensure_runtime_dir
  if [[ -f "$LOG_FILE" ]]; then
    tail -n 50 "$LOG_FILE"
  else
    echo "No log file yet: $LOG_FILE"
  fi
}

case "${1:-}" in
  start)
    start_app
    ;;
  stop)
    stop_app
    ;;
  restart)
    stop_app_inner || true
    start_app
    ;;
  status)
    status_app
    ;;
  logs)
    logs_app
    ;;
  *)
    usage
    exit 1
    ;;
esac
