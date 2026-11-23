"""Plate localisation, forensic enhancement and OCR with engine fallback.

Enhancement only uses classical, content-preserving filters and multi-frame averaging.
Generative super-resolution is deliberately excluded because it can invent characters.
The raw crop is always preserved beside every enhanced view.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings
from app.cv.device import active_device
from app.cv.plate_fusion import PlateRead, align

logger = logging.getLogger(__name__)

MIN_DETECT_SIDE = 640
MAX_DETECT_SCALE = 3.0
MAX_DESKEW_DEGREES = 20.0
MIN_PLATE_WIDTH = 28
MIN_PLATE_HEIGHT = 11
MIN_PLATE_ASPECT = 1.2
MIN_PLATE_CENTER_Y = 0.30
MIN_PLATE_QUALITY = 0.008
QUALITY_HEIGHT = 48
TARGET_ENHANCED_HEIGHT = 96
MAX_ENHANCE_SCALE = 4
MAX_STACK_FRAMES = 7
BAND_WIDTH = 0.09
MIN_STACK_FRAMES = 3
MIN_STACK_CORRELATION = 0.75
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
    quality: float


def trim_country_band(image: np.ndarray) -> np.ndarray:
    """Remove a saturated blue country band so OCR does not read it as an extra character."""
    width = image.shape[1]
    band = max(int(width * BAND_WIDTH), 1)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    left = hsv[:, :band]
    is_blue = (left[:, :, 0] >= 95) & (left[:, :, 0] <= 130) & (left[:, :, 1] >= 70)
    body = hsv[:, band:]
    body_blue = (body[:, :, 0] >= 95) & (body[:, :, 0] <= 130) & (body[:, :, 1] >= 70)
    if is_blue.mean() >= 0.45 and body_blue.mean() < 0.25:
        return image[:, band:]
    return image


def plate_quality(image: np.ndarray) -> float:
    """Contrast-normalised focus measure at a fixed scale, comparable across plate sizes."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    scale = QUALITY_HEIGHT / max(gray.shape[0], 1)
    resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC).astype(np.float32)
    variance = float(resized.var())
    if variance < 1.0:
        return 0.0
    return float(cv2.Laplacian(resized, cv2.CV_32F).var()) / variance


def plate_belongs_to_target(
    plate: tuple[int, int, int, int],
    target: tuple[int, int, int, int],
    occluders: list[tuple[int, int, int, int]],
) -> bool:
    """A plate counts only if it is on the target's lower body and not on a nearer vehicle."""
    center_x, center_y = (plate[0] + plate[2]) / 2, (plate[1] + plate[3]) / 2
    x1, y1, x2, y2 = target
    if not (x1 <= center_x <= x2 and y1 + (y2 - y1) * MIN_PLATE_CENTER_Y <= center_y <= y2):
        return False
    return not any(a <= center_x <= c and b <= center_y <= d for a, b, c, d in occluders)


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
    """Deskew, upscale, denoise, apply mild CLAHE, then unsharp mask.

    Upscaling comes first so denoising and sharpening do not clip small strokes.
    """
    deskewed = deskew_plate(image)
    gray = cv2.cvtColor(deskewed, cv2.COLOR_BGR2GRAY)
    factor = int(np.clip(np.ceil(TARGET_ENHANCED_HEIGHT / max(gray.shape[0], 1)), 2, MAX_ENHANCE_SCALE))
    upscaled = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    denoised = cv2.bilateralFilter(upscaled, 5, 24, 5)
    contrast = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(3, 6)).apply(denoised)
    blurred = cv2.GaussianBlur(contrast, (0, 0), 1.0 + factor * 0.35)
    sharpened = cv2.addWeighted(contrast, 1.45, blurred, -0.45, 0)
    return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)


