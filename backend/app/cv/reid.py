"""Cross-camera re-identification.

The system only *proposes* links. A proposal needs independent evidence: consistent readable
plate characters, or strong visual similarity with a plausible supplied time. Colour, body type
and make/model can never create a link. An investigator confirms or rejects every proposal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple

import cv2
import numpy as np

from app.cv.plate_fusion import UNKNOWN
from app.engine.confusion_matrices import body_similarity, colour_similarity, is_confusable

WEIGHT_VISUAL = 0.45
WEIGHT_PLATE = 0.30
WEIGHT_ATTRIBUTES = 0.25
MIN_PLATE_OVERLAP = 3
FULL_PLATE_LENGTH = 9
OVERLAP_TEMPORAL_FACTOR = 0.55
LONG_GAP_HOURS = 24.0
LONG_GAP_FACTOR = 0.85
HIST_BINS = (16, 6, 4)
HIST_GRID = 2

# Link evidence thresholds.
STRONG_PLATE_EXACT = 5
PARTIAL_PLATE_EXACT = 4
MIN_PLATE_AGREEMENT = 0.90
MIN_DISTINCT_CHARS = 3
PARTIAL_MIN_VISUAL = 0.45
PARTIAL_MIN_ATTRIBUTES = 0.50
VISUAL_ONLY_MIN = 0.80
VISUAL_ONLY_MIN_ATTRIBUTES = 0.60
CONTRADICTION_MIN_COMPARED = 4
CONTRADICTION_MAX_AGREEMENT = 0.70


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
    location: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PlateOverlap:
    agreement: float
    compared: int
    exact: int
    contradictions: int
    distinct: int


class LinkResult(NamedTuple):
    groups: list[list[str]]
    links: list[dict]
    blocked: int


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


def plate_overlap(a: str, b: str) -> PlateOverlap | None:
    """Compare known characters at the best slot alignment, or None without enough overlap."""
    if sum(c != UNKNOWN for c in a) < 2 or sum(c != UNKNOWN for c in b) < 2:
        return None
    # Two full-length reads share a coordinate frame. Partial reads may slide, and the
    # shift with the most matched evidence wins so a tiny accidental overlap cannot.
    full_frame = len(a) == len(b) and len(a) >= FULL_PLATE_LENGTH
    shifts = [0] if full_frame else range(-(len(b) - 1), len(a))
    best: tuple[float, float, PlateOverlap] | None = None
    for shift in shifts:
        score, compared, exact, contradictions = 0.0, 0, 0, 0
        chars: set[str] = set()
        for j, right in enumerate(b):
            i = j + shift
            if not 0 <= i < len(a) or a[i] == UNKNOWN or right == UNKNOWN:
                continue
            compared += 1
            if a[i] == right:
                score += 1.0
                exact += 1
                chars.add(right)
            elif is_confusable(a[i], right):
                score += 0.65
            else:
                contradictions += 1
        if compared < MIN_PLATE_OVERLAP:
            continue
        candidate = PlateOverlap(score / compared, compared, exact, contradictions, len(chars))
        if best is None or (score, candidate.agreement) > (best[0], best[1]):
            best = (score, candidate.agreement, candidate)
    return best[2] if best else None


def plate_compatibility(a: str, b: str) -> float | None:
    overlap = plate_overlap(a, b)
    return overlap.agreement if overlap else None


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


def temporal_check(a: TrackProfile, b: TrackProfile) -> tuple[str, float, str]:
    """Return ``(status, factor, note)``. Missing time is never treated as a passed check."""
    if not all((a.start, a.end, b.start, b.end)):
        missing = [label for label, value in (("first", a.start), ("second", b.start)) if value is None]
        return "unavailable", 1.0, f"Not validated: capture time missing for {' and '.join(missing)} sighting"
    if a.start <= b.end and b.start <= a.end:
        return "implausible", OVERLAP_TEMPORAL_FACTOR, "Implausible: sightings overlap in time at different cameras"
    gap = (max(a.start, b.start) - min(a.end, b.end)).total_seconds() / 3600
    if gap > LONG_GAP_HOURS:
        return "weak", LONG_GAP_FACTOR, f"Weak: {gap:.1f} h between sightings"
    return "plausible", 1.0, f"Plausible order: {gap * 60:.1f} min between sightings (travel route not checked)"


def temporal_factor(a: TrackProfile, b: TrackProfile) -> tuple[float, str]:
    _, factor, note = temporal_check(a, b)
    return factor, note


def _evidence_tier(overlap: PlateOverlap | None, visual: float, attributes: float | None,
                   temporal: str) -> tuple[str | None, str]:
    if overlap and overlap.compared >= CONTRADICTION_MIN_COMPARED and overlap.contradictions >= 2 \
            and overlap.agreement < CONTRADICTION_MAX_AGREEMENT:
        return None, "plate characters contradict each other"
    attributes_ok = attributes is None or attributes >= PARTIAL_MIN_ATTRIBUTES
    if overlap and overlap.agreement >= MIN_PLATE_AGREEMENT and overlap.distinct >= MIN_DISTINCT_CHARS:
        if overlap.exact >= STRONG_PLATE_EXACT:
            if temporal == "implausible":
                return None, "plate agrees but the sightings overlap in time"
            return "strong_plate", "consistent readable plate characters"
        if overlap.exact >= PARTIAL_PLATE_EXACT and visual >= PARTIAL_MIN_VISUAL and attributes_ok:
            if temporal == "implausible":
                return None, "partial plate agrees but the sightings overlap in time"
            return "partial_plate", "partial plate overlap with supporting visual similarity"
    if visual >= VISUAL_ONLY_MIN and temporal == "plausible" \
            and (attributes is None or attributes >= VISUAL_ONLY_MIN_ATTRIBUTES):
        return "visual_time", "strong visual similarity with a plausible capture time"
    return None, "insufficient independent evidence"


def pair_similarity(a: TrackProfile, b: TrackProfile) -> dict:
    visual = visual_similarity(a, b)
    overlap = plate_overlap(a.plate_text, b.plate_text)
    plate = overlap.agreement if overlap else None
    attributes = attribute_compatibility(a, b)
    signals = {"visual": (WEIGHT_VISUAL, visual), "plate": (WEIGHT_PLATE, plate),
               "attributes": (WEIGHT_ATTRIBUTES, attributes)}
    active = {key: value for key, value in signals.items() if value[1] is not None}
    total = sum(weight for weight, _ in active.values())
    base = sum(weight * value for weight, value in active.values()) / total
    status, factor, note = temporal_check(a, b)
    tier, tier_reason = _evidence_tier(overlap, visual, attributes, status)
    return {
        "a": a.vehicle_id, "b": b.vehicle_id, "score": round(base * factor, 4),
        "visual": round(visual, 4), "plate": None if plate is None else round(plate, 4),
        "plate_compared": overlap.compared if overlap else 0,
        "plate_exact": overlap.exact if overlap else 0,
        "plate_contradictions": overlap.contradictions if overlap else 0,
        "attributes": None if attributes is None else round(attributes, 4),
        "temporal_status": status, "temporal_factor": factor, "temporal_note": note,
        "location_context": f"{a.location or 'not supplied'} to {b.location or 'not supplied'}",
        "weights": {key: round(active[key][0] / total, 4) if key in active else 0.0 for key in signals},
        "evidence_tier": tier, "evidence_reason": tier_reason,
        "plate_conflict": tier_reason == "plate characters contradict each other",
    }


def link_tracks(profiles: list[TrackProfile]) -> LinkResult:
    """Group proposals greedily. A group never holds two tracks from one clip."""
    pairs = [
        pair_similarity(a, b)
        for index, a in enumerate(profiles)
        for b in profiles[index + 1:]
        if a.clip_id != b.clip_id
    ]
    tier_rank = {"strong_plate": 0, "partial_plate": 1, "visual_time": 2}
    eligible = sorted((p for p in pairs if p["evidence_tier"]),
                      key=lambda p: (tier_rank[p["evidence_tier"]], -p["score"]))
    blocked = sum(p["plate_conflict"] for p in pairs)
    groups = {profile.vehicle_id: {profile.vehicle_id} for profile in profiles}
    clip_of = {profile.vehicle_id: profile.clip_id for profile in profiles}
    accepted: list[dict] = []
    for pair in eligible:
        left, right = groups[pair["a"]], groups[pair["b"]]
        if left is right or {clip_of[v] for v in left} & {clip_of[v] for v in right}:
            continue
        left |= right
        for member in right:
            groups[member] = left
        accepted.append(pair)
    unique = {id(group): group for group in groups.values()}
    return LinkResult([sorted(group) for group in unique.values() if len(group) > 1], accepted, blocked)
