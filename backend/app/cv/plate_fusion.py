"""Multi-frame plate fusion with sequence alignment and a strict anti-hallucination gate.

Every fused slot keeps the frame, character and confidence of each read that voted for it.
A slot is emitted only when frame evidence supports it. Otherwise it is ``?`` and runner-up
characters are retained as evidence for the matcher, never written into the plate.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
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
MAX_PLATE_SLOTS = 10
MIN_NORM_WEIGHT = 0.15
MIN_CHAR_CONFIDENCE = 0.05
MIN_READ_CONFIDENCE = 0.40
MAX_REPEAT_SHARE = 0.70
MIN_ALIGNED_CHARS = 3
MIN_READ_IDENTITY = 0.55
CONFUSABLE_IDENTITY = 0.7
FULL_PLATE_SLOTS = 9
MAX_SLOT_EVIDENCE = 12
CONFLICT_RUNNER_UP = 0.25
MIN_CONFLICT_FRAMES = 2
# A character needs a clear majority of the frames that saw its position.
MIN_FRAME_AGREEMENT = 2 / 3
MIN_SLOT_OBSERVATION_SHARE = 0.3


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
    derived: bool = False  # A multi-frame stack repeats frames, so it is not independent evidence.
    char_alternatives: list[list[tuple[str, float]]] = field(default_factory=list)
    char_source_supported: list[bool] = field(default_factory=list)
    char_variants: list[list[dict]] = field(default_factory=list)
    ocr_engine: str = ""
    crop: str | None = None
    crop_sha256: str | None = None
    withheld: frozenset[int] = frozenset()

    def alternatives_at(self, index: int) -> list[tuple[str, float]]:
        return self.char_alternatives[index] if index < len(self.char_alternatives) else []

    def source_supported_at(self, index: int) -> bool:
        return self.char_source_supported[index] if index < len(self.char_source_supported) else True

    def variants_at(self, index: int) -> list[dict]:
        return self.char_variants[index] if index < len(self.char_variants) else []


@dataclass
class SlotVote:
    frame_idx: int
    timestamp_sec: float
    char: str
    confidence: float
    source: str
    source_supported: bool = True
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    variants: list[dict] = field(default_factory=list)
    crop: str | None = None
    crop_sha256: str | None = None
    ocr_engine: str = ""


@dataclass
class FusedSlot:
    position: int
    char: str
    confidence: float
    candidates: list[tuple[str, float]]
    support_frames: int
    observed_frames: int
    evidence: list[SlotVote] = field(default_factory=list)
    unknown_reason: str | None = None
    source_supported_frames: int = 0


@dataclass
class FusedPlate:
    text: str
    slots: list[FusedSlot]
    matrix: list[dict] = field(default_factory=list)
    reads_used: int = 0
    reads_rejected: int = 0
    rejected_reads: list[dict] = field(default_factory=list)

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
        return PlateEvidence(slots=slots, anchor="full" if len(slots) >= FULL_PLATE_SLOTS else "floating")

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "known_count": self.known_count,
            "reads_used": self.reads_used,
            "reads_rejected": self.reads_rejected,
            "rejected_reads": self.rejected_reads,
            "slots": [
                {
                    "position": s.position,
                    "char": s.char,
                    "confidence": round(s.confidence, 4),
                    "candidates": [{"char": c, "probability": round(p, 4)} for c, p in s.candidates],
                    "support_frames": s.support_frames,
                    "observed_frames": s.observed_frames,
                    "source_supported_frames": s.source_supported_frames,
                    "unknown_reason": s.unknown_reason,
                    "evidence": [
                        {"frame_idx": v.frame_idx, "timestamp_sec": round(v.timestamp_sec, 3), "char": v.char,
                         "confidence": round(v.confidence, 4), "source": v.source,
                         "source_supported": v.source_supported, "ocr_engine": v.ocr_engine, "crop": v.crop,
                         "crop_sha256": v.crop_sha256,
                         "alternatives": [{"char": c, "probability": round(p, 4)} for c, p in v.alternatives],
                         "variants": v.variants}
                        for v in s.evidence[:MAX_SLOT_EVIDENCE]
                    ],
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


def alignment_identity(reference: str, read: str, pairs: list[tuple[int, int]]) -> tuple[float, int]:
    """Return ``(identity, compared_chars)`` over aligned slots where both characters are known."""
    value, compared = 0.0, 0
    for ref_index, read_index in pairs:
        left, right = reference[ref_index], read[read_index]
        if left == UNKNOWN or right == UNKNOWN:
            continue
        compared += 1
        value += 1.0 if left == right else CONFUSABLE_IDENTITY if is_confusable(left, right) else 0.0
    return (value / compared if compared else 0.0), compared


def _rejection(read: PlateRead, reason: str) -> dict:
    return {"frame_idx": read.frame_idx, "timestamp_sec": round(read.timestamp_sec, 3), "raw_text": read.raw_text,
            "source": read.source, "reason": reason}


def _clean(read: PlateRead, digits_only: bool = False) -> tuple[PlateRead | None, str | None]:
    chars: list[str] = []
    confidences: list[float] = []
    kept: list[int] = []
    raw = read.raw_text.upper()
    source = read.char_confidences if len(read.char_confidences) == len(raw) else [read.ocr_engine_score] * len(raw)
    for index, (char, confidence) in enumerate(zip(raw, source)):
        if char.isalnum() and char.isascii():
            keep = confidence >= MIN_CHAR_CONFIDENCE
            chars.append(char if keep else UNKNOWN)
            confidences.append(float(confidence) if keep else 0.0)
            kept.append(index)
        elif char == UNKNOWN:
            chars.append(UNKNOWN)
            confidences.append(0.0)
            kept.append(index)
    withheld: set[int] = set()
    if digits_only:
        # OCR can render a foreign letter as a digit, so trust only the longest numeric block.
        block = max(re.finditer(r"[0-9]+", "".join(chars)), key=lambda m: len(m.group()), default=None)
        allowed = range(block.start(), block.end()) if block else range(0)
        withheld = {i for i, char in enumerate(chars) if i not in allowed}
        chars = [UNKNOWN if i in withheld else char for i, char in enumerate(chars)]
        confidences = [0.0 if i in withheld else conf for i, conf in enumerate(confidences)]
    known = [(char, conf) for char, conf in zip(chars, confidences) if char != UNKNOWN]
    if not MIN_READ_LENGTH <= len(chars) <= MAX_READ_LENGTH:
        return None, "length outside plausible plate range"
    if len(known) < 2:
        return None, "too few readable characters"
    if sum(conf for _, conf in known) / len(known) < MIN_READ_CONFIDENCE:
        return None, "read confidence too low"
    if len(known) >= 5 and Counter(c for c, _ in known).most_common(1)[0][1] / len(known) >= MAX_REPEAT_SHARE:
        return None, "repeated-character OCR artefact"
    return PlateRead(
        read.frame_idx, read.timestamp_sec, "".join(chars), confidences, read.sharpness_score, read.bbox_area,
        read.ocr_engine_score, read.source, read.derived,
        [[] if k in withheld_positions(kept, withheld) else read.alternatives_at(k) for k in kept],
        [read.source_supported_at(k) for k in kept],
        [read.variants_at(k) for k in kept],
        read.ocr_engine, read.crop, read.crop_sha256, frozenset(withheld),
    ), None


def withheld_positions(kept: list[int], withheld: set[int]) -> set[int]:
    return {kept[i] for i in withheld}


def _normalise(values: list[float]) -> list[float]:
    peak = max(values, default=0.0)
    if peak <= 0:
        return [1.0 for _ in values]
    return [max(MIN_NORM_WEIGHT, value / peak) for value in values]


def _seed_order(reads: list[PlateRead], weight: dict[int, float]) -> list[PlateRead]:
    """Order reads by how strongly other frames corroborate them, so noise cannot seed the frame."""
    support: dict[int, float] = {}
    for read in reads:
        total = 0.0
        for other in reads:
            if other is read:
                continue
            identity, compared = alignment_identity(read.raw_text, other.raw_text, align(read.raw_text, other.raw_text))
            if compared >= MIN_ALIGNED_CHARS and identity >= MIN_READ_IDENTITY:
                total += identity * compared * weight[id(other)]
        support[id(read)] = total
    return sorted(reads, key=lambda r: (
        r.derived,
        -support[id(r)],
        -sum(ch != UNKNOWN for ch in r.raw_text),
        -weight[id(r)] * r.ocr_engine_score,
        r.frame_idx,
    ))


def fuse_plate_reads(
    reads: list[PlateRead],
    tau_char: float | None = None,
    single_frame_min_conf: float | None = None,
    digits_only: bool = False,
) -> FusedPlate:
    """Fuse reads. ``digits_only`` withholds letters when the plate uses a script OCR cannot read."""
    tau = settings.tau_char if tau_char is None else tau_char
    single_min = settings.single_frame_min_conf if single_frame_min_conf is None else single_frame_min_conf

    rejected: list[dict] = []
    kept: list[PlateRead] = []
    for read in reads:
        clean, reason = _clean(read, digits_only)
        if clean is None:
            rejected.append(_rejection(read, reason or "invalid read"))
        else:
            kept.append(clean)
    if not kept:
        return FusedPlate(text="", slots=[], reads_rejected=len(reads), rejected_reads=rejected)

    sharpness = _normalise([read.sharpness_score for read in kept])
    area = _normalise([read.bbox_area for read in kept])
    frame_weight = {id(read): sharpness[i] * area[i] for i, read in enumerate(kept)}
    ordered = _seed_order(kept, frame_weight)

    # Each column stores (read, char, confidence, weight), so a slot never loses its source frame.
    seed = ordered[0]
    columns: list[list[tuple[PlateRead, str, float, float, int]]] = [
        [(seed, ch, conf, conf * frame_weight[id(seed)], index)]
        for index, (ch, conf) in enumerate(list(zip(seed.raw_text, seed.char_confidences))[:MAX_PLATE_SLOTS])
    ]
    if len(seed.raw_text) > MAX_PLATE_SLOTS:
        rejected.append(_rejection(seed, f"characters beyond slot {MAX_PLATE_SLOTS} ignored"))

    def consensus() -> str:
        output = []
        for column in columns:
            tally: dict[str, float] = defaultdict(float)
            for _, char, _, weight, _ in column:
                if char != UNKNOWN:
                    tally[char] += weight
            output.append(max(sorted(tally), key=tally.get) if tally else UNKNOWN)
        return "".join(output)

    # When reads cannot share one plate-length frame, OCR has inserted or dropped a character.
    # Only columns that the conflicting reads align on remain reliable.
    trusted_columns: set[int] | None = None
    used = 1
    for read in ordered[1:]:
        reference = consensus()
        pairs = align(reference, read.raw_text)
        identity, compared = alignment_identity(reference, read.raw_text, pairs)
        if compared < MIN_ALIGNED_CHARS or identity < MIN_READ_IDENTITY:
            rejected.append(_rejection(read, "does not align with the other frames"))
            continue
        used += 1
        # If an earlier read dropped a character that this read saw, open a slot for it.
        missing = sum(
            max((later_index - index - 1) - (later_ref - ref - 1), 0)
            for (ref, index), (later_ref, later_index) in zip(pairs, pairs[1:])
        )
        if missing and len(columns) + missing <= MAX_PLATE_SLOTS:
            for (ref, index), (later_ref, later_index) in reversed(list(zip(pairs, pairs[1:]))):
                for _ in range(max((later_index - index - 1) - (later_ref - ref - 1), 0)):
                    columns.insert(ref + 1, [])
            pairs = align(consensus(), read.raw_text)
        first_ref, first_read = pairs[0]
        last_ref, last_read = pairs[-1]
        placed = {index: ref for ref, index in pairs}
        targets: dict[int, int] = {}
        for index in range(len(read.raw_text)):
            if index in placed:
                targets[index] = placed[index]
            elif index < first_read:
                targets[index] = first_ref - (first_read - index)
            elif index > last_read:
                targets[index] = last_ref + (index - last_read)
        lowest = min(targets.values())
        highest = max(targets.values())
        if max(highest, len(columns) - 1) - min(lowest, 0) + 1 > MAX_PLATE_SLOTS:
            agreed = {id(columns[ref]) for ref, index in pairs if read.raw_text[index] != UNKNOWN}
            trusted_columns = agreed if trusted_columns is None else trusted_columns & agreed
            for ref, index in pairs:
                columns[ref].append((read, read.raw_text[index], read.char_confidences[index],
                                     read.char_confidences[index] * frame_weight[id(read)], index))
            rejected.append(_rejection(read, "characters outside the plate frame ignored; read lengths conflict"))
            continue
        room = MAX_PLATE_SLOTS - len(columns)
        prepend = min(max(-lowest, 0), max(room, 0))
        if prepend:
            columns[:0] = [[] for _ in range(prepend)]
        for index, target in targets.items():
            target += prepend
            if target < 0 or target >= MAX_PLATE_SLOTS:
                continue
            while target >= len(columns):
                columns.append([])
            columns[target].append((read, read.raw_text[index], read.char_confidences[index],
                                    read.char_confidences[index] * frame_weight[id(read)], index))

    slots: list[FusedSlot] = []
    for position, column in enumerate(columns):
        tally: dict[str, float] = defaultdict(float)
        confidences: dict[str, list[float]] = defaultdict(list)
        source_votes: dict[str, int] = defaultdict(int)
        votes: list[SlotVote] = []
        withheld_votes = 0
        for read, char, conf, weight, index in column:
            if char == UNKNOWN:
                withheld_votes += index in read.withheld
                continue
            supported = read.source_supported_at(index) and not read.derived
            tally[char] += weight
            for alternative, probability in read.alternatives_at(index):
                tally[alternative] += probability * frame_weight[id(read)]
            votes.append(SlotVote(read.frame_idx, read.timestamp_sec, char, conf, read.source, supported,
                                  read.alternatives_at(index), read.variants_at(index), read.crop, read.crop_sha256,
                                  read.ocr_engine))
            if not read.derived:
                confidences[char].append(conf)
                source_votes[char] += supported
        total = sum(tally.values())
        observed = sum(len(items) for items in confidences.values())
        if total <= 0 or observed == 0:
            reason = "withheld: plate script cannot be read by the OCR alphabet" if withheld_votes \
                else "not visible in any usable frame"
            slots.append(FusedSlot(position, UNKNOWN, 0.0, [], 0, 0, votes, reason, 0))
            if withheld_votes:
                slots[-1].observed_frames = -withheld_votes  # Kept in place, then normalised below.
            continue
        ranked = sorted(((char, value / total) for char, value in tally.items()), key=lambda x: (-x[1], x[0]))
        winner, posterior = ranked[0]
        support = len(confidences[winner])
        miss = 1.0
        for conf in confidences[winner]:
            miss *= 1.0 - conf
        fused = posterior * (1.0 - miss)
        reason: str | None = None
        if trusted_columns is not None and id(column) not in trusted_columns:
            reason = "frames disagree about plate length, so this position is not reliable"
        elif support == 0:
            reason = "best reading appears only in a derived multi-frame view"
        elif source_votes[winner] == 0:
            reason = "best reading appears only after image processing, not in source pixels"
        elif len(ranked) > 1 and ranked[1][1] >= CONFLICT_RUNNER_UP \
                and (fused < tau or len(confidences.get(ranked[1][0], [])) >= MIN_CONFLICT_FRAMES):
            reason = f"frames disagree between {winner} and {ranked[1][0]}"
        elif observed >= 2 and support < MIN_FRAME_AGREEMENT * observed - 1e-9:
            reason = f"only {support} of {observed} frames agree on {winner}"
        elif fused < tau:
            reason = f"fused confidence {fused:.2f} is below {tau:.2f}"
        elif support < 2 and max(confidences[winner]) < single_min:
            reason = f"seen in one frame at {max(confidences[winner]):.2f}, below {single_min:.2f}"
        if reason is None:
            slots.append(FusedSlot(position, winner, fused, ranked[1:3], support, observed, votes, None,
                                   source_votes[winner]))
        else:
            slots.append(FusedSlot(position, UNKNOWN, fused, ranked[:2], support, observed, votes, reason,
                                   source_votes[winner]))

    # A position seen by only a few frames next to well-observed positions is usually an OCR
    # insertion or a plate border. Removing it keeps one bad frame from shifting the whole plate.
    if len(slots) > 1:
        peak = max(slot.observed_frames for slot in slots)
        keep = [i for i, slot in enumerate(slots)
                if not 0 < slot.observed_frames < MIN_SLOT_OBSERVATION_SHARE * peak]
        if keep and len(keep) < len(slots):
            removed = [i for i in range(len(slots)) if i not in keep]
            for index in removed:
                for read, char, _, _, _ in columns[index]:
                    if char != UNKNOWN:
                        rejected.append(_rejection(read, f"character {char} ignored: position seen in too few frames"))
            slots = [slots[i] for i in keep]
            columns = [columns[i] for i in keep]

    while slots and slots[0].observed_frames == 0:
        slots.pop(0)
        columns.pop(0)
    while slots and slots[-1].observed_frames == 0:
        slots.pop()
        columns.pop()
    for index, slot in enumerate(slots):
        slot.position = index
        slot.observed_frames = max(slot.observed_frames, 0)

    by_read: dict[int, dict] = {}
    for position, column in enumerate(columns):
        for read, char, conf, _, _ in column:
            row = by_read.setdefault(id(read), {
                "frame_idx": read.frame_idx,
                "timestamp_sec": round(read.timestamp_sec, 3),
                "raw_text": read.raw_text,
                "source": read.source,
                "ocr_engine": read.ocr_engine,
                "crop": read.crop,
                "crop_sha256": read.crop_sha256,
                "derived": read.derived,
                "sharpness": round(read.sharpness_score, 2),
                "cells": [{"char": UNKNOWN, "confidence": 0.0} for _ in columns],
            })
            row["cells"][position] = {"char": char, "confidence": round(conf, 4)}
    matrix = sorted(by_read.values(), key=lambda row: (row["derived"], row["timestamp_sec"], row["frame_idx"]))
    return FusedPlate("".join(s.char for s in slots), slots, matrix, used, len(rejected), rejected)
