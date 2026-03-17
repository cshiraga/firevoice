"""FireVoice – A blazing-fast, fully local voice-to-text tool for macOS."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("firevoice")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
