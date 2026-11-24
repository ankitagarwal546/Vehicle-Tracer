"""Central runtime configuration. Every value can be overridden by an environment variable."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PIPELINE_VERSION = "2.2.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BACKEND_DIR / 'storage' / 'vehicle_tracer.db'}"
    upload_dir: Path = BACKEND_DIR / "storage" / "uploads"
    artifact_dir: Path = BACKEND_DIR / "storage" / "artifacts"
    model_dir: Path = BACKEND_DIR / "storage" / "models"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    device: str = "auto"  # auto | cpu | mps | cuda
    sample_fps: float = 6.0
    max_frames_per_clip: int = 720
    min_sharpness: float = 12.0
    min_brightness: float = 12.0
    max_brightness: float = 248.0
    min_contrast: float = 6.0

    yolo_model: str = "auto"  # auto: yolov8s on GPU/MPS, yolov8n on CPU
    yolo_conf: float = 0.25
    yolo_imgsz: int = 0  # 0: 960 on GPU/MPS, 640 on CPU
    min_track_frames: int = 3

    alpr_detector_model: str = "yolo-v9-s-608-license-plate-end2end"
    alpr_ocr_model: str = "cct-s-v2-global-model"
    plate_detector_conf: float = 0.3

    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"

    tau_char: float = 0.55
    single_frame_min_conf: float = 0.78
    registry_size: int = 5000
    allow_model_download: bool = False
    max_plausible_speed_kmh: float = 140.0
    analysis_workers: int = 0  # 0: half the CPU cores, capped at 4
    max_upload_mb: int = 1024

    # Sign-in. Leaving AUTH_PASSWORD empty disables it, which is only safe on a private machine.
    auth_username: str = "admin"
    auth_password: str = ""
    session_secret: str = ""
    session_hours: float = 12.0
    require_auth: bool = False  # refuse to start without AUTH_PASSWORD (set in the deploy image)
    cookie_secure: bool = False  # true behind HTTPS
    cookie_samesite: str = "lax"  # "none" lets the session work inside an embedding iframe (needs HTTPS)

    # Serve the built web app from the API server (single-container deploys).
    frontend_dist: Path | None = None


settings = Settings()
for directory in (settings.upload_dir, settings.artifact_dir, settings.model_dir):
    directory.mkdir(parents=True, exist_ok=True)
