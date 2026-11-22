"""Multi-frame plate fusion with sequence alignment and a strict anti-hallucination gate.

A slot is emitted only when frame evidence supports it. Otherwise it is ``?`` and the
runner-up characters are retained as evidence for the matcher, never written into the plate.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.config import settings
from app.engine.confusion_matrices import is_confusable
from app.engine.schemas import CharCandidate, PlateEvidence, SlotEvidence

UNKNOWN = "?"
MATCH = 2.0
CONFUSABLE = 0.8
WILDCARD = 0.1
MISMATCH = -1.5
GAP = -1.2
MIN_READ_LENGTH = 3
MAX_READ_LENGTH = 12
MIN_NORM_WEIGHT = 0.15
MIN_CHAR_CONFIDENCE = 0.05


@dataclass
class PlateRead:
    frame_idx: int
    timestamp_sec: float
    raw_text: str
    char_confidences: list[float]
    sharpness_score: float = 1.0
    bbox_area: float = 1.0
    ocr_engine_score: float = 1.0
    source: str = ""


@dataclass
class FusedSlot:
    position: int
    char: str
    confidence: float
    candidates: list[tuple[str, float]]
    support_frames: int
    observed_frames: int


@dataclass
class FusedPlate:
    text: str
    slots: list[FusedSlot]
    matrix: list[dict] = field(default_factory=list)
    reads_used: int = 0
    reads_rejected: int = 0

    @property
    def known_count(self) -> int:
        return sum(slot.char != UNKNOWN for slot in self.slots)

    def to_evidence(self) -> PlateEvidence:
        slots = [
            SlotEvidence(
                char=slot.char,
                confidence=slot.confidence if slot.char != UNKNOWN else 0.0,
                candidates=[CharCandidate(char=c, probability=p) for c, p in slot.candidates],
            )
            for slot in self.slots
        ]
        return PlateEvidence(slots=slots, anchor="full" if len(slots) >= 9 else "floating")

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "known_count": self.known_count,
            "reads_used": self.reads_used,
            "reads_rejected": self.reads_rejected,
            "slots": [
                {
                    "position": s.position,
                    "char": s.char,
                    "confidence": round(s.confidence, 4),
                    "candidates": [{"char": c, "probability": round(p, 4)} for c, p in s.candidates],
                    "support_frames": s.support_frames,
                    "observed_frames": s.observed_frames,
                }
                for s in self.slots
            ],
            "matrix": self.matrix,
        }


def _pair_score(a: str, b: str) -> float:
    if a == UNKNOWN or b == UNKNOWN:
        return WILDCARD
    if a == b:
        return MATCH
    return CONFUSABLE if is_confusable(a, b) else MISMATCH


def align(reference: str, read: str) -> list[tuple[int, int]]:
    """Semi-global Needleman-Wunsch. End gaps are free so partial reads can overhang.

    Returns ``(reference_index, read_index)`` pairs for aligned, non-gap columns.
    """
    rows, cols = len(reference), len(read)
    score = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    trace = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        trace[i][0] = 1
    for j in range(1, cols + 1):
        trace[0][j] = 2
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            diagonal = score[i - 1][j - 1] + _pair_score(reference[i - 1], read[j - 1])
            up = score[i - 1][j] + (0.0 if j == cols else GAP)
            left = score[i][j - 1] + (0.0 if i == rows else GAP)
            best = max(diagonal, up, left)
            score[i][j] = best
            trace[i][j] = 0 if best == diagonal else 1 if best == up else 2
    pairs: list[tuple[int, int]] = []
    i, j = rows, cols
    while i > 0 or j > 0:
        move = trace[i][j]
        if move == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif move == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _clean(read: PlateRead) -> PlateRead | None:
    chars: list[str] = []
    confidences: list[float] = []
    raw = read.raw_text.upper()
    source = read.char_confidences if len(read.char_confidences) == len(raw) else [read.ocr_engine_score] * len(raw)
    for char, confidence in zip(raw, source):
        if char.isalnum() and char.isascii():
            keep = confidence >= MIN_CHAR_CONFIDENCE
            chars.append(char if keep else UNKNOWN)
            confidences.append(float(confidence) if keep else 0.0)
        elif char == UNKNOWN:
            chars.append(UNKNOWN)
            confidences.append(0.0)
    known = sum(char != UNKNOWN for char in chars)
    if not MIN_READ_LENGTH <= len(chars) <= MAX_READ_LENGTH or known < 2:
        return None
    return PlateRead(read.frame_idx, read.timestamp_sec, "".join(chars), confidences,
                     read.sharpness_score, read.bbox_area, read.ocr_engine_score, read.source)


def _normalise(values: list[float]) -> list[float]:
    peak = max(values, default=0.0)
    if peak <= 0:
        return [1.0 for _ in values]
    return [max(MIN_NORM_WEIGHT, value / peak) for value in values]


def _reject_length_outliers(reads: list[PlateRead]) -> list[PlateRead]:
    lengths = sorted(len(read.raw_text) for read in reads)
    median = lengths[len(lengths) // 2]
    return [read for read in reads if len(read.raw_text) <= median + 2]


def fuse_plate_reads(
    reads: list[PlateRead],
    tau_char: float | None = None,
    single_frame_min_conf: float | None = None,
) -> FusedPlate:
    tau = settings.tau_char if tau_char is None else tau_char
    single_min = settings.single_frame_min_conf if single_frame_min_conf is None else single_frame_min_conf
    cleaned = [clean for clean in map(_clean, reads) if clean is not None]
    if not cleaned:
        return FusedPlate(text="", slots=[], reads_rejected=len(reads))
    kept = _reject_length_outliers(cleaned)
    rejected = len(reads) - len(kept)

    sharpness = _normalise([read.sharpness_score for read in kept])
    area = _normalise([read.bbox_area for read in kept])
    frame_weight = {id(read): sharpness[i] * area[i] for i, read in enumerate(kept)}
    ordered = sorted(
        kept,
        key=lambda r: (-sum(ch != UNKNOWN for ch in r.raw_text), -frame_weight[id(r)] * r.ocr_engine_score, r.frame_idx),
    )

    # Progressive alignment: each column stores (read, char, confidence, weight).
    columns: list[list[tuple[PlateRead, str, float, float]]] = [
        [(ordered[0], ch, conf, conf * frame_weight[id(ordered[0])])]
        for ch, conf in zip(ordered[0].raw_text, ordered[0].char_confidences)
    ]

    def consensus() -> str:
        output = []
        for column in columns:
            tally: dict[str, float] = defaultdict(float)
            for _, char, _, weight in column:
                if char != UNKNOWN:
                    tally[char] += weight
            output.append(max(sorted(tally), key=tally.get) if tally else UNKNOWN)
        return "".join(output)

    for read in ordered[1:]:
        pairs = align(consensus(), read.raw_text)
        if not pairs:
            continue
        shift = pairs[0][0] - pairs[0][1]
        if shift < 0:
            columns[:0] = [[] for _ in range(-shift)]
            pairs = [(ref - shift, idx) for ref, idx in pairs]
            shift = 0
        placed = {idx: ref for ref, idx in pairs}
        for idx, (char, conf) in enumerate(zip(read.raw_text, read.char_confidences)):
            target = placed.get(idx)
            if target is None and (idx < pairs[0][1] or idx > pairs[-1][1]):
                target = idx + (pairs[0][0] - pairs[0][1] if idx < pairs[0][1] else pairs[-1][0] - pairs[-1][1])
            if target is None or target < 0:
                continue
            while target >= len(columns):
                columns.append([])
            columns[target].append((read, char, conf, conf * frame_weight[id(read)]))

    slots: list[FusedSlot] = []
    for position, column in enumerate(columns):
        tally: dict[str, float] = defaultdict(float)
        confidences: dict[str, list[float]] = defaultdict(list)
        for _, char, conf, weight in column:
            if char != UNKNOWN:
                tally[char] += weight
                confidences[char].append(conf)
        total = sum(tally.values())
        observed = sum(len(items) for items in confidences.values())
        if total <= 0:
            slots.append(FusedSlot(position, UNKNOWN, 0.0, [], 0, 0))
            continue
        ranked = sorted(((char, value / total) for char, value in tally.items()), key=lambda x: (-x[1], x[0]))
        winner, posterior = ranked[0]
        miss = 1.0
        for conf in confidences[winner]:
            miss *= 1.0 - conf
        fused = posterior * (1.0 - miss)
        support = len(confidences[winner])
        passes = fused >= tau and (support >= 2 or max(confidences[winner]) >= single_min)
        if passes:
            slots.append(FusedSlot(position, winner, fused, ranked[1:3], support, observed))
        else:
            slots.append(FusedSlot(position, UNKNOWN, fused, ranked[:2], support, observed))

    while slots and slots[0].observed_frames == 0:
        slots.pop(0)
        columns.pop(0)
    while slots and slots[-1].observed_frames == 0:
        slots.pop()
        columns.pop()
    for index, slot in enumerate(slots):
        slot.position = index

    by_read: dict[int, dict] = {}
    for position, column in enumerate(columns):
        for read, char, conf, _ in column:
            row = by_read.setdefault(id(read), {
                "frame_idx": read.frame_idx,
                "timestamp_sec": round(read.timestamp_sec, 3),
                "raw_text": read.raw_text,
                "source": read.source,
                "sharpness": round(read.sharpness_score, 2),
                "cells": [{"char": UNKNOWN, "confidence": 0.0} for _ in columns],
            })
            row["cells"][position] = {"char": char, "confidence": round(conf, 4)}
    matrix = sorted(by_read.values(), key=lambda row: (row["timestamp_sec"], row["frame_idx"]))
    return FusedPlate("".join(s.char for s in slots), slots, matrix, len(kept), rejected)
