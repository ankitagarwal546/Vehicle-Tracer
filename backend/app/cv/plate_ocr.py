"""Plate localisation and per-character OCR across traceable image variants.

Enhancement only uses classical filters, interpolation and multi-frame averaging. Generative
super-resolution is deliberately excluded because it can invent characters. A character that
appears only in processed views is flagged as lacking support from source pixels.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings
from app.cv.device import active_device
from app.cv.model_assets import ModelsNotInstalled, asset_status
from app.cv.plate_fusion import PlateRead, align
from app.cv.plate_variants import VARIANTS, Rectification, build_variants

logger = logging.getLogger(__name__)

MIN_DETECT_SIDE = 640
MAX_DETECT_SCALE = 3.0
MIN_PLATE_WIDTH = 28
MIN_PLATE_HEIGHT = 11
MIN_PLATE_ASPECT = 1.2
MIN_PLATE_CENTER_Y = 0.30
MIN_PLATE_QUALITY = 0.008
QUALITY_HEIGHT = 48
MAX_ALTERNATIVES = 3
MIN_ALTERNATIVE_PROB = 0.03
MIN_RAW_SUPPORT = 0.20
UNSUPPORTED_PENALTY = 0.5
MAX_STACK_FRAMES = 7
BAND_WIDTH = 0.09
MIN_STACK_FRAMES = 3
MIN_STACK_CORRELATION = 0.75
_ALNUM = re.compile(r"[^A-Z0-9]")


@dataclass
class OcrOutput:
    text: str
    confidences: list[float]
    alternatives: list[list[tuple[str, float]]] = field(default_factory=list)

    @property
    def score(self) -> float:
        return float(np.mean(self.confidences)) if self.confidences else 0.0

    def probability(self, index: int, char: str) -> float:
        if self.text[index] == char:
            return self.confidences[index]
        if index < len(self.alternatives):
            return next((p for c, p in self.alternatives[index] if c == char), 0.0)
        return 0.0


@dataclass
class CombinedRead:
    text: str
    confidences: list[float]
    alternatives: list[list[tuple[str, float]]]
    source_supported: list[bool]
    variant_votes: list[list[dict]]


@dataclass
class PlateObservation:
    read: PlateRead
    raw_crop: np.ndarray
    variants: dict[str, np.ndarray]
    variant_outputs: dict[str, OcrOutput | None]
    bbox_in_crop: tuple[int, int, int, int]
    box_confidence: float
    quality: float
    rectification: Rectification


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


def combine_variants(outputs: dict[str, OcrOutput | None]) -> CombinedRead | None:
    """Compare one frame's variants per character, using the raw read as the coordinate frame.

    A character that the raw crop does not support is marked unsupported and its confidence is
    halved. Fusion later keeps it only if another frame's source pixels support it.
    """
    available = {name: value for name, value in outputs.items() if value is not None and value.text}
    if not available:
        return None
    raw = available.get("raw")
    base = raw or max(available.values(), key=lambda value: value.score)
    positions: dict[str, dict[int, int]] = {}
    for name, output in available.items():
        # OCR slots are positional, so equal-length reads compare directly. Others are aligned.
        positions[name] = {i: i for i in range(len(output.text))} if len(output.text) == len(base.text) else {
            left: right for left, right in align(base.text, output.text)
        }
    text: list[str] = []
    confidences: list[float] = []
    alternatives: list[list[tuple[str, float]]] = []
    supported: list[bool] = []
    votes_by_slot: list[list[dict]] = []
    for index in range(len(base.text)):
        tally: dict[str, float] = {}
        total_weight = 0.0
        slot_votes: list[dict] = []
        for name, output in available.items():
            other = positions[name].get(index)
            if other is None or other >= len(output.text):
                continue
            weight = VARIANTS[name]["weight"]
            total_weight += weight
            slot_votes.append({"variant": name, "char": output.text[other],
                               "confidence": round(output.confidences[other], 4)})
            tally[output.text[other]] = tally.get(output.text[other], 0.0) + weight * output.confidences[other]
            if other < len(output.alternatives):
                for char, probability in output.alternatives[other]:
                    tally[char] = tally.get(char, 0.0) + weight * probability
        ranked = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
        chosen, mass = ranked[0]
        confidence = mass / max(total_weight, 1e-9)
        has_source = raw is not None and (raw.text[index] == chosen or raw.probability(index, chosen) >= MIN_RAW_SUPPORT)
        if not has_source:
            confidence *= UNSUPPORTED_PENALTY
        text.append(chosen)
        confidences.append(float(min(confidence, 1.0)))
        alternatives.append([(c, round(v / max(total_weight, 1e-9), 4)) for c, v in ranked[1:MAX_ALTERNATIVES + 1]
                             if v / max(total_weight, 1e-9) >= MIN_ALTERNATIVE_PROB])
        supported.append(has_source)
        votes_by_slot.append(slot_votes)
    return CombinedRead("".join(text), confidences, alternatives, supported, votes_by_slot)


class FastAlprEngine:
    name = "fast-alpr"

    def __init__(self) -> None:
        from fast_alpr import ALPR

        if not settings.allow_model_download and not asset_status()["plate_ocr"]["installed"]:
            raise ModelsNotInstalled("FastALPR weights are not installed. Run scripts/download_models.py.")
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

    def locate(self, image: np.ndarray) -> list[tuple[tuple[int, int, int, int], float]]:
        """Return plate boxes with detector confidence, most confident first."""
        ranked = sorted(self.alpr.detector.predict(image), key=lambda d: -d.confidence)
        return [((int(d.bounding_box.x1), int(d.bounding_box.y1), int(d.bounding_box.x2), int(d.bounding_box.y2)),
                 float(d.confidence)) for d in ranked]

    def read_many(self, images: dict[str, np.ndarray]) -> dict[str, OcrOutput | None]:
        """Run the views as one batch and keep each slot's character probabilities."""
        recognizer = self.alpr.ocr.ocr_model
        names = list(images)
        convert = {"grayscale": cv2.COLOR_BGR2GRAY, "rgb": cv2.COLOR_BGR2RGB}.get(recognizer.config.image_color_mode)
        batch = [cv2.cvtColor(images[name], convert) if convert is not None else images[name] for name in names]
        fetch = [recognizer.plate_output_name]
        session = recognizer.model
        capture = _CapturingSession(session)
        recognizer.model = capture
        try:
            recognizer.run(batch, return_confidence=True)
        finally:
            recognizer.model = session
        probabilities = capture.output(fetch[0])
        alphabet = recognizer.config.alphabet
        pad = recognizer.config.pad_char
        return {name: _decode_slots(probabilities[i], alphabet, pad) for i, name in enumerate(names)}


