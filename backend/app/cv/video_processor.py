"""Evidence ingest, video probing, adaptive sampling and frame quality gating."""
from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.config import settings

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SEQUENCE_FPS = 5.0
MAX_SEQUENCE_IMAGES = 2000
STATIC_DIFF = 0.6
MAX_STATIC_GAP_SEC = 2.0


@dataclass
class VideoMetadata:
    fps: float
    width: int
    height: int
    frame_count: int
    duration_sec: float
    codec: str


@dataclass
class SampledFrame:
    frame_idx: int
    timestamp_sec: float
    image: np.ndarray
    sharpness: float
    brightness: float
    contrast: float


@dataclass
class SamplingStats:
    windows: int = 0
    kept: int = 0
    rejected_blur: int = 0
    rejected_exposure: int = 0
    rejected_contrast: int = 0
    rejected_static: int = 0
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "windows": self.windows, "kept": self.kept, "rejected_blur": self.rejected_blur,
            "rejected_exposure": self.rejected_exposure, "rejected_contrast": self.rejected_contrast,
            "rejected_static": self.rejected_static,
        }


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sharpness_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _sequence_images(path: Path) -> list[Path]:
    return sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)[:MAX_SEQUENCE_IMAGES]


def extract_image_sequence(archive: Path, target: Path) -> Path:
    """Extract only image members, flattening names so no entry can escape ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        members = sorted(
            (info for info in bundle.infolist()
             if not info.is_dir() and Path(info.filename).suffix.lower() in IMAGE_EXTENSIONS),
            key=lambda info: info.filename,
        )
        if not members:
            raise ValueError("Archive contains no supported images")
        for index, info in enumerate(members[:MAX_SEQUENCE_IMAGES]):
            suffix = Path(info.filename).suffix.lower()
            (target / f"{index:06d}{suffix}").write_bytes(bundle.read(info))
    return target


def probe_video(path: Path) -> VideoMetadata:
    if path.is_dir():
        images = _sequence_images(path)
        if not images:
            raise ValueError("Image sequence is empty")
        first = cv2.imread(str(images[0]))
        if first is None:
            raise ValueError("Image sequence could not be decoded")
        return VideoMetadata(SEQUENCE_FPS, first.shape[1], first.shape[0], len(images),
                             len(images) / SEQUENCE_FPS, "image-sequence")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Unreadable video: {path.name}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        fps = fps if 0 < fps < 240 else 25.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
        codec = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00 ")
        ok, _ = capture.read()
        if not ok:
            raise ValueError(f"Video has no decodable frames: {path.name}")
    finally:
        capture.release()
    return VideoMetadata(round(fps, 3), width, height, max(frames, 0), round(max(frames, 0) / fps, 3), codec or "unknown")


def _raw_frames(path: Path, metadata: VideoMetadata) -> Iterator[tuple[int, np.ndarray]]:
    if path.is_dir():
        for index, image_path in enumerate(_sequence_images(path)):
            image = cv2.imread(str(image_path))
            if image is not None:
                yield index, image
        return
    capture = cv2.VideoCapture(str(path))
    try:
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                return
            yield index, frame
            index += 1
    finally:
        capture.release()


def sample_frames(
    path: Path,
    metadata: VideoMetadata,
    sample_fps: float | None = None,
    stats: SamplingStats | None = None,
) -> Iterator[SampledFrame]:
    """Yield the sharpest usable frame from each sampling window."""
    stats = stats if stats is not None else SamplingStats()
    target = min(max(sample_fps or settings.sample_fps, 0.5), metadata.fps)
    if metadata.duration_sec > 0:
        # Long clips are sampled more sparsely so the frame budget still covers the whole clip.
        target = min(target, settings.max_frames_per_clip / metadata.duration_sec)
    window = max(int(round(metadata.fps / target)), 1)
    best: tuple[float, int, np.ndarray] | None = None
    previous: np.ndarray | None = None
    last_kept_ts = -MAX_STATIC_GAP_SEC

    def evaluate(candidate: tuple[float, int, np.ndarray]) -> SampledFrame | None:
        nonlocal previous, last_kept_ts
        stats.windows += 1
        sharp, frame_idx, image = candidate
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        brightness, contrast = float(gray.mean()), float(gray.std())
        if not settings.min_brightness <= brightness <= settings.max_brightness:
            stats.rejected_exposure += 1
            return None
        if contrast < settings.min_contrast:
            stats.rejected_contrast += 1
            return None
        if sharp < settings.min_sharpness:
            stats.rejected_blur += 1
            return None
        timestamp = frame_idx / metadata.fps
        small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        if previous is not None and float(cv2.absdiff(small, previous).mean()) < STATIC_DIFF \
                and timestamp - last_kept_ts < MAX_STATIC_GAP_SEC:
            stats.rejected_static += 1
            return None
        previous, last_kept_ts = small, timestamp
        stats.kept += 1
        return SampledFrame(frame_idx, timestamp, image, sharp, brightness, contrast)

    for index, frame in _raw_frames(path, metadata):
        sharp = sharpness_score(cv2.resize(frame, (320, int(320 * frame.shape[0] / frame.shape[1]))))
        if best is None or sharp > best[0]:
            best = (sharp, index, frame)
        if (index + 1) % window == 0:
            result = evaluate(best)
            best = None
            if result is not None:
                yield result
    if best is not None:
        result = evaluate(best)
        if result is not None:
            yield result
