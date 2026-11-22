"""Download and verify every model once, so later runs work without internet access."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pipeline_orchestrator import models  # noqa: E402


def main() -> int:
    models.load()
    status = models.status()
    print(f"Device:    {status['device']}")
    print(f"Detector:  {'ready' if status['detector']['loaded'] else status['detector']['error']}")
    print(f"Plate OCR: {status['plate_ocr']['engine']}")
    print(f"OpenCLIP:  {'ready' if status['clip']['loaded'] else status['clip']['error']}")
    return 0 if status["detector"]["loaded"] and status["plate_ocr"]["loaded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
