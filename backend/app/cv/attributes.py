"""Lighting-robust colour estimation and body type classification."""
from __future__ import annotations

import cv2
import numpy as np

from app.cv.clip_service import ClipService

# Reference colours in OpenCV 8-bit CIELAB.
COLOUR_REFERENCES: dict[str, tuple[int, int, int]] = {
    "white": (240, 128, 128), "silver": (185, 128, 128), "grey": (125, 128, 128), "black": (35, 128, 128),
    "red": (120, 185, 160), "maroon": (65, 160, 140), "blue": (80, 140, 90), "green": (95, 95, 150),
    "yellow": (215, 115, 195), "orange": (165, 160, 185), "brown": (90, 142, 155), "beige": (205, 132, 150),
}
_NAMES = list(COLOUR_REFERENCES)
_REFERENCE_LAB = np.array([COLOUR_REFERENCES[name] for name in _NAMES], dtype=np.float32)
LAB_WEIGHT = np.array([0.45, 1.0, 1.0], dtype=np.float32)
COLOUR_TEMPERATURE = 9.0
MAX_PIXELS = 6000
SPECULAR_L = 250
CHROMA_MIN = 18.0
MIN_CHROMATIC_SHARE = 0.32
STRONG_CHROMATIC_SHARE = 0.18
STRONG_CHROMA = 30.0
EXPOSURE_TARGET_L = 205.0
NEUTRAL_SIGMA = 34.0
_NEUTRALS = {"black": 45.0, "grey": 105.0, "silver": 158.0, "white": 215.0}
BODY_MIN_CONFIDENCE = 0.55

BODY_PROMPTS: dict[str, list[str]] = {
    "sedan": ["a photo of a sedan car with a separate boot", "a CCTV image of a four door saloon car"],
    "hatchback": ["a photo of a small hatchback car", "a CCTV image of a compact hatchback"],
    "suv": ["a photo of a large SUV", "a CCTV image of a sport utility vehicle"],
    "two-wheeler": ["a photo of a motorcycle", "a CCTV image of a scooter with a rider"],
    "auto-rickshaw": ["a photo of an Indian three wheeled auto rickshaw", "a CCTV image of a tuk tuk"],
    "pickup_truck": ["a photo of a small pickup truck", "a CCTV image of a light goods carrier"],
    "heavy_truck": ["a photo of a heavy cargo lorry", "a CCTV image of a large goods truck"],
    "bus": ["a photo of a passenger bus", "a CCTV image of a city bus"],
    "van": ["a photo of a passenger van", "a CCTV image of a minivan"],
}
YOLO_PRIORS: dict[str, dict[str, float]] = {
    "car": {"sedan": 1.0, "hatchback": 1.0, "suv": 1.0, "van": 0.3, "pickup_truck": 0.2, "auto-rickshaw": 0.2},
    "two-wheeler": {"two-wheeler": 1.0, "auto-rickshaw": 0.2},
    "bus": {"bus": 1.0, "van": 0.25, "heavy_truck": 0.15},
    "truck": {"heavy_truck": 1.0, "pickup_truck": 0.9, "van": 0.35, "bus": 0.15, "auto-rickshaw": 0.2},
}
YOLO_ONLY_BODY = {"car": "car", "two-wheeler": "two-wheeler", "bus": "bus", "truck": "heavy_truck"}


def gray_world(image: np.ndarray, reference: np.ndarray | None = None) -> np.ndarray:
    """Remove a global illuminant cast, such as sodium street lighting.

    The illuminant is estimated from ``reference``, normally the full scene. Estimating it
    from a crop filled by one vehicle would wrongly neutralise that vehicle's paint.
    """
    source = image if reference is None else reference
    pixels = source.reshape(-1, 3).astype(np.float32)
    means = pixels.mean(axis=0)
    gains = means.mean() / np.maximum(means, 1.0)
    gains = np.clip(gains, 0.6, 1.6)
    return np.clip(image.astype(np.float32) * gains, 0, 255).astype(np.uint8)


