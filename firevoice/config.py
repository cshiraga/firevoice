"""Configuration, runtime paths, and text-replacement utilities."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def runtime_dir() -> Path:
    """Return the runtime directory (~/.firevoice)."""
    return Path.home() / ".firevoice"


def ready_file() -> Path:
    return runtime_dir() / "firevoice.ready"


def _default_replacements_path() -> Path:
    override = os.getenv("VOICE_REPLACEMENTS_FILE")
    if override:
        return Path(override).expanduser()
    return runtime_dir() / "voice-replacements.json"


def ensure_default_replacements() -> None:
    """Copy the bundled voice-replacements.json to the runtime directory
    if it does not already exist there."""
    dest = runtime_dir() / "voice-replacements.json"
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
