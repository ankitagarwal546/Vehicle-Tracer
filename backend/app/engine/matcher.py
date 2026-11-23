"""Explainable plate-first vehicle matcher.

Every number in a result can be traced to a formula in this module:

    S_plate = clamp(sum(slot contributions) / sum(known slot confidences)) * gamma
    gamma   = known_chars / expected_plate_length
    score   = 100 * sum(weight_k * S_k) * veto

``score`` is an uncalibrated ranking score. It is not a probability of identity.

Colour, body type and make/model only support a plate-based match. A vehicle can reach
``CONFIDENT_SHORTLIST`` only when plate evidence alone clears every gate in ``THRESHOLDS``.
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable
from itertools import combinations
from math import ceil

import numpy as np

from .confusion_matrices import (
    body_similarity,
    colour_similarity,
    expected_char_classes,
    PLATE_FORMAT_NAMES,
    format_accepts,
    is_confusable,
    normalise_body,
    plate_family,
)
from .schemas import (
    AttributeSuggestions,
    Candidate,
    MatchResult,
    PlateEvidence,
    QueryEvidence,
    RegistryCoverage,
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
DROPPED_SLOT_PENALTY = 0.05
MAX_DROPPED_SLOTS = 2
MIN_SLOTS_FOR_GAPS = 6

WEIGHTS = {
    "high_readability": {"plate": 0.62, "body_type": 0.15, "colour": 0.13, "make_model": 0.10},
    "partial_plate": {"plate": 0.48, "body_type": 0.22, "colour": 0.18, "make_model": 0.12},
    "severe_occlusion": {"plate": 0.20, "body_type": 0.35, "colour": 0.27, "make_model": 0.18},
}
SEVERE_SCORE_CAP = 65.0
VETO_BODY_CONFIDENCE = 0.85
VETO_BODY_SIMILARITY = 0.10
VETO_MULTIPLIER = 0.25
MIN_BODY_COMPATIBILITY = 0.30
TOP_K = 5
SUGGESTION_LIMIT = 5
MIN_SUGGESTION_SIMILARITY = 0.80

# Explicit promotion gates. Each one is reported to the investigator when it fails.
THRESHOLDS: dict[str, float] = {
    "min_readable_chars": 5,
    "min_supporting_chars": 5,
    "min_exact_chars": 4,
    "min_plate_agreement": 0.70,
    "max_hard_contradictions": 1,
    "max_contradiction_share": 0.15,
    "min_match_score": 45.0,
    "min_score_gap": 5.0,
    "min_plate_gap": 0.02,
}
MIN_PARTIAL_LIST_CHARS = 3


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
    known = [index for index, slot in enumerate(plate.slots) if slot.char != "?"]
    if not known:
        return [0]
    # Unknown edge slots carry no position evidence, so only the readable span must fit.
    return list(range(-known[0], registry_len - known[-1]))


def _layouts(plate: PlateEvidence, length: int) -> list[tuple[dict[int, int], float]]:
    """Return ``(registry position -> slot index, penalty)`` candidates.

    OCR can silently drop a covered character, shifting everything after it. A short read may
    therefore be compared with one or two *unknown* slots inserted. Nothing is filled in.
    """
    count = len(plate.slots)
    layouts: list[tuple[dict[int, int], float]] = []
    for offset in _offsets(plate, length):
        penalty = SHIFT_PENALTY if offset and plate.anchor == "full" else 0.0
        layouts.append(({index + offset: index for index in range(count)}, penalty))
    missing = length - count
    if plate.anchor in {"full", "floating"} and 1 <= missing <= MAX_DROPPED_SLOTS and count >= MIN_SLOTS_FOR_GAPS:
        for gaps in combinations(range(1, length - 1), missing):
            remaining = iter(range(count))
            mapping = {position: next(remaining) for position in range(length) if position not in gaps}
            layouts.append((mapping, DROPPED_SLOT_PENALTY * missing))
    return layouts


def _align_plate(plate: PlateEvidence, registry_plate: str) -> tuple[float, float, dict[int, int]]:
    """Return ``(quality, gamma, registry position -> slot index)`` for the best alignment."""
    known_slots = {index: slot for index, slot in enumerate(plate.slots) if slot.char != "?"}
    if not known_slots:
        return 0.0, 0.0, {}
    length = len(registry_plate)
    classes = expected_char_classes(registry_plate)
    total_conf = sum(slot.confidence for slot in known_slots.values()) or 1.0
    gamma = min(len(known_slots) / max(length, 1), 1.0)
    best_quality, best_mapping = float("-inf"), {}
    for mapping, penalty in _layouts(plate, length):
        total = 0.0
        placed: set[int] = set()
        for position, index in mapping.items():
            if index not in known_slots:
                continue
            placed.add(index)
            if 0 <= position < length:
                total += _score_slot(known_slots[index], registry_plate[position], classes[position])[1]
            else:
                total += SOFT_MISMATCH_PENALTY * known_slots[index].confidence
        quality = total / total_conf - penalty
        if quality > best_quality:
            best_quality, best_mapping = quality, mapping
    return max(0.0, min(1.0, best_quality)), gamma, best_mapping


def score_plate(plate: PlateEvidence, registry_plate: str) -> tuple[float, float, float, int, int, list[SlotDiff]]:
    """Return ``(S_plate, quality, gamma, offset, hard_mismatches, slot_diff)``."""
    if plate.known_count == 0:
        diff = [
            SlotDiff(position=i, query="?", registry=ch, kind="unobserved", confidence=0.0, contribution=0.0)
            for i, ch in enumerate(registry_plate)
        ]
        return 0.0, 0.0, 0.0, 0, 0, diff

    classes = expected_char_classes(registry_plate)
    slots = plate.slots
    quality, gamma, mapping = _align_plate(plate, registry_plate)
    offset = next((position - index for position, index in sorted(mapping.items())), 0)
    diff: list[SlotDiff] = []
    hard = 0
    for position, registry_char in enumerate(registry_plate):
        index = mapping.get(position)
        slot = slots[index] if index is not None else None
        if slot is None:
            diff.append(SlotDiff(position=position, query="?", registry=registry_char, kind="unobserved",
                                 confidence=0.0, contribution=0.0))
            continue
        kind, value = _score_slot(slot, registry_char, classes[position])
        hard += kind == "hard_mismatch"
        diff.append(SlotDiff(position=position, query=slot.char, registry=registry_char, kind=kind,
                             confidence=round(slot.confidence, 4), contribution=round(value, 4)))
    return quality * gamma, quality, gamma, offset, hard, diff


def score_colour(query: QueryEvidence, colour: str) -> float | None:
    total = sum(c.confidence for c in query.colours)
    if total <= 0:
        return None
    return sum(c.confidence * colour_similarity(c.label, colour) for c in query.colours) / total


def score_body(query: QueryEvidence, body_type: str) -> float | None:
    if not query.body_type or query.body_confidence <= 0:
        return None
    return body_similarity(query.body_type, body_type)


def score_make_model(query: QueryEvidence, make: str, model: str) -> float | None:
    known = [m for m in query.make_models if m.make.lower() != "unknown" and m.confidence > 0]
    if not known:
        return None
    total = sum(m.confidence for m in known)
    score = 0.0
    for item in known:
        same_make = item.make.lower() == make.lower()
        same_model = item.model.lower() == model.lower()
        score += item.confidence * (1.0 if same_make and same_model else 0.5 if same_make else 0.15)
    return score / total


def _resolved_weights(regime: str, active: dict[str, bool]) -> dict[str, float]:
    base = WEIGHTS[regime]
    enabled = {key: value for key, value in base.items() if key == "plate" or active[key]}
    total = sum(enabled.values())
    return {key: round(enabled.get(key, 0.0) / total, 4) for key in base}


class RegistryIndex:
    """Column-oriented registry so a re-rank stays interactive on large registries."""

    def __init__(self, records: Iterable[RegistryRecord]) -> None:
        self.records = list(records)
        self._fingerprint: str | None = None
        groups: dict[int, list[int]] = {}
        for index, record in enumerate(self.records):
            groups.setdefault(len(record.plate), []).append(index)
        self.groups = {
            length: (
                np.asarray(indices, dtype=np.int32),
                np.frombuffer("".join(self.records[i].plate for i in indices).encode("ascii"), dtype=np.uint8)
                .reshape(len(indices), length),
            )
            for length, indices in groups.items() if length > 0
        }
        self.colours, self.colour_codes = self._encode(r.colour for r in self.records)
        self.bodies, self.body_codes = self._encode(r.body_type for r in self.records)
        self.make_models, self.make_model_codes = self._encode((r.make, r.model) for r in self.records)
        self.families, self.family_codes = self._encode(plate_family(r.plate) for r in self.records)

    def eligible(self, plate_format: str) -> np.ndarray:
        """Registry rows whose plate format can be compared with this camera's plates."""
        if not self.records:
            return np.zeros(0, dtype=bool)
        return np.asarray([format_accepts(plate_format, family) for family in self.families],
                          dtype=bool)[self.family_codes]

    def compatible_count(self, plate_format: str) -> int:
        return int(self.eligible(plate_format).sum())

    def family_counts(self) -> dict[str, int]:
        if not self.records:
            return {}
        counts = np.bincount(self.family_codes, minlength=len(self.families))
        return {family: int(count) for family, count in zip(self.families, counts)}

    def fingerprint(self) -> str:
        """Identify registry content, so a case can tell when it was scored on an older registry."""
        if self._fingerprint is None:
            digest = hashlib.sha256()
            for row in sorted(f"{r.plate}|{r.status}|{r.source}" for r in self.records):
                digest.update(row.encode("ascii", "replace"))
            self._fingerprint = digest.hexdigest()[:16]
        return self._fingerprint

    @staticmethod
    def _encode(values: Iterable) -> tuple[list, np.ndarray]:
        lookup: dict = {}
        codes = [lookup.setdefault(value, len(lookup)) for value in values]
        return list(lookup), np.asarray(codes, dtype=np.int32)


