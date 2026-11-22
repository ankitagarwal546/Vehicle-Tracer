"""Central runtime configuration. Every value can be overridden by an environment variable."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PIPELINE_VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BACKEND_DIR / 'storage' / 'vehicle_tracer.db'}"
    upload_dir: Path = BACKEND_DIR / "storage" / "uploads"
    artifact_dir: Path = BACKEND_DIR / "storage" / "artifacts"
    model_dir: Path = BACKEND_DIR / "storage" / "models"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    device: str = "auto"  # auto | cpu | mps | cuda
    sample_fps: float = 5.0
    max_frames_per_clip: int = 240
    min_sharpness: float = 12.0
    min_brightness: float = 12.0
    max_brightness: float = 248.0
    min_contrast: float = 6.0

    yolo_model: str = "yolov8n.pt"
    yolo_conf: float = 0.2
    yolo_imgsz: int = 640
    min_track_frames: int = 2

    alpr_detector_model: str = "yolo-v9-t-384-license-plate-end2end"
    alpr_ocr_model: str = "cct-xs-v2-global-model"
    plate_detector_conf: float = 0.25

    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"

    tau_char: float = 0.55
    single_frame_min_conf: float = 0.78
    reid_link_threshold: float = 0.62
    max_upload_mb: int = 1024


settings = Settings()
for directory in (settings.upload_dir, settings.artifact_dir, settings.model_dir):
    directory.mkdir(parents=True, exist_ok=True)
