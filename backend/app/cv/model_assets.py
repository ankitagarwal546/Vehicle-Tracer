"""Report which model weights are installed without loading or downloading them.

The app never downloads weights at startup. ``scripts/download_models.py`` installs them once.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.config import settings
from app.cv.device import active_device

INSTALL_COMMAND = ".venv/bin/python scripts/download_models.py"
CLIP_REPOSITORIES = {"laion2b_s34b_b79k": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"}
CLIP_FILES = ("open_clip_model.safetensors", "open_clip_pytorch_model.bin")
EASYOCR_FILES = ("craft_mlt_25k.pth", "english_g2.pth")


class ModelsNotInstalled(RuntimeError):
    """Raised instead of silently downloading weights or substituting fake output."""


def yolo_weights_name() -> str:
    if settings.yolo_model != "auto":
        return settings.yolo_model
    return "yolov8s.pt" if active_device() != "cpu" else "yolov8n.pt"


def _has_files(directory: Path) -> bool:
    return directory.is_dir() and any(directory.iterdir())


def clip_weights_path() -> str | None:
    repository = CLIP_REPOSITORIES.get(settings.clip_pretrained)
    if repository is None:
        return None
    from huggingface_hub import try_to_load_from_cache

    for filename in CLIP_FILES:
        found = try_to_load_from_cache(repository, filename)
        if isinstance(found, str):
            return found
    return None


def asset_status() -> dict:
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    easyocr_dir = Path(os.environ.get("EASYOCR_MODULE_PATH", Path.home() / ".EasyOCR")) / "model"
    yolo = settings.model_dir / yolo_weights_name()
    alpr = _has_files(cache / "open-image-models" / settings.alpr_detector_model) \
        and _has_files(cache / "fast-plate-ocr" / settings.alpr_ocr_model)
    easyocr = all((easyocr_dir / name).exists() for name in EASYOCR_FILES)
    clip = clip_weights_path() is not None
    missing = []
    if not yolo.exists():
        missing.append(f"vehicle detector ({yolo.name})")
    if not alpr and not easyocr:
        missing.append("plate OCR")
    return {
        "vehicle_detector": {"installed": yolo.exists(), "required": True, "name": yolo.name},
        "plate_ocr": {"installed": alpr, "required": True, "name": settings.alpr_ocr_model},
        "plate_ocr_fallback": {"installed": easyocr, "required": False, "name": "EasyOCR"},
        "attributes_reid": {"installed": clip, "required": False, "name": settings.clip_model},
        "ready": not missing,
        "missing": missing,
        "install_command": INSTALL_COMMAND,
    }


def require_analysis_models() -> None:
    if settings.allow_model_download:
        return
    status = asset_status()
    if not status["ready"]:
        raise ModelsNotInstalled(
            f"Missing {', '.join(status['missing'])}. From the backend folder, run: {INSTALL_COMMAND}"
        )
