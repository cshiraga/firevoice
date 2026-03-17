"""Allow running FireVoice via ``python -m firevoice``."""

from firevoice.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
