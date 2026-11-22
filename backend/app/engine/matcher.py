"""Explainable probabilistic vehicle matcher.

Every number in a result can be traced to a formula in this module:

    S_plate = clamp(sum(slot contributions) / sum(known slot confidences)) * gamma
    gamma   = known_chars / expected_plate_length
    score   = 100 * sum(weight_k * S_k) * veto
    conf    = min(cap, score * (0.90 + 0.10 * min(1, margin / 10)))

Signals with no evidence are removed and their weight is redistributed proportionally.
"""
from __future__ import annotations

import time
from collections.abc import Iterable

from .confusion_matrices import (
    body_similarity,
    colour_similarity,
    expected_char_classes,
    is_confusable,
    normalise_body,
)
from .schemas import (
    Candidate,
    MatchResult,
    PlateEvidence,
    QueryEvidence,
    RegistryRecord,
    SlotDiff,
    SlotEvidence,
    SubScores,
)

EXACT_REWARD = 1.0
CONFUSABLE_REWARD = 0.65
RUNNER_UP_BONUS = 0.20
SYNTAX_BONUS = 0.05
HARD_MISMATCH_PENALTY = -1.2
SOFT_MISMATCH_PENALTY = -0.40
HARD_CONFIDENCE = 0.80
SHIFT_PENALTY = 0.05

WEIGHTS = {
    "high_readability": {"plate": 0.62, "body_type": 0.15, "colour": 0.13, "make_model": 0.10},
    "partial_plate": {"plate": 0.48, "body_type": 0.22, "colour": 0.18, "make_model": 0.12},
    "severe_occlusion": {"plate": 0.20, "body_type": 0.35, "colour": 0.27, "make_model": 0.18},
}
SEVERE_CONFIDENCE_CAP = 65.0
MIN_CONFIDENCE = 45.0
VETO_BODY_CONFIDENCE = 0.85
VETO_BODY_SIMILARITY = 0.10
VETO_MULTIPLIER = 0.25
MIN_BODY_COMPATIBILITY = 0.30
MIN_HIGH_CONF_CHARS_FOR_GATE = 5
MAX_HARD_MISMATCHES = 3
AMBIGUITY_BAND = 1.0
AMBIGUITY_COUNT = 6
TOP_K = 5


def regime_for(known_chars: int) -> str:
    if known_chars >= 6:
        return "high_readability"
    if known_chars >= 3:
        return "partial_plate"
    return "severe_occlusion"


def _candidate_probability(slot: SlotEvidence, char: str) -> float:
    return next((c.probability for c in slot.candidates if c.char == char), 0.0)


def _score_slot(slot: SlotEvidence, registry_char: str, expected_class: str) -> tuple[str, float]:
    if not slot.known:
        return "unknown", 0.0
    conf = slot.confidence
    if slot.char == registry_char:
        return "exact", EXACT_REWARD * conf
    runner_up = _candidate_probability(slot, registry_char)
    if is_confusable(slot.char, registry_char):
        value = CONFUSABLE_REWARD * conf + RUNNER_UP_BONUS * runner_up
        observed_class = "9" if slot.char.isdigit() else "A"
        if observed_class != expected_class:
            value += SYNTAX_BONUS * conf
        return "confusable", min(value, conf)
    if slot.locked or conf >= HARD_CONFIDENCE:
        return "hard_mismatch", HARD_MISMATCH_PENALTY * conf
    return "mismatch", SOFT_MISMATCH_PENALTY * conf + RUNNER_UP_BONUS * runner_up


def _offsets(plate: PlateEvidence, registry_len: int) -> list[int]:
    query_len = len(plate.slots)
    if plate.anchor == "prefix":
        return [0]
    if plate.anchor == "suffix":
        return [registry_len - query_len]
    if plate.anchor == "full":
        return [0] if query_len == registry_len else [0, registry_len - query_len]
    return list(range(min(0, registry_len - query_len), max(0, registry_len - query_len) + 1))


