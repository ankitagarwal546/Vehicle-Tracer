"""100-case matcher benchmark: 80 degraded true matches and 20 out-of-registry vehicles.

This tests matcher behaviour on simulated OCR evidence. It does not measure OCR or CV accuracy,
and its promoted-precision figure is not a calibrated real-world probability.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.seed_registry import SERIES_LETTERS, build_registry  # noqa: E402
from app.engine.confusion_matrices import COLOURS, OCR_CONFUSABLE  # noqa: E402
from app.engine.matcher import RegistryIndex, match  # noqa: E402
from app.engine.schemas import (  # noqa: E402
    CharCandidate,
    LabelScore,
    PlateEvidence,
    QueryEvidence,
    RegistryRecord,
    SlotEvidence,
)

CONFUSABLE_MAP: dict[str, list[str]] = {}
for left, right in sorted(OCR_CONFUSABLE):
    CONFUSABLE_MAP.setdefault(left, []).append(right)
COLOUR_SHIFT = {"white": "silver", "silver": "grey", "grey": "silver", "black": "grey", "red": "maroon",
                "maroon": "red", "blue": "black", "beige": "white", "brown": "maroon", "orange": "red",
                "yellow": "orange", "green": "grey"}
ALPHANUM = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"


def degrade_plate(plate: str, rng: random.Random) -> PlateEvidence:
    severity = rng.choices(["light", "moderate", "heavy", "edge"], weights=[30, 35, 20, 15])[0]
    p_unknown = {"light": 0.08, "moderate": 0.25, "heavy": 0.45, "edge": 0.05}[severity]
    p_confuse = {"light": 0.05, "moderate": 0.12, "heavy": 0.15, "edge": 0.08}[severity]
    slots: list[SlotEvidence] = []
    for char in plate:
        roll = rng.random()
        if roll < p_unknown:
            slots.append(SlotEvidence())
        elif roll < p_unknown + p_confuse and char in CONFUSABLE_MAP:
            wrong = rng.choice(CONFUSABLE_MAP[char])
            confidence = rng.uniform(0.56, 0.84)
            candidates = [CharCandidate(char=char, probability=rng.uniform(0.2, 0.4))] if rng.random() < 0.6 else []
            slots.append(SlotEvidence(char=wrong, confidence=confidence, candidates=candidates))
        else:
            slots.append(SlotEvidence(char=char, confidence=rng.uniform(0.62, 0.98)))
    if severity == "edge":
        keep = rng.randint(4, 6)
        if rng.random() < 0.5:
            return PlateEvidence(slots=slots[-keep:], anchor="floating")
        return PlateEvidence(slots=slots[:keep], anchor="floating")
    return PlateEvidence(slots=slots, anchor="full")


def attributes(record: dict, rng: random.Random, plate: PlateEvidence) -> QueryEvidence:
    colour = COLOUR_SHIFT[record["colour"]] if rng.random() < 0.3 else record["colour"]
    secondary = rng.choice([c for c in COLOURS if c != colour])
    body = record["body_type"]
    return QueryEvidence(
        plate=plate,
        colours=[LabelScore(label=colour, confidence=rng.uniform(0.5, 0.8)),
                 LabelScore(label=secondary, confidence=rng.uniform(0.05, 0.2))],
        body_type=body, body_confidence=rng.uniform(0.45, 0.8),
    )


def out_of_registry_plate(known: set[str], rng: random.Random) -> str:
    while True:
        state = rng.choice(["PB", "OD", "KL", "AP", "TS", "AS", "BR", "JH"])
        plate = f"{state}{rng.randint(1, 99):02d}{''.join(rng.choices(SERIES_LETTERS, k=2))}{rng.randint(1, 9999):04d}"
        if plate not in known:
            return plate


def near_miss_plate(source: str, known: set[str], rng: random.Random) -> str:
    """Change four non-confusable slots of a real plate, keeping most of its shape."""
    while True:
        chars = list(source)
        for index in rng.sample(range(len(chars)), 4):
            pool = [c for c in ALPHANUM if c != chars[index] and (c, chars[index]) not in OCR_CONFUSABLE
                    and c.isdigit() == chars[index].isdigit()]
            chars[index] = rng.choice(pool)
        plate = "".join(chars)
        if plate not in known:
            return plate


def evaluate(seed: int, size: int = 5000) -> dict:
    rng = random.Random(seed)
    rows = build_registry(size)
    registry = [RegistryRecord(id=i, **row) for i, row in enumerate(rows, 1)]
    known = {row["plate"] for row in rows}
    index = RegistryIndex(registry)
    top1 = top5 = accepted = accepted_correct = 0
    reciprocal = 0.0
    tp_no_match = fp_no_match = fn_no_match = 0
    elapsed: list[float] = []

    for source in rng.sample(rows, 80):
        query = attributes(source, rng, degrade_plate(source["plate"], rng))
        result = match(query, index)
        elapsed.append(result.elapsed_ms)
        ranked = [c.vehicle.plate for c in (result.candidates + result.rejected_candidates)]
        if result.status == "NO_CONFIDENT_MATCH":
            fp_no_match += 1
        else:
            accepted += 1
            accepted_correct += result.candidates[0].vehicle.plate == source["plate"]
        if ranked and ranked[0] == source["plate"]:
            top1 += 1
        if source["plate"] in ranked[:5]:
            top5 += 1
            reciprocal += 1 / (ranked.index(source["plate"]) + 1)

    for position in range(20):
        source = rng.choice(rows)
        plate = near_miss_plate(source["plate"], known, rng) if position % 2 else out_of_registry_plate(known, rng)
        evidence = PlateEvidence(slots=[
            SlotEvidence() if rng.random() < 0.1 else SlotEvidence(char=c, confidence=rng.uniform(0.82, 0.98))
            for c in plate
        ], anchor="full")
        result = match(attributes(source, rng, evidence), index)
        elapsed.append(result.elapsed_ms)
        if result.status == "NO_CONFIDENT_MATCH":
            tp_no_match += 1
        else:
            fn_no_match += 1
            accepted += 1

    precision = tp_no_match / max(tp_no_match + fp_no_match, 1)
    recall = tp_no_match / max(tp_no_match + fn_no_match, 1)
    return {
        "seed": seed, "registry_size": len(rows), "cases": 100, "true_match_cases": 80, "no_match_cases": 20,
        "top1_rank_accuracy": round(top1 / 80, 4), "top5_recall": round(top5 / 80, 4),
        "mrr": round(reciprocal / 80, 4),
        "promoted_results": accepted, "promoted_correct": accepted_correct,
        "promoted_precision": round(accepted_correct / max(accepted, 1), 4),
        "true_matches_promoted": round((80 - fp_no_match) / 80, 4),
        "no_match_recall": round(recall, 4), "no_match_precision": round(precision, 4),
        "true_matches_withheld": fp_no_match,
        "mean_match_ms": round(sum(elapsed) / len(elapsed), 2), "max_match_ms": round(max(elapsed), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--registry-size", type=int, default=5000)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.seed, args.registry_size), indent=2))


if __name__ == "__main__":
    main()
