"""Plate localisation, forensic enhancement and OCR with engine fallback.

Enhanced crops are decision aids for OCR. The raw crop is always preserved beside them.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings
from app.cv.device import active_device
from app.cv.plate_fusion import PlateRead
from app.cv.video_processor import sharpness_score

logger = logging.getLogger(__name__)

MIN_DETECT_SIDE = 640
MAX_DETECT_SCALE = 4.0
MAX_DESKEW_DEGREES = 20.0
_ALNUM = re.compile(r"[^A-Z0-9]")


@dataclass
class OcrOutput:
    text: str
    confidences: list[float]

    @property
    def score(self) -> float:
        return float(np.mean(self.confidences)) if self.confidences else 0.0


@dataclass
class PlateObservation:
    read: PlateRead
    raw_crop: np.ndarray
    enhanced_crop: np.ndarray
    bbox_in_crop: tuple[int, int, int, int]
    chosen: str


def deskew_plate(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.2 * image.shape[0] * image.shape[1]:
        return image
    (center, (width, height), angle) = cv2.minAreaRect(largest)
    if width < height:
        angle += 90
    angle = ((angle + 90) % 180) - 90
    if abs(angle) < 0.5 or abs(angle) > MAX_DESKEW_DEGREES:
        return image
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(image, matrix, (image.shape[1], image.shape[0]),
                          flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def enhance_plate(image: np.ndarray) -> np.ndarray:
    """Deskew, CLAHE, bilateral denoise, unsharp mask and 2x bicubic upscale."""
    deskewed = deskew_plate(image)
    gray = cv2.cvtColor(deskewed, cv2.COLOR_BGR2GRAY)
    contrast = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4)).apply(gray)
    denoised = cv2.bilateralFilter(contrast, 5, 40, 40)
    blurred = cv2.GaussianBlur(denoised, (0, 0), 1.2)
    sharpened = cv2.addWeighted(denoised, 1.6, blurred, -0.6, 0)
    upscaled = cv2.resize(sharpened, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(upscaled, cv2.COLOR_GRAY2BGR)


class FastAlprEngine:
    name = "fast-alpr"

    def __init__(self) -> None:
        from fast_alpr import ALPR

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if active_device() == "cuda" \
            else ["CPUExecutionProvider"]
        self.alpr = ALPR(
            detector_model=settings.alpr_detector_model,
            detector_conf_thresh=settings.plate_detector_conf,
            detector_providers=providers,
            ocr_model=settings.alpr_ocr_model,
            ocr_device="cuda" if active_device() == "cuda" else "cpu",
            ocr_providers=providers,
        )

    def locate(self, image: np.ndarray) -> tuple[int, int, int, int] | None:
        detections = self.alpr.detector.predict(image)
        if not detections:
            return None
        best = max(detections, key=lambda d: d.confidence).bounding_box
        return int(best.x1), int(best.y1), int(best.x2), int(best.y2)

    def read(self, plate: np.ndarray) -> OcrOutput | None:
        result = self.alpr.ocr.predict(plate)
        if result is None or not result.text:
            return None
        raw = result.text.upper()
        confidence = result.confidence
        values = list(confidence) if isinstance(confidence, (list, tuple, np.ndarray)) else [float(confidence)] * len(raw)
        if len(values) != len(raw):
            values = [float(np.mean(values))] * len(raw)
        pairs = [(c, float(v)) for c, v in zip(raw, values) if c.isascii() and c.isalnum()]
        return OcrOutput("".join(c for c, _ in pairs), [v for _, v in pairs]) if pairs else None


class EasyOcrEngine:
    """Offline fallback. It reports one confidence per word, applied to each character."""

    name = "easyocr"

    def __init__(self) -> None:
        import easyocr

        self.reader = easyocr.Reader(["en"], gpu=active_device() == "cuda", verbose=False)

    def locate(self, image: np.ndarray) -> tuple[int, int, int, int] | None:
        height, width = image.shape[:2]
        top = int(height * 0.35)
        best: tuple[float, tuple[int, int, int, int]] | None = None
        for box, text, confidence in self.reader.readtext(image[top:], allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
            if len(_ALNUM.sub("", text.upper())) < 3:
                continue
            xs, ys = [p[0] for p in box], [p[1] + top for p in box]
            candidate = (float(confidence), (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return None
        x1, y1, x2, y2 = best[1]
        return max(x1, 0), max(y1, 0), min(x2, width), min(y2, height)

    def read(self, plate: np.ndarray) -> OcrOutput | None:
        results = self.reader.readtext(plate, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        if not results:
            return None
        ordered = sorted(results, key=lambda r: (min(p[1] for p in r[0]) // max(plate.shape[0] / 2, 1),
                                                 min(p[0] for p in r[0])))
        text, values = "", []
        for _, word, confidence in ordered:
            clean = _ALNUM.sub("", word.upper())
            text += clean
            values += [float(confidence)] * len(clean)
        return OcrOutput(text, values) if text else None


class PlateReader:
    """Loads the primary engine and falls back automatically."""

    def __init__(self) -> None:
        self.engine = None
        self.errors: dict[str, str] = {}
        for factory in (FastAlprEngine, EasyOcrEngine):
            try:
                self.engine = factory()
                break
            except Exception as error:  # Model download and native runtime failures vary by platform.
                self.errors[factory.name] = f"{type(error).__name__}: {error}"
                logger.warning("OCR engine %s unavailable: %s", factory.name, error)

    @property
    def name(self) -> str:
        return self.engine.name if self.engine else "unavailable"

    def read_vehicle(self, crop: np.ndarray, frame_idx: int, timestamp: float) -> PlateObservation | None:
        if self.engine is None:
            return None
        height, width = crop.shape[:2]
        scale = min(MAX_DETECT_SCALE, max(MIN_DETECT_SIDE / max(height, width), 1.0))
        scaled = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale > 1 else crop
        located = self.engine.locate(scaled)
        if located is None:
            return None
        x1, y1, x2, y2 = (int(round(value / scale)) for value in located)
        x1, y1, x2, y2 = max(x1, 0), max(y1, 0), min(x2, width), min(y2, height)
        if x2 - x1 < 8 or y2 - y1 < 4:
            return None
        raw = crop[y1:y2, x1:x2].copy()
        enhanced = enhance_plate(raw)
        outputs = {"raw": self.engine.read(raw), "enhanced": self.engine.read(enhanced)}
        available = {key: value for key, value in outputs.items() if value is not None}
        if not available:
            return None
        chosen = max(available, key=lambda key: available[key].score)
        output = available[chosen]
        read = PlateRead(
            frame_idx=frame_idx, timestamp_sec=timestamp, raw_text=output.text,
            char_confidences=output.confidences, sharpness_score=sharpness_score(raw),
            bbox_area=float((x2 - x1) * (y2 - y1)), ocr_engine_score=output.score,
            source=f"{self.engine.name}:{chosen}",
        )
        return PlateObservation(read, raw, enhanced, (x1, y1, x2, y2), chosen)
