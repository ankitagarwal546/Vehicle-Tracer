"""Choose which track frames deserve plate OCR, and record every frame that was skipped."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

NEAR_DUPLICATE_DIFF = 2.5
NEAR_DUPLICATE_SECONDS = 1.0
STABLE_READS = 5
STABLE_MIN_CONFIDENCE = 0.9


@dataclass
class FrameSelection:
    selected: list
    near_duplicates: int


def _lower_body_signature(observation) -> np.ndarray:
    x1, y1, x2, y2 = observation.target_in_crop
    crop = observation.crop
    if x2 <= x1 or y2 <= y1:
        region = crop
    else:
        region = crop[y1 + (y2 - y1) // 3:y2, x1:x2]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (32, 16), interpolation=cv2.INTER_AREA).astype(np.float32)


def select_plate_frames(observations: Sequence) -> FrameSelection:
    """Keep the best-ranked frame of each near-identical group. Input is ordered best first."""
    selected: list = []
    signatures: list[tuple[float, np.ndarray]] = []
    skipped = 0
    for observation in observations:
        signature = _lower_body_signature(observation)
        duplicate = any(
            abs(observation.timestamp_sec - when) <= NEAR_DUPLICATE_SECONDS
            and float(np.abs(signature - other).mean()) < NEAR_DUPLICATE_DIFF
            for when, other in signatures
        )
        if duplicate:
            skipped += 1
            continue
        selected.append(observation)
        signatures.append((observation.timestamp_sec, signature))
    return FrameSelection(selected, skipped)


def reads_are_stable(reads: Sequence) -> bool:
    """True when enough source-supported frames agree on every character with high confidence."""
    if len(reads) < STABLE_READS:
        return False
    if len({read.raw_text for read in reads}) != 1:
        return False
    return all(
        min(read.char_confidences) >= STABLE_MIN_CONFIDENCE and all(read.char_source_supported)
        for read in reads
    )