def _plate_scores(index: RegistryIndex, plate: PlateEvidence) -> np.ndarray:
    scores = np.zeros(len(index.records), dtype=np.float64)
    known_slots = [(i, slot) for i, slot in enumerate(plate.slots) if slot.char != "?"]
    if not known_slots:
        return scores
    total_conf = sum(slot.confidence for _, slot in known_slots) or 1.0
    tables: list[np.ndarray] = []
    for _, slot in known_slots:
        table = np.full(128, SOFT_MISMATCH_PENALTY * slot.confidence, dtype=np.float64)
        for code in (*range(48, 58), *range(65, 91)):
            char = chr(code)
            table[code] = _score_slot(slot, char, "9" if char.isdigit() else "A")[1]
        tables.append(table)
    table_by_slot = {slot_index: table for (slot_index, _), table in zip(known_slots, tables)}
    slot_by_index = dict(known_slots)
    for length, (indices, chars) in index.groups.items():
        best = np.full(len(indices), -np.inf)
        for mapping, penalty in _layouts(plate, length):
            total = np.zeros(len(indices), dtype=np.float64)
            for position, slot_index in mapping.items():
                if slot_index not in table_by_slot:
                    continue
                if 0 <= position < length:
                    total += table_by_slot[slot_index][chars[:, position]]
                else:
                    total += SOFT_MISMATCH_PENALTY * slot_by_index[slot_index].confidence
            best = np.maximum(best, total / total_conf - penalty)
        scores[indices] = np.clip(best, 0.0, 1.0) * min(len(known_slots) / length, 1.0)
    return scores