def score_plate(plate: PlateEvidence, registry_plate: str) -> tuple[float, float, float, int, int, list[SlotDiff]]:
    """Return ``(S_plate, quality, gamma, offset, hard_mismatches, slot_diff)``."""
    known = plate.known_count
    expected = max(len(registry_plate), 1)
    if known == 0:
        diff = [
            SlotDiff(position=i, query="?", registry=ch, kind="unobserved", confidence=0.0, contribution=0.0)
            for i, ch in enumerate(registry_plate)
        ]
        return 0.0, 0.0, 0.0, 0, 0, diff

    classes = expected_char_classes(registry_plate)
    slots = plate.slots
    total_conf = sum(slot.confidence for slot in slots if slot.known) or 1.0
    gamma = min(known / expected, 1.0)
    best: tuple[float, int] | None = None

    for offset in _offsets(plate, len(registry_plate)):
        total = 0.0
        for index, slot in enumerate(slots):
            position = index + offset
            if not slot.known:
                continue
            if 0 <= position < len(registry_plate):
                total += _score_slot(slot, registry_plate[position], classes[position])[1]
            else:
                total += SOFT_MISMATCH_PENALTY * slot.confidence
        quality = total / total_conf - (SHIFT_PENALTY if offset and plate.anchor == "full" else 0.0)
        if best is None or quality > best[0]:
            best = (quality, offset)

    assert best is not None
    quality, offset = best
    quality = max(0.0, min(1.0, quality))
    by_position = {index + offset: slot for index, slot in enumerate(slots)}
    diff: list[SlotDiff] = []
    hard = 0
    for position, registry_char in enumerate(registry_plate):
        slot = by_position.get(position)
        if slot is None:
            diff.append(SlotDiff(position=position, query="?", registry=registry_char, kind="unobserved",
                                 confidence=0.0, contribution=0.0))
            continue
        kind, value = _score_slot(slot, registry_char, classes[position])
        hard += kind == "hard_mismatch"
        diff.append(SlotDiff(position=position, query=slot.char, registry=registry_char, kind=kind,
                             confidence=round(slot.confidence, 4), contribution=round(value, 4)))
    return quality * gamma, quality, gamma, offset, hard, diff


def score_colour(query: QueryEvidence, record: RegistryRecord) -> float | None:
    total = sum(c.confidence for c in query.colours)
    if total <= 0:
        return None
    return sum(c.confidence * colour_similarity(c.label, record.colour) for c in query.colours) / total


def score_body(query: QueryEvidence, record: RegistryRecord) -> float | None:
    if not query.body_type or query.body_confidence <= 0:
        return None
    return body_similarity(query.body_type, record.body_type)


def score_make_model(query: QueryEvidence, record: RegistryRecord) -> float | None:
    known = [m for m in query.make_models if m.make.lower() != "unknown" and m.confidence > 0]
    if not known:
        return None
    total = sum(m.confidence for m in known)
    score = 0.0
    for item in known:
        same_make = item.make.lower() == record.make.lower()
        same_model = item.model.lower() == record.model.lower()
        score += item.confidence * (1.0 if same_make and same_model else 0.5 if same_make else 0.15)
    return score / total


def _resolved_weights(regime: str, signals: dict[str, float | None]) -> dict[str, float]:
    base = WEIGHTS[regime]
    active = {key: value for key, value in base.items() if key == "plate" or signals[key] is not None}
    total = sum(active.values())
    return {key: round(active.get(key, 0.0) / total, 4) for key in base}


def _reasons(candidate: Candidate, query: QueryEvidence) -> list[str]:
    counts: dict[str, list[int]] = {}
    for diff in candidate.slot_diff:
        counts.setdefault(diff.kind, []).append(diff.position + 1)
    reasons: list[str] = []
    labels = {
        "exact": "Exact character match at slot(s)",
        "confusable": "OCR-confusable match at slot(s)",
        "unknown": "Unreadable, scored neutral, at slot(s)",
        "unobserved": "Not visible in footage at slot(s)",
        "mismatch": "Low-confidence disagreement at slot(s)",
        "hard_mismatch": "High-confidence contradiction at slot(s)",
    }
    for kind in ("exact", "confusable", "unknown", "unobserved", "mismatch", "hard_mismatch"):
        if kind in counts:
            reasons.append(f"{labels[kind]} {', '.join(map(str, counts[kind]))}.")
    sub = candidate.sub_scores
    reasons.append(
        f"Plate evidence {sub.plate:.2f} = alignment quality {sub.plate_quality:.2f} x coverage {sub.coverage:.2f}."
    )
    vehicle = candidate.vehicle
    if sub.colour is not None and query.colours:
        reasons.append(f"Observed colour {query.colours[0].label} vs registry {vehicle.colour}: {sub.colour:.2f}.")
    if sub.body_type is not None:
        reasons.append(f"Observed body {query.body_type} vs registry {vehicle.body_type}: {sub.body_type:.2f}.")
    if sub.make_model is not None and query.make_models:
        top = query.make_models[0]
        reasons.append(
            f"Observed {top.make} {top.model} vs registry {vehicle.make} {vehicle.model}: {sub.make_model:.2f}."
        )
    reasons.extend(candidate.contradictions)
    return reasons