def body_panel_mask(shape: tuple[int, int], plate_bbox: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """Select the bonnet or boot panel, excluding glass, wheels, side context and the plate."""
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[int(height * 0.42):int(height * 0.80), int(width * 0.18):int(width * 0.82)] = 255
    if plate_bbox is not None:
        x1, y1, x2, y2 = plate_bbox
        mask[max(y1, 0):max(y2, 0), max(x1, 0):max(x2, 0)] = 0
    return mask


def _exposure_gain(scene: np.ndarray | None) -> float:
    """Normalise panel brightness to scene exposure so dusk footage does not turn white to grey."""
    if scene is None:
        return 1.0
    lightness = cv2.cvtColor(scene, cv2.COLOR_BGR2LAB)[:, :, 0]
    return float(np.clip(EXPOSURE_TARGET_L / max(float(np.percentile(lightness, 90)), 1.0), 0.85, 1.45))


def _soft_votes(values: np.ndarray, references: np.ndarray, temperature: float) -> np.ndarray:
    distances = np.linalg.norm(references - values[:, None, :], axis=2)
    weights = np.exp(-(distances - distances.min(axis=1, keepdims=True)) / temperature)
    weights /= weights.sum(axis=1, keepdims=True)
    return weights.mean(axis=0)


def estimate_colour(
    crops: list[np.ndarray],
    plate_boxes: list[tuple[int, int, int, int] | None] | None = None,
    scenes: list[np.ndarray | None] | None = None,
) -> list[dict]:
    """Return the top-2 canonical colours. White balance is applied only with scene context."""
    boxes = plate_boxes or [None] * len(crops)
    references = scenes or [None] * len(crops)
    samples: list[np.ndarray] = []
    for crop, box, scene in zip(crops[:5], boxes[:5], references[:5]):
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            continue
        balanced = gray_world(crop, scene) if scene is not None else crop
        lab = cv2.cvtColor(balanced, cv2.COLOR_BGR2LAB).astype(np.float32)
        selected = lab[body_panel_mask(crop.shape[:2], box) > 0]
        if selected.size:
            selected = selected[selected[:, 0] < SPECULAR_L]
            selected[:, 0] = np.clip(selected[:, 0] * _exposure_gain(scene), 0, 255)
            samples.append(selected)
    if not samples or not sum(len(s) for s in samples):
        return []
    pixels = np.concatenate(samples)
    if len(pixels) > MAX_PIXELS:
        pixels = pixels[np.random.default_rng(0).choice(len(pixels), MAX_PIXELS, replace=False)]
    chroma = np.hypot(pixels[:, 1] - 128, pixels[:, 2] - 128)
    chromatic = chroma >= CHROMA_MIN
    votes = np.zeros(len(_NAMES), dtype=np.float64)
    strong_paint = chromatic.mean() >= STRONG_CHROMATIC_SHARE \
        and chromatic.any() and float(np.median(chroma[chromatic])) >= STRONG_CHROMA
    if chromatic.mean() >= MIN_CHROMATIC_SHARE or strong_paint:
        indices = [i for i, name in enumerate(_NAMES) if name not in _NEUTRALS]
        # Glass and shadow dilute painted area, so painted pixels carry extra weight.
        painted = min(float(chromatic.mean()) * 1.8, 0.95)
        votes[indices] = _soft_votes(pixels[chromatic] * LAB_WEIGHT, _REFERENCE_LAB[indices] * LAB_WEIGHT,
                                     COLOUR_TEMPERATURE) * painted
        neutral_share = 1.0 - painted
    else:
        neutral_share = 1.0
    neutral_pixels = pixels[~chromatic] if (~chromatic).any() else pixels
    # The median is robust to the sky reflections that make a black bonnet look grey.
    level = float(np.median(neutral_pixels[:, 0]))
    neutral_indices = [_NAMES.index(name) for name in _NEUTRALS]
    centres = np.array([_NEUTRALS[name] for name in _NEUTRALS], dtype=np.float64)
    membership = np.exp(-((centres - level) / NEUTRAL_SIGMA) ** 2)
    votes[neutral_indices] += neutral_share * membership / membership.sum()
    votes /= votes.sum()
    top = np.argsort(votes)[::-1][:2]
    return [{"label": _NAMES[i], "confidence": round(float(votes[i]), 4)} for i in top]


def classify_body(
    yolo_class: str,
    yolo_confidence: float,
    embedding: np.ndarray | None,
    clip: ClipService | None,
) -> dict:
    prior = YOLO_PRIORS.get(yolo_class, {})
    if embedding is None or clip is None or not clip.available or not prior:
        label = YOLO_ONLY_BODY.get(yolo_class, yolo_class)
        return {"label": label, "confidence": round(min(yolo_confidence, 0.7), 4), "source": "yolo",
                "distribution": [{"label": label, "confidence": round(min(yolo_confidence, 0.7), 4)}]}
    labels = list(prior)
    probabilities = clip.zero_shot(embedding, [BODY_PROMPTS[label] for label in labels])
    posterior = probabilities * np.array([prior[label] for label in labels])
    posterior /= posterior.sum()
    order = np.argsort(posterior)[::-1]
    distribution = [{"label": labels[i], "confidence": round(float(posterior[i]), 4)} for i in order[:3]]
    if float(posterior[order[0]]) < BODY_MIN_CONFIDENCE:
        # Report the detector's broad class rather than a fine-grained guess.
        return {"label": YOLO_ONLY_BODY.get(yolo_class, yolo_class), "confidence": round(min(yolo_confidence, 0.7), 4),
                "source": "yolo (fine type uncertain)", "distribution": distribution}
    return {
        "label": labels[order[0]],
        "confidence": round(float(posterior[order[0]]), 4),
        "source": "yolo+openclip",
        "distribution": distribution,
    }