def _column(values: list, codes: np.ndarray, scorer) -> np.ndarray | None:
    computed = [scorer(value) for value in values]
    if not computed or computed[0] is None:
        return None
    return np.asarray(computed, dtype=np.float64)[codes]


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
        reasons.append(f"Supporting: observed colour {query.colours[0].label} vs registry {vehicle.colour} "
                       f"({sub.colour:.2f}).")
    if sub.body_type is not None:
        reasons.append(f"Supporting: observed body {str(query.body_type).replace('_', ' ')} vs registry "
                       f"{vehicle.body_type.replace('_', ' ')} ({sub.body_type:.2f}).")
    if sub.make_model is not None and query.make_models:
        top = query.make_models[0]
        reasons.append(f"Supporting: estimated {top.make} {top.model} vs registry {vehicle.make} {vehicle.model} "
                       f"({sub.make_model:.2f}).")
    reasons.extend(candidate.contradictions)
    return reasons


def _plate_blockers(candidate: Candidate, known: int) -> list[str]:
    """Return every plate gate this candidate fails. Attributes cannot clear any of them."""
    t = THRESHOLDS
    blockers: list[str] = []
    supporting = candidate.exact_chars + candidate.confusable_chars
    if known < t["min_readable_chars"]:
        blockers.append(f"Only {known} readable plate character(s); {t['min_readable_chars']:.0f} are required.")
    if supporting < t["min_supporting_chars"]:
        blockers.append(f"Only {supporting} character(s) agree with this plate; "
                        f"{t['min_supporting_chars']:.0f} are required.")
    if candidate.exact_chars < t["min_exact_chars"]:
        blockers.append(f"Only {candidate.exact_chars} exact character match(es); "
                        f"{t['min_exact_chars']:.0f} are required.")
    if candidate.sub_scores.plate_quality < t["min_plate_agreement"]:
        blockers.append(f"Plate agreement {candidate.sub_scores.plate_quality:.2f} is below "
                        f"{t['min_plate_agreement']:.2f}.")
    share = candidate.hard_mismatches / known if known else 0.0
    if candidate.hard_mismatches > t["max_hard_contradictions"] or share > t["max_contradiction_share"]:
        blockers.append(f"{candidate.hard_mismatches} high-confidence character contradiction(s) with this plate.")
    if candidate.vetoed:
        blockers.append("Observed body type fundamentally conflicts with this registry entry.")
    return blockers