def stack_plates(crops: list[np.ndarray]) -> np.ndarray | None:
    """Register several plate crops to the sharpest one and average them to suppress noise.

    Averaging aligned real pixels cannot create a character that no frame contains.
    """
    usable = sorted((c for c in crops if c.shape[0] >= MIN_PLATE_HEIGHT), key=plate_quality, reverse=True)
    usable = usable[:MAX_STACK_FRAMES]
    if len(usable) < MIN_STACK_FRAMES:
        return None
    reference = usable[0]
    height = max(int(reference.shape[0] * 2), 48)
    width = int(reference.shape[1] * height / reference.shape[0])
    base = cv2.resize(reference, (width, height), interpolation=cv2.INTER_CUBIC)
    base_gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)
    aligned = [base.astype(np.float32)]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
    for crop in usable[1:]:
        moving = cv2.resize(crop, (width, height), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(moving, cv2.COLOR_BGR2GRAY).astype(np.float32)
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            correlation, warp = cv2.findTransformECC(base_gray, gray, warp, cv2.MOTION_AFFINE, criteria, None, 5)
        except cv2.error:
            continue
        if correlation < MIN_STACK_CORRELATION:
            continue
        warped = cv2.warpAffine(moving, warp, (width, height), flags=cv2.INTER_CUBIC + cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_REPLICATE)
        aligned.append(warped.astype(np.float32))
    if len(aligned) < MIN_STACK_FRAMES:
        return None
    return np.clip(np.mean(aligned, axis=0), 0, 255).astype(np.uint8)


def apply_variant_agreement(primary: OcrOutput, others: list[OcrOutput]) -> OcrOutput:
    """Lower confidence for characters that change when the same plate is re-read after filtering.

    OCR on an illegible plate often reports high confidence, but its answer is unstable.
    """
    if not others:
        return primary
    votes = [0] * len(primary.text)
    for other in others:
        for left, right in align(primary.text, other.text):
            if primary.text[left] == other.text[right]:
                votes[left] += 1
    adjusted = [conf * (0.5 + 0.5 * vote / len(others)) for conf, vote in zip(primary.confidences, votes)]
    return OcrOutput(primary.text, adjusted)


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

    def locate(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Return plate boxes, most confident first."""
        ranked = sorted(self.alpr.detector.predict(image), key=lambda d: -d.confidence)
        return [(int(d.bounding_box.x1), int(d.bounding_box.y1), int(d.bounding_box.x2), int(d.bounding_box.y2))
                for d in ranked]

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

    def locate(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        height, width = image.shape[:2]
        top = int(height * 0.35)
        found: list[tuple[float, tuple[int, int, int, int]]] = []
        for box, text, confidence in self.reader.readtext(image[top:], allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
            if len(_ALNUM.sub("", text.upper())) < 3:
                continue
            xs, ys = [p[0] for p in box], [p[1] + top for p in box]
            box = (max(int(min(xs)), 0), max(int(min(ys)), 0), min(int(max(xs)), width), min(int(max(ys)), height))
            found.append((float(confidence), box))
        return [box for _, box in sorted(found, key=lambda item: -item[0])]

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

    def read_crop(self, plate: np.ndarray) -> tuple[OcrOutput | None, str, np.ndarray]:
        """Read raw and enhanced views, then discount characters that are unstable between them."""
        enhanced = enhance_plate(plate)
        doubled = cv2.resize(plate, None, fx=2, fy=2, interpolation=cv2.INTER_LANCZOS4)
        outputs = {"raw": self.engine.read(plate), "enhanced": self.engine.read(enhanced),
                   "upscaled": self.engine.read(doubled)}
        available = {key: value for key, value in outputs.items() if value is not None}
        if not available:
            return None, "", enhanced
        chosen = max(available, key=lambda key: available[key].score)
        others = [value for key, value in available.items() if key != chosen]
        return apply_variant_agreement(available[chosen], others), chosen, enhanced

    def read_vehicle(
        self,
        crop: np.ndarray,
        frame_idx: int,
        timestamp: float,
        target: tuple[int, int, int, int] | None = None,
        occluders: list[tuple[int, int, int, int]] | None = None,
    ) -> PlateObservation | None:
        """Read the plate that belongs to the target vehicle, ignoring plates of nearer vehicles."""
        if self.engine is None:
            return None
        height, width = crop.shape[:2]
        scale = min(MAX_DETECT_SCALE, max(MIN_DETECT_SIDE / max(height, width), 1.0))
        scaled = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale > 1 else crop
        located = None
        for candidate in self.engine.locate(scaled):
            box = tuple(int(round(value / scale)) for value in candidate)
            if plate_belongs_to_target(box, target or (0, 0, width, height), occluders or []):
                located = box
                break
        if located is None:
            return None
        x1, y1, x2, y2 = located
        x1, y1, x2, y2 = max(x1, 0), max(y1, 0), min(x2, width), min(y2, height)
        plate_width, plate_height = x2 - x1, y2 - y1
        if plate_width < MIN_PLATE_WIDTH or plate_height < MIN_PLATE_HEIGHT \
                or plate_width / max(plate_height, 1) < MIN_PLATE_ASPECT:
            return None
        raw = trim_country_band(crop[y1:y2, x1:x2].copy())
        quality = plate_quality(raw)
        if quality < MIN_PLATE_QUALITY:
            return None
        output, chosen, enhanced = self.read_crop(raw)
        if output is None:
            return None
        read = PlateRead(
            frame_idx=frame_idx, timestamp_sec=timestamp, raw_text=output.text,
            char_confidences=output.confidences, sharpness_score=quality,
            bbox_area=float(plate_width * plate_height), ocr_engine_score=output.score,
            source=f"{self.engine.name}:{chosen}",
        )
        return PlateObservation(read, raw, enhanced, (x1, y1, x2, y2), chosen, quality)

    def read_stack(self, observations: list[PlateObservation]) -> tuple[PlateRead | None, np.ndarray | None]:
        """OCR a multi-frame stack. The read is flagged derived so it cannot count as extra frames."""
        if self.engine is None:
            return None, None
        stacked = stack_plates([item.raw_crop for item in observations])
        if stacked is None:
            return None, None
        output, chosen, _ = self.read_crop(stacked)
        if output is None:
            return None, stacked
        when = float(np.mean([item.read.timestamp_sec for item in observations]))
        read = PlateRead(
            frame_idx=-1, timestamp_sec=when, raw_text=output.text, char_confidences=output.confidences,
            sharpness_score=plate_quality(stacked),
            bbox_area=float(max(item.read.bbox_area for item in observations)),
            ocr_engine_score=output.score, source=f"{self.engine.name}:stack-{chosen}", derived=True,
        )
        return read, stacked
