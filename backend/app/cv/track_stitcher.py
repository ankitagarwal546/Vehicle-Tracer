"""Repair tracker identity switches so one physical vehicle yields one result.

A pair of tracks is merged only when geometry and appearance agree independently:

* Consecutive fragments: the later track starts where the earlier track's motion predicts.
* Concurrent duplicates: both tracks cover nearly the same box over their shared frames.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

MAX_GAP_SEC = 4.0
MAX_OVERLAP_SEC = 0.35
MAX_CENTER_DISTANCE = 0.55
MIN_SIZE_RATIO = 0.6
MIN_APPEARANCE = 0.84
MIN_DUPLICATE_IOU = 0.6
MIN_DUPLICATE_APPEARANCE = 0.75
VELOCITY_POINTS = 6

Box = tuple[int, int, int, int]


class Stitchable(Protocol):
    track_id: int
    trajectory: list[tuple[float, Box]]


@dataclass(frozen=True)
class StitchDecision:
    kept: int
    merged: int
    score: float
    reason: str


def box_iou(a: Box, b: Box) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(x2 - x1, 0) * max(y2 - y1, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def _center(box: Box) -> np.ndarray:
    return np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2], dtype=np.float64)


def _size(box: Box) -> float:
    return float(np.hypot(box[2] - box[0], box[3] - box[1]))


def predicted_center(trajectory: Sequence[tuple[float, Box]], when: float) -> np.ndarray:
    """Extrapolate the last observed center with a least-squares constant velocity."""
    recent = trajectory[-VELOCITY_POINTS:]
    last_time, last_box = recent[-1]
    center = _center(last_box)
    if len(recent) < 2 or recent[-1][0] <= recent[0][0]:
        return center
    times = np.array([t for t, _ in recent]) - last_time
    centers = np.array([_center(box) for _, box in recent])
    velocity = np.array([np.polyfit(times, centers[:, axis], 1)[0] for axis in range(2)])
    return center + velocity * (when - last_time)


def fragment_geometry(earlier: Stitchable, later: Stitchable) -> float | None:
    """Return a 0..1 geometric score, or None when the tracks cannot be one continuous motion."""
    end_time, end_box = earlier.trajectory[-1]
    start_time, start_box = later.trajectory[0]
    gap = start_time - end_time
    if gap > MAX_GAP_SEC or gap < -MAX_OVERLAP_SEC:
        return None
    ratio = _size(start_box) / max(_size(end_box), 1.0)
    if not MIN_SIZE_RATIO <= ratio <= 1 / MIN_SIZE_RATIO:
        return None
    scale = (_size(end_box) * _size(start_box)) ** 0.5
    distance = float(np.linalg.norm(predicted_center(earlier.trajectory, start_time) - _center(start_box))) / scale
    if distance > MAX_CENTER_DISTANCE:
        return None
    return 1.0 - distance / MAX_CENTER_DISTANCE


def duplicate_iou(a: Stitchable, b: Stitchable) -> float | None:
    """Mean IoU over shared timestamps, or None when the tracks do not share any."""
    left = {round(t, 3): box for t, box in a.trajectory}
    shared = [(left[round(t, 3)], box) for t, box in b.trajectory if round(t, 3) in left]
    if not shared:
        return None
    return float(np.mean([box_iou(x, y) for x, y in shared]))


def plan_merges(
    tracks: Sequence[Stitchable],
    appearance: Callable[[Stitchable, Stitchable], float],
) -> list[StitchDecision]:
    """Greedily choose merges, best evidence first, keeping every group time-consistent."""
    proposals: list[tuple[float, int, int, str]] = []
    ordered = sorted(tracks, key=lambda t: t.trajectory[0][0])
    for index, earlier in enumerate(ordered):
        for later in ordered[index + 1:]:
            if later.trajectory[0][0] - earlier.trajectory[-1][0] > MAX_GAP_SEC:
                continue
            iou = duplicate_iou(earlier, later)
            if iou is not None and iou >= MIN_DUPLICATE_IOU:
                visual = appearance(earlier, later)
                if visual >= MIN_DUPLICATE_APPEARANCE:
                    proposals.append((iou + visual, earlier.track_id, later.track_id, "concurrent duplicate"))
                continue
            geometry = fragment_geometry(earlier, later)
            if geometry is None:
                continue
            visual = appearance(earlier, later)
            if visual >= MIN_APPEARANCE:
                proposals.append((geometry + visual, earlier.track_id, later.track_id, "track fragment"))
    proposals.sort(key=lambda item: (-item[0], item[1], item[2]))

    parent = {track.track_id: track.track_id for track in tracks}
    spans = {track.track_id: (track.trajectory[0][0], track.trajectory[-1][0]) for track in tracks}

    def find(track_id: int) -> int:
        while parent[track_id] != track_id:
            parent[track_id] = parent[parent[track_id]]
            track_id = parent[track_id]
        return track_id

    decisions: list[StitchDecision] = []
    for score, a, b, reason in proposals:
        root_a, root_b = find(a), find(b)
        if root_a == root_b:
            continue
        span_a, span_b = spans[root_a], spans[root_b]
        overlap = min(span_a[1], span_b[1]) - max(span_a[0], span_b[0])
        if reason == "track fragment" and overlap > MAX_OVERLAP_SEC:
            continue
        keep, drop = sorted((root_a, root_b))
        parent[drop] = keep
        spans[keep] = (min(span_a[0], span_b[0]), max(span_a[1], span_b[1]))
        decisions.append(StitchDecision(keep, drop, round(score, 4), reason))
    return [StitchDecision(find(d.kept), d.merged, d.score, d.reason) for d in decisions]