def _build_candidate(query: QueryEvidence, record: RegistryRecord, regime: str, weights: dict[str, float],
                     colour: float | None, body: float | None, make_model: float | None) -> Candidate:
    plate_score, quality, gamma, offset, hard, diff = score_plate(query.plate, record.plate)
    signals = {"plate": plate_score, "colour": colour, "body_type": body, "make_model": make_model}
    raw = sum(weights[key] * (value or 0.0) for key, value in signals.items())
    contradictions: list[str] = []
    vetoed = body is not None and query.body_confidence > VETO_BODY_CONFIDENCE and body <= VETO_BODY_SIMILARITY
    if vetoed:
        raw *= VETO_MULTIPLIER
        contradictions.append(
            f"Hard veto: {str(query.body_type).replace('_', ' ')} observed at {query.body_confidence:.0%} conflicts "
            f"with registry {record.body_type.replace('_', ' ')}; score multiplied by {VETO_MULTIPLIER}."
        )
    cap = SEVERE_SCORE_CAP if regime == "severe_occlusion" else 100.0
    return Candidate(
        vehicle=record,
        score=round(min(raw * 100, cap), 2),
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
        exact_chars=sum(d.kind == "exact" for d in diff),
        confusable_chars=sum(d.kind == "confusable" for d in diff),
        hard_mismatches=hard,
        vetoed=vetoed,
        contradictions=contradictions,
        reasons=[],
    )


def _suggestions(index: RegistryIndex, query: QueryEvidence, colour: np.ndarray | None,
                 body: np.ndarray | None, eligible: np.ndarray) -> AttributeSuggestions:
    """Unranked, alphabetical appearance matches. Owner details are withheld."""
    if colour is None and body is None:
        return AttributeSuggestions()
    mask = eligible.copy()
    basis: list[str] = []
    if colour is not None:
        mask &= colour >= MIN_SUGGESTION_SIMILARITY
        basis.append(f"colour similar to {query.colours[0].label}")
    if body is not None:
        mask &= body >= MIN_SUGGESTION_SIMILARITY
        basis.append(f"body similar to {str(query.body_type).replace('_', ' ')}")
    matching = sorted((index.records[i] for i in np.flatnonzero(mask)), key=lambda r: r.plate)
    return AttributeSuggestions(similar_count=len(matching), basis=basis,
                                vehicles=[r.without_owner() for r in matching[:SUGGESTION_LIMIT]])