class _CapturingSession:
    """Keeps the OCR model's raw per-slot output, which the public API reduces to one character."""

    def __init__(self, session) -> None:
        self._session = session
        self._outputs: dict[str, np.ndarray] = {}

    def run(self, names, feed):
        values = self._session.run(names, feed)
        self._outputs = dict(zip(names, values))
        return values

    def output(self, name: str) -> np.ndarray:
        return self._outputs[name]

    def __getattr__(self, name):
        return getattr(self._session, name)


def _decode_slots(slots: np.ndarray, alphabet: str, pad: str) -> OcrOutput | None:
    """Decode positional distributions. A pad is a spacer such as a plate's group gap, not a character."""
    top = slots.argmax(axis=1)
    last = max((i for i, code in enumerate(top) if alphabet[code] != pad), default=-1)
    if last < 0:
        return None
    text: list[str] = []
    confidences: list[float] = []
    alternatives: list[list[tuple[str, float]]] = []
    for index in range(last + 1):
        code = int(top[index])
        char = alphabet[code]
        if char == pad:
            continue
        ranked = [(alphabet[i], float(slots[index, i])) for i in np.argsort(slots[index])[::-1][:MAX_ALTERNATIVES + 2]]
        others = [(c, round(p, 4)) for c, p in ranked if c not in (char, pad) and p >= MIN_ALTERNATIVE_PROB]
        text.append(char)
        confidences.append(float(slots[index, code]))
        alternatives.append(others[:MAX_ALTERNATIVES])
    return OcrOutput("".join(text), confidences, alternatives)


