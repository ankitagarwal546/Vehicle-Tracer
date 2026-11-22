"""Cross-camera re-identification and entity linking."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

from app.config import settings
from app.cv.plate_fusion import UNKNOWN
from app.engine.confusion_matrices import body_similarity, colour_similarity, is_confusable

WEIGHT_VISUAL = 0.45
WEIGHT_PLATE = 0.30
WEIGHT_ATTRIBUTES = 0.25
MIN_PLATE_OVERLAP = 3
FULL_PLATE_LENGTH = 9
PLATE_CONFLICT = 0.35
OVERLAP_TEMPORAL_FACTOR = 0.55
LONG_GAP_HOURS = 24.0
LONG_GAP_FACTOR = 0.85
HIST_BINS = (16, 6, 4)
HIST_GRID = 2


@dataclass
class TrackProfile:
    vehicle_id: str
    clip_id: str
    embedding: np.ndarray | None
    histogram: np.ndarray
    plate_text: str
    body_type: str | None
    colours: list[dict]
    make_models: list[dict]
    start: datetime | None = None
    end: datetime | None = None
    extra: dict = field(default_factory=dict)


def spatial_hsv_histogram(crops: list[np.ndarray]) -> np.ndarray:
    """L2-normalised HSV histograms over a 2x2 grid, averaged across crops."""
    descriptors = []
    for crop in crops[:5]:
        hsv = cv2.cvtColor(cv2.resize(crop, (96, 96)), cv2.COLOR_BGR2HSV)
        parts = []
        for row in range(HIST_GRID):
            for col in range(HIST_GRID):
                cell = hsv[row * 48:(row + 1) * 48, col * 48:(col + 1) * 48]
                parts.append(cv2.calcHist([cell], [0, 1, 2], None, HIST_BINS, [0, 180, 0, 256, 0, 256]).ravel())
        descriptors.append(np.concatenate(parts))
    if not descriptors:
        return np.zeros(int(np.prod(HIST_BINS)) * HIST_GRID ** 2, dtype=np.float32)
    mean = np.mean(descriptors, axis=0)
    return (mean / max(float(np.linalg.norm(mean)), 1e-9)).astype(np.float32)


def mean_embedding(embeddings: np.ndarray | None) -> np.ndarray | None:
    if embeddings is None or len(embeddings) == 0:
        return None
    mean = embeddings.mean(axis=0)
    return mean / max(float(np.linalg.norm(mean)), 1e-9)


def visual_similarity(a: TrackProfile, b: TrackProfile) -> float:
    histogram = float(np.clip(a.histogram @ b.histogram, 0, 1))
    if a.embedding is None or b.embedding is None:
        return histogram
    # CLIP cosine between unrelated vehicles is typically ~0.5, so rescale from that baseline.
    cosine = float(a.embedding @ b.embedding)
    rescaled = float(np.clip((cosine - 0.5) / 0.5, 0, 1))
    return 0.8 * rescaled + 0.2 * histogram


def plate_compatibility(a: str, b: str) -> float | None:
    """Return slot agreement over aligned known characters, or None without enough overlap."""
    if sum(c != UNKNOWN for c in a) < 2 or sum(c != UNKNOWN for c in b) < 2:
        return None
    # Two full-length reads share a coordinate frame. Partial reads may slide, and the
    # shift with the most matched evidence wins so a tiny accidental overlap cannot.
    full_frame = len(a) == len(b) and len(a) >= FULL_PLATE_LENGTH
    shifts = [0] if full_frame else range(-(len(b) - 1), len(a))
    best: tuple[float, float] | None = None
    for shift in shifts:
        score, count = 0.0, 0
        for j, right in enumerate(b):
            i = j + shift
            if not 0 <= i < len(a) or a[i] == UNKNOWN or right == UNKNOWN:
                continue
            count += 1
            score += 1.0 if a[i] == right else 0.65 if is_confusable(a[i], right) else 0.0
        if count >= MIN_PLATE_OVERLAP and (best is None or (score, score / count) > best):
            best = (score, score / count)
    return best[1] if best else None


def attribute_compatibility(a: TrackProfile, b: TrackProfile) -> float | None:
    parts: list[float] = []
    if a.body_type and b.body_type:
        parts.append(body_similarity(a.body_type, b.body_type))
    if a.colours and b.colours:
        total = sum(x["confidence"] * y["confidence"] for x in a.colours for y in b.colours)
        if total > 0:
            parts.append(sum(x["confidence"] * y["confidence"] * colour_similarity(x["label"], y["label"])
                             for x in a.colours for y in b.colours) / total)
    known_a = {(m["make"], m["model"]) for m in a.make_models if m["make"] != "Unknown"}
    known_b = {(m["make"], m["model"]) for m in b.make_models if m["make"] != "Unknown"}
    if known_a and known_b:
        parts.append(1.0 if known_a & known_b else 0.5 if {m for m, _ in known_a} & {m for m, _ in known_b} else 0.2)
    return float(np.mean(parts)) if parts else None


def temporal_factor(a: TrackProfile, b: TrackProfile) -> tuple[float, str]:
    if not all((a.start, a.end, b.start, b.end)):
        return 1.0, "no timestamps supplied"
    if a.start <= b.end and b.start <= a.end:
        return OVERLAP_TEMPORAL_FACTOR, "sightings overlap in time at different cameras"
    gap = (max(a.start, b.start) - min(a.end, b.end)).total_seconds() / 3600
    if gap > LONG_GAP_HOURS:
        return LONG_GAP_FACTOR, f"{gap:.1f} h between sightings"
    return 1.0, f"{gap * 60:.1f} min between sightings"


def pair_similarity(a: TrackProfile, b: TrackProfile) -> dict:
    visual = visual_similarity(a, b)
    plate = plate_compatibility(a.plate_text, b.plate_text)
    attributes = attribute_compatibility(a, b)
    signals = {"visual": (WEIGHT_VISUAL, visual), "plate": (WEIGHT_PLATE, plate),
               "attributes": (WEIGHT_ATTRIBUTES, attributes)}
    active = {key: value for key, value in signals.items() if value[1] is not None}
    total = sum(weight for weight, _ in active.values())
    base = sum(weight * value for weight, value in active.values()) / total
    factor, note = temporal_factor(a, b)
    return {
        "a": a.vehicle_id, "b": b.vehicle_id, "score": round(base * factor, 4),
        "visual": round(visual, 4), "plate": None if plate is None else round(plate, 4),
        "attributes": None if attributes is None else round(attributes, 4),
        "temporal_factor": factor, "temporal_note": note,
        "weights": {key: round(active[key][0] / total, 4) if key in active else 0.0 for key in signals},
        "plate_conflict": plate is not None and plate < PLATE_CONFLICT,
    }


def link_tracks(profiles: list[TrackProfile], threshold: float | None = None) -> tuple[list[list[str]], list[dict]]:
    """Greedy agglomerative linking. A group never holds two tracks from one clip."""
    cutoff = settings.reid_link_threshold if threshold is None else threshold
    pairs = [
        pair_similarity(a, b)
        for index, a in enumerate(profiles)
        for b in profiles[index + 1:]
        if a.clip_id != b.clip_id
    ]
    pairs.sort(key=lambda pair: -pair["score"])
    groups = {profile.vehicle_id: {profile.vehicle_id} for profile in profiles}
    clip_of = {profile.vehicle_id: profile.clip_id for profile in profiles}
    accepted: list[dict] = []
    for pair in pairs:
        if pair["score"] < cutoff or pair["plate_conflict"]:
            continue
        left, right = groups[pair["a"]], groups[pair["b"]]
        if left is right or {clip_of[v] for v in left} & {clip_of[v] for v in right}:
            continue
        left |= right
        for member in right:
            groups[member] = left
        accepted.append(pair)
    unique = {id(group): group for group in groups.values()}
    return [sorted(group) for group in unique.values() if len(group) > 1], accepted
