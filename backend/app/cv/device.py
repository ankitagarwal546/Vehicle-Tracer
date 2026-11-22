"""Accelerator selection with a guaranteed CPU fallback."""
from __future__ import annotations

from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=1)
def active_device() -> str:
    requested = settings.device.lower()
    try:
        import torch
    except ImportError:
        return "cpu"
    available = {
        "cuda": torch.cuda.is_available(),
        "mps": torch.backends.mps.is_available(),
        "cpu": True,
    }
    if requested != "auto":
        return requested if available.get(requested) else "cpu"
    return next(name for name in ("cuda", "mps", "cpu") if available[name])