class EasyOcrEngine:
    """Offline fallback. It reports one confidence per word, applied to each character."""

    name = "easyocr"

    def __init__(self) -> None:
        import easyocr

        self.reader = easyocr.Reader(["en"], gpu=active_device() == "cuda", verbose=False,
                                     download_enabled=settings.allow_model_download)

    def locate(self, image: np.ndarray) -> list[tuple[tuple[int, int, int, int], float]]:
        height, width = image.shape[:2]
        top = int(height * 0.35)
        found: list[tuple[float, tuple[int, int, int, int]]] = []
        for box, text, confidence in self.reader.readtext(image[top:], allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
            if len(_ALNUM.sub("", text.upper())) < 3:
                continue
            xs, ys = [p[0] for p in box], [p[1] + top for p in box]
            box = (max(int(min(xs)), 0), max(int(min(ys)), 0), min(int(max(xs)), width), min(int(max(ys)), height))
            found.append((float(confidence), box))
        return [(box, confidence) for confidence, box in sorted(found, key=lambda item: -item[0])]

    def read_many(self, images: dict[str, np.ndarray]) -> dict[str, OcrOutput | None]:
        return {name: self.read(image) for name, image in images.items()}

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
        box_confidence = 0.0
        for candidate, confidence in self.engine.locate(scaled):
            box = tuple(int(round(value / scale)) for value in candidate)
            if plate_belongs_to_target(box, target or (0, 0, width, height), occluders or []):
                located, box_confidence = box, confidence
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
        variants, rectification = build_variants(raw)
        outputs = self.engine.read_many(variants)
        combined = combine_variants(outputs)
        if combined is None:
            return None
        read = PlateRead(
            frame_idx=frame_idx, timestamp_sec=timestamp, raw_text=combined.text,
            char_confidences=combined.confidences, sharpness_score=quality,
            bbox_area=float(plate_width * plate_height),
            ocr_engine_score=float(np.mean(combined.confidences)),
            source=f"{self.engine.name}:multi-variant", char_alternatives=combined.alternatives,
            char_source_supported=combined.source_supported, char_variants=combined.variant_votes,
            ocr_engine=self.engine.name, crop_sha256=hashlib.sha256(raw.tobytes()).hexdigest(),
        )
        return PlateObservation(read, raw, variants, outputs, (x1, y1, x2, y2), box_confidence, quality, rectification)

    def read_stack(self, observations: list[PlateObservation]) -> tuple[PlateRead | None, np.ndarray | None]:
        """OCR a multi-frame stack. The read is flagged derived so it cannot count as extra frames."""
        if self.engine is None:
            return None, None
        stacked = stack_plates([item.raw_crop for item in observations])
        if stacked is None:
            return None, None
        views, _ = build_variants(stacked)
        combined = combine_variants(self.engine.read_many(views))
        if combined is None:
            return None, stacked
        when = float(np.mean([item.read.timestamp_sec for item in observations]))
        read = PlateRead(
            frame_idx=-1, timestamp_sec=when, raw_text=combined.text, char_confidences=combined.confidences,
            sharpness_score=plate_quality(stacked),
            bbox_area=float(max(item.read.bbox_area for item in observations)),
            ocr_engine_score=float(np.mean(combined.confidences)), source=f"{self.engine.name}:stack",
            derived=True, char_alternatives=combined.alternatives, char_source_supported=[False] * len(combined.text),
            char_variants=combined.variant_votes, ocr_engine=self.engine.name,
        )
        return read, stacked