def match(
    query: QueryEvidence,
    registry: Iterable[RegistryRecord] | RegistryIndex,
    top_k: int = TOP_K,
) -> MatchResult:
    """Rank the registry against plate evidence and promote only what clears every gate."""
    started = time.perf_counter()
    index = registry if isinstance(registry, RegistryIndex) else RegistryIndex(registry)
    records = index.records
    known = query.plate.known_count
    regime = regime_for(known)
    query = query.model_copy(update={"body_type": normalise_body(query.body_type) if query.body_type else None})

    colour = _column(index.colours, index.colour_codes, lambda value: score_colour(query, value))
    body = _column(index.bodies, index.body_codes, lambda value: score_body(query, value))
    make_model = _column(index.make_models, index.make_model_codes,
                         lambda value: score_make_model(query, value[0], value[1]))
    weights = _resolved_weights(regime, {"colour": colour is not None, "body_type": body is not None,
                                         "make_model": make_model is not None})
    eligible = index.eligible(query.plate_format)
    plate_scores = _plate_scores(index, query.plate)
    plate_scores = np.where(eligible, plate_scores, 0.0)
    raw = weights["plate"] * plate_scores
    for key, column in (("colour", colour), ("body_type", body), ("make_model", make_model)):
        if column is not None:
            raw = raw + weights[key] * column
    if body is not None and query.body_confidence > VETO_BODY_CONFIDENCE:
        raw = np.where(body <= VETO_BODY_SIMILARITY, raw * VETO_MULTIPLIER, raw)
    cap = SEVERE_SCORE_CAP if regime == "severe_occlusion" else 100.0
    scores = np.minimum(np.round(raw * 100, 2), cap)

    # Plate evidence ranks first. Attributes only order vehicles whose plate evidence is tied.
    head: list[Candidate] = []
    if bool(eligible.any()):
        take = min(top_k + 1, int(eligible.sum()))
        rounded_plate = np.round(plate_scores, 4)
        floor = np.partition(rounded_plate[eligible], -take)[-take]
        pool = np.flatnonzero((rounded_plate >= floor) & eligible)
        ordered = sorted(pool.tolist(), key=lambda i: (-rounded_plate[i], -scores[i], records[i].plate))
        for i in ordered[:take]:
            head.append(_build_candidate(
                query, records[i], regime, weights,
                None if colour is None else float(colour[i]),
                None if body is None else float(body[i]),
                None if make_model is None else float(make_model[i]),
            ))
    for rank, candidate in enumerate(head, start=1):
        candidate.rank = rank
        candidate.blocking_reasons = _plate_blockers(candidate, known)
        candidate.plate_supported = not candidate.blocking_reasons
        candidate.reasons = _reasons(candidate, query)

    shortlist = head[:top_k]
    t = THRESHOLDS
    diagnostics: list[str] = []
    codes: list[str] = []
    outcome = "NO_REGISTRY_MATCH"
    top = shortlist[0] if shortlist else None

    compatible = int(eligible.sum())
    format_name = PLATE_FORMAT_NAMES.get(query.plate_format, query.plate_format.replace("_", " "))
    no_coverage_note = (f"The active registry has 0 compatible {format_name} records out of {len(records):,}, "
                        "so no registry comparison was possible.")
    if known == 0:
        outcome = "UNREADABLE_PLATE"
        codes.append("NO_PLATE_EVIDENCE")
        diagnostics.append("No plate character could be read, so no registry vehicle can be identified. "
                           "Colour, body type and model alone never identify a vehicle.")
        if compatible == 0:
            diagnostics.append(no_coverage_note)
    elif known < t["min_readable_chars"]:
        outcome = "INSUFFICIENT_PLATE"
        codes.append("TOO_FEW_CHARACTERS")
        diagnostics.append(f"Only {known} plate character(s) are readable; at least "
                           f"{t['min_readable_chars']:.0f} are required before a vehicle can be shortlisted.")
        if compatible == 0:
            diagnostics.append(no_coverage_note)
    elif top is None:
        outcome = "NO_REGISTRY_COVERAGE"
        codes.append("NO_REGISTRY_COVERAGE")
        diagnostics.append(f"{no_coverage_note} The plate read is kept as OCR evidence. This is not a no-match result.")
    else:
        if query.body_type and query.body_confidence > 0 and body is not None \
                and bool(np.all(body < MIN_BODY_COMPATIBILITY)):
            codes.append("BODY_INCOMPATIBLE")
            diagnostics.append(f"No registry vehicle is body-compatible with {query.body_type.replace('_', ' ')}.")
        if top.blocking_reasons:
            codes.append("PLATE_NOT_SUPPORTED")
            diagnostics.append("Closest registry plate does not qualify: " + " ".join(top.blocking_reasons))
        if top.score < t["min_match_score"]:
            codes.append("LOW_MATCH_SCORE")
            diagnostics.append(f"Top match score {top.score:.1f} is below the {t['min_match_score']:.0f} threshold.")
        if not codes and len(head) > 1:
            rival = head[1]
            score_gap = top.score - rival.score
            plate_gap = top.sub_scores.plate - rival.sub_scores.plate
            if score_gap < t["min_score_gap"] or plate_gap < t["min_plate_gap"]:
                outcome = "AMBIGUOUS"
                codes.append("AMBIGUOUS_CANDIDATES")
                diagnostics.append(
                    f"{rival.vehicle.plate} is too close to {top.vehicle.plate} (score gap {score_gap:.1f}, "
                    f"plate gap {plate_gap:.2f}; required {t['min_score_gap']:.0f} and {t['min_plate_gap']:.2f})."
                )

    base = {
        "regime": regime,
        "query_plate": query.plate.text,
        "known_chars": known,
        "registry_size": len(records),
        "reason_codes": codes,
        "thresholds": dict(t),
        "registry_coverage": RegistryCoverage(plate_format=query.plate_format, compatible_records=compatible,
                                              total_records=len(records), searched=compatible > 0 and known >= t["min_readable_chars"]),
    }
    if codes or top is None:
        # Show only registry plates that genuinely share characters with the read.
        required = max(MIN_PARTIAL_LIST_CHARS, ceil(known / 2))
        keep = [] if known < MIN_PARTIAL_LIST_CHARS else [
            c.model_copy(update={"vehicle": c.vehicle.without_owner(), "rank": rank})
            for rank, c in enumerate((c for c in shortlist if c.exact_chars >= required), start=1)
        ]
        if outcome == "NO_REGISTRY_MATCH" and not keep and known >= t["min_readable_chars"] and top is not None:
            diagnostics = [f"No registry plate shares at least {required} characters with this read."]
            codes = ["NO_SIMILAR_PLATE"]
            base["reason_codes"] = codes
        suggestions = _suggestions(index, query, colour, body, eligible) if known < t["min_readable_chars"] \
            else AttributeSuggestions()
        return MatchResult(status="NO_CONFIDENT_MATCH", outcome=outcome, candidates=[], rejected_candidates=keep,
                           attribute_suggestions=suggestions, diagnostics=diagnostics,
                           elapsed_ms=round((time.perf_counter() - started) * 1000, 2), **base)

    accepted = [c for c in shortlist if c.plate_supported and c.score >= t["min_match_score"]]
    rejected = [c.model_copy(update={"vehicle": c.vehicle.without_owner()})
                for c in shortlist if c not in accepted]
    diagnostics.append(
        f"{top.vehicle.plate} cleared every plate gate: {top.exact_chars} exact and {top.confusable_chars} "
        f"confusable character(s), {top.hard_mismatches} contradiction(s), match score {top.score:.1f}."
    )
    return MatchResult(status="CONFIDENT_SHORTLIST", outcome="PLATE_CANDIDATE", candidates=accepted,
                       rejected_candidates=rejected, diagnostics=diagnostics,
                       elapsed_ms=round((time.perf_counter() - started) * 1000, 2), **base)