def _score_record(query: QueryEvidence, record: RegistryRecord, regime: str) -> Candidate:
    plate_score, quality, gamma, offset, hard, diff = score_plate(query.plate, record.plate)
    colour = score_colour(query, record)
    body = score_body(query, record)
    make_model = score_make_model(query, record)
    signals = {"plate": plate_score, "colour": colour, "body_type": body, "make_model": make_model}
    weights = _resolved_weights(regime, signals)
    raw = sum(weights[key] * (value or 0.0) for key, value in signals.items())

    contradictions: list[str] = []
    vetoed = False
    if body is not None and query.body_confidence > VETO_BODY_CONFIDENCE and body <= VETO_BODY_SIMILARITY:
        vetoed = True
        raw *= VETO_MULTIPLIER
        contradictions.append(
            f"Hard veto: {query.body_type} observed at {query.body_confidence:.0%} conflicts with "
            f"registry {record.body_type}; score multiplied by {VETO_MULTIPLIER}."
        )
    return Candidate(
        vehicle=record,
        score=round(raw * 100, 2),
        confidence=0.0,
        sub_scores=SubScores(
            plate=round(plate_score, 4),
            colour=None if colour is None else round(colour, 4),
            body_type=None if body is None else round(body, 4),
            make_model=None if make_model is None else round(make_model, 4),
            coverage=round(gamma, 4),
            plate_quality=round(quality, 4),
        ),
        weights=weights,
        slot_diff=diff,
        alignment_offset=offset,
        hard_mismatches=hard,
        vetoed=vetoed,
        contradictions=contradictions,
        reasons=[],
    )


def match(query: QueryEvidence, registry: Iterable[RegistryRecord], top_k: int = TOP_K) -> MatchResult:
    """Rank the registry against the evidence and apply the no-confident-match gate."""
    started = time.perf_counter()
    records = list(registry)
    known = query.plate.known_count
    regime = regime_for(known)
    query = query.model_copy(update={"body_type": normalise_body(query.body_type) if query.body_type else None})
    scored = sorted(
        (_score_record(query, record, regime) for record in records),
        key=lambda c: (-c.score, -c.sub_scores.plate, c.vehicle.plate),
    )

    cap = SEVERE_CONFIDENCE_CAP if regime == "severe_occlusion" else 100.0
    head = scored[: top_k + 1]
    for index, candidate in enumerate(head):
        best_other = head[1].score if index == 0 and len(head) > 1 else head[0].score
        margin = max(candidate.score - best_other, 0.0)
        candidate.confidence = round(min(cap, candidate.score * (0.90 + 0.10 * min(1.0, margin / 10.0))), 2)
    shortlist = head[:top_k]
    for rank, candidate in enumerate(shortlist, start=1):
        candidate.rank = rank
        candidate.reasons = _reasons(candidate, query)

    diagnostics: list[str] = []
    high_conf_known = sum(s.known and s.confidence >= HARD_CONFIDENCE for s in query.plate.slots)
    top = shortlist[0] if shortlist else None
    if top is None:
        diagnostics.append("Registry is empty.")
    else:
        if top.confidence < MIN_CONFIDENCE:
            diagnostics.append(f"Top candidate confidence {top.confidence:.1f}% is below {MIN_CONFIDENCE:.0f}%.")
        if high_conf_known >= MIN_HIGH_CONF_CHARS_FOR_GATE and top.hard_mismatches >= MAX_HARD_MISMATCHES:
            diagnostics.append(
                f"{high_conf_known} high-confidence characters were read, yet the top candidate has "
                f"{top.hard_mismatches} non-confusable contradictions."
            )
        if query.body_type and query.body_confidence > 0 and all(
            (c.sub_scores.body_type or 0.0) < MIN_BODY_COMPATIBILITY for c in scored
        ):
            diagnostics.append(f"No registry vehicle is body-compatible with {query.body_type}.")
        if regime == "severe_occlusion":
            tied = sum(top.score - c.score <= AMBIGUITY_BAND for c in scored)
            if tied >= AMBIGUITY_COUNT:
                diagnostics.append(
                    f"Only {known} plate character(s) readable and {tied} vehicles score within "
                    f"{AMBIGUITY_BAND:.0f} point of the leader, so the evidence cannot discriminate."
                )

    elapsed = (time.perf_counter() - started) * 1000
    base = {
        "regime": regime,
        "query_plate": query.plate.text,
        "known_chars": known,
        "registry_size": len(records),
        "elapsed_ms": round(elapsed, 2),
    }
    if diagnostics:
        return MatchResult(status="NO_CONFIDENT_MATCH", candidates=[], rejected_candidates=shortlist,
                           diagnostics=diagnostics, **base)
    rejected = [c for c in shortlist if c.confidence < MIN_CONFIDENCE or c.vetoed]
    accepted = [c for c in shortlist if c not in rejected]
    return MatchResult(status="CONFIDENT_SHORTLIST", candidates=accepted, rejected_candidates=rejected,
                       diagnostics=[f"Top candidate cleared all decision gates at {top.confidence:.1f}%."], **base)
