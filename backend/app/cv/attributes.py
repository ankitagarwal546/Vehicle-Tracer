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
KMEANS_CLUSTERS = 4
COLOUR_TEMPERATURE = 18.0
MAX_PIXELS = 4000

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
    "car": {"sedan": 1.0, "hatchback": 1.0, "suv": 1.0, "van": 0.45, "pickup_truck": 0.25, "auto-rickshaw": 0.35},
    "two-wheeler": {"two-wheeler": 1.0, "auto-rickshaw": 0.2},
    "bus": {"bus": 1.0, "van": 0.25, "heavy_truck": 0.15},
    "truck": {"heavy_truck": 1.0, "pickup_truck": 0.9, "van": 0.35, "bus": 0.15, "auto-rickshaw": 0.2},
}
YOLO_ONLY_BODY = {"car": "car", "two-wheeler": "two-wheeler", "bus": "bus", "truck": "heavy_truck"}


def gray_world(image: np.ndarray) -> np.ndarray:
    """Remove a global illuminant cast, such as sodium street lighting."""
    pixels = image.reshape(-1, 3).astype(np.float32)
    means = pixels.mean(axis=0)
    gains = means.mean() / np.maximum(means, 1.0)
    gains = np.clip(gains, 0.6, 1.6)
    return np.clip(image.astype(np.float32) * gains, 0, 255).astype(np.uint8)


def body_panel_mask(shape: tuple[int, int], plate_bbox: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """Mask out windshield/top 25%, wheels/bottom 20%, side margins and the plate."""
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[int(height * 0.25):int(height * 0.80), int(width * 0.08):int(width * 0.92)] = 255
    if plate_bbox is not None:
        x1, y1, x2, y2 = plate_bbox
        mask[max(y1, 0):max(y2, 0), max(x1, 0):max(x2, 0)] = 0
    return mask


def estimate_colour(
    crops: list[np.ndarray],
    plate_boxes: list[tuple[int, int, int, int] | None] | None = None,
) -> list[dict]:
    """Return the top-2 canonical colours with probabilities."""
    boxes = plate_boxes or [None] * len(crops)
    samples: list[np.ndarray] = []
    for crop, box in zip(crops[:5], boxes[:5]):
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            continue
        balanced = gray_world(crop)
        lab = cv2.cvtColor(balanced, cv2.COLOR_BGR2LAB)
        selected = lab[body_panel_mask(crop.shape[:2], box) > 0]
        if selected.size:
            samples.append(selected)
    if not samples:
        return []
    pixels = np.concatenate(samples).astype(np.float32)
    if len(pixels) > MAX_PIXELS:
        generator = np.random.default_rng(0)
        pixels = pixels[generator.choice(len(pixels), MAX_PIXELS, replace=False)]
    clusters = min(KMEANS_CLUSTERS, len(pixels))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(0)
    _, labels, centers = cv2.kmeans(pixels, clusters, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    shares = np.bincount(labels.ravel(), minlength=clusters) / len(labels)
    votes = np.zeros(len(_NAMES), dtype=np.float64)
    for center, share in zip(centers, shares):
        distances = np.linalg.norm((_REFERENCE_LAB - center) * np.array([0.6, 1.0, 1.0]), axis=1)
        membership = np.exp(-(distances - distances.min()) / COLOUR_TEMPERATURE)
        votes += share * membership / membership.sum()
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
    return {
        "label": labels[order[0]],
        "confidence": round(float(posterior[order[0]]), 4),
        "source": "yolo+openclip",
        "distribution": [{"label": labels[i], "confidence": round(float(posterior[i]), 4)} for i in order[:3]],
    }
