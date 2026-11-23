"""End-to-end evaluation on labelled synthetic video fixtures.

Each case is rendered to a video and processed by the real detector, tracker, OCR, fusion, matcher
and re-identification code. Results describe this synthetic fixture set only. They are not an
estimate of real-world CCTV accuracy, and thresholds must not be tuned against them.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_demo_clip import Scenario, render  # noqa: E402

from app.cv.plate_fusion import align  # noqa: E402
from app.cv.reid import TrackProfile, link_tracks, mean_embedding  # noqa: E402
from app.cv.video_processor import SamplingStats, probe_video, sample_frames  # noqa: E402
from app.db.seed_registry import SERIES_LETTERS, build_registry  # noqa: E402
from app.engine.matcher import RegistryIndex, match  # noqa: E402
from app.engine.schemas import RegistryRecord  # noqa: E402
from app.services.pipeline_orchestrator import _analyse_track, _stitch_tracks, build_query, models  # noqa: E402

PLATE_FORMAT = "india_rto"
EXPECT_NO_MATCH = {"ambiguous_partial", "unreadable", "out_of_registry"}
# Other recolourings of the sample photo look unnatural and the stock detector does not see a vehicle.
FIXTURE_COLOURS = {"blue", "red", "maroon", "white", "grey", "silver", "black"}
RANKABLE = {"true_clear", "true_partial", "true_moving_occlusion", "ambiguous_partial"}
EXPECT_PROMOTION = {"true_clear", "true_partial", "true_moving_occlusion"}


@dataclass
class Outcome:
    scenario: Scenario
    plate: str
    status: str
    outcome: str
    ranked: list[str]
    promoted: str | None
    wrong_chars: int
    emitted_chars: int
    hidden_emitted: int
    profile: TrackProfile | None


def character_errors(read: str, truth: str, hidden: set[int]) -> tuple[int, int, int]:
    """Count emitted characters that disagree with truth, using gap-aware alignment.

    OCR can drop a covered character, so a plain position-by-position comparison would count
    every correct character after the gap as wrong.
    """
    if not read:
        return 0, 0, 0
    placed = {index: position for position, index in align(truth, read)}
    wrong = emitted = on_hidden = 0
    for index, char in enumerate(read):
        if char == "?":
            continue
        emitted += 1
        position = placed.get(index)
        if position is None or truth[position] != char:
            wrong += 1
        if position in hidden:
            on_hidden += 1
    return wrong, emitted, on_hidden


def random_plate(rng: random.Random, known: set[str], state: str | None = None) -> str:
    while True:
        prefix = state or rng.choice(["PB", "OD", "KL", "AP", "TS", "AS", "BR", "JH"])
        plate = f"{prefix}{rng.randint(1, 99):02d}{''.join(rng.choices(SERIES_LETTERS, k=2))}{rng.randint(1, 9999):04d}"
        if plate not in known:
            return plate


def scenario(identifier: str, plate: str, colour: str, category: str, in_registry: bool, seed: int,
             seconds_override: float = 2.0, **extra) -> Scenario:
    return Scenario(id=identifier, file=f"synthetic_eval_{identifier}.mp4", camera=identifier, location="fixture",
                    plate=plate, colour=colour, category=category, in_registry=in_registry, seed=seed,
                    seconds=seconds_override, **extra)


def build_cases(seed: int) -> tuple[list[dict], list[Scenario], list[Scenario]]:
    """Return extra registry rows, single-sighting cases and cross-camera sightings."""
    rng = random.Random(seed)
    rows = build_registry(5000)
    known = {row["plate"] for row in rows}
    buses = [row for row in rows if row["body_type"] == "bus" and len(row["plate"]) == 10
             and row["plate"].isalnum() and row["colour"] in FIXTURE_COLOURS]
    rng.shuffle(buses)
    cursor = iter(buses)
    extra: list[dict] = []
    cases: list[Scenario] = []
    for i in range(15):
        row = next(cursor)
        cases.append(scenario(f"clear{i}", row["plate"], row["colour"], "true_clear", True, 1000 + i,
                              direction=rng.choice([-1, 1])))
    for i in range(15):
        row = next(cursor)
        hidden = rng.choice([[0, 1], [0, 1, 2], [7, 8, 9], [8, 9], [rng.randint(3, 7)]])
        cases.append(scenario(f"partial{i}", row["plate"], row["colour"], "true_partial", True, 1100 + i,
                              hidden=hidden, direction=rng.choice([-1, 1])))
    for i in range(6):
        row = next(cursor)
        cases.append(scenario(f"moving{i}", row["plate"], row["colour"], "true_moving_occlusion", True, 1600 + i,
                              moving_cover=True, hidden=[rng.randint(3, 6)], seconds_override=3.0))
    for i in range(10):
        first = random_plate(rng, known)
        slot = rng.randint(6, 9)
        replacement = rng.choice([d for d in "0123456789" if d != first[slot]])
        second = f"{first[:slot]}{replacement}{first[slot + 1:]}"
        known |= {first, second}
        template = {"make": "Tata", "model": "Starbus", "body_type": "bus", "year": 2020, "owner_name": "Fixture Owner",
                    "owner_city": "Fixture", "status": "ACTIVE", "colour": "blue"}
        extra += [{**template, "plate": first}, {**template, "plate": second}]
        cases.append(scenario(f"ambiguous{i}", first, "blue", "ambiguous_partial", True, 1200 + i, hidden=[slot]))
    for i in range(10):
        row = next(cursor)
        cases.append(scenario(f"unreadable{i}", row["plate"], row["colour"], "unreadable", True, 1300 + i,
                              plate_blur=7.0, motion_blur=9))
    for i in range(10):
        cases.append(scenario(f"outside{i}", random_plate(rng, known), rng.choice(["white", "blue", "red", "silver"]),
                              "out_of_registry", False, 1400 + i))
    sightings: list[Scenario] = []
    for i in range(10):
        row = next(cursor)
        for side, hidden in (("a", [7, 8, 9]), ("b", [0, 1, 2])):
            sightings.append(scenario(f"link{i}{side}", row["plate"], row["colour"], "link", True,
                                      1500 + 2 * i + (side == "b"), hidden=hidden, link_group=f"v{i}",
                                      direction=1 if side == "a" else -1))
    return extra, cases, sightings


def process(item: Scenario, directory: Path, registry: RegistryIndex, clip_start: datetime) -> Outcome:
    path = directory / item.file
    render(item, path)
    metadata = probe_video(path)
    tracks, _ = _stitch_tracks(models.detector.track_clip(sample_frames(path, metadata, stats=SamplingStats())))
    path.unlink(missing_ok=True)
    hidden = set(item.hidden)
    if not tracks:
        return Outcome(item, "", "NO_CONFIDENT_MATCH", "NO_VEHICLE_TRACK", [], None, 0, 0, 0, None)
    track = max(tracks, key=lambda value: value.frames_tracked)
    analysis = _analyse_track(track)
    query = build_query(analysis.fused.to_evidence(), analysis.attributes, PLATE_FORMAT)
    result = match(query, registry)
    ranked = [c.vehicle.plate for c in result.candidates + result.rejected_candidates]
    wrong, emitted, on_hidden = character_errors(analysis.fused.text, item.plate, hidden)
    profile = TrackProfile(
        vehicle_id=item.id, clip_id=item.id, embedding=mean_embedding(analysis.embeddings),
        histogram=analysis.histogram, plate_text=analysis.fused.text,
        body_type=analysis.attributes["body_type"]["label"], colours=analysis.attributes["colours"],
        make_models=analysis.attributes["make_model"]["predictions"], start=clip_start,
        end=clip_start + timedelta(seconds=track.last_seen_sec), plate_format=PLATE_FORMAT,
    )
    promoted = result.candidates[0].vehicle.plate if result.candidates else None
    return Outcome(item, analysis.fused.text, result.status, result.outcome, ranked, promoted, wrong, emitted,
                   on_hidden, profile)


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarise(outcomes: list[Outcome], sightings: list[Outcome]) -> dict:
    rankable = [o for o in outcomes if o.scenario.category in RANKABLE]
    top1 = sum(bool(o.ranked) and o.ranked[0] == o.scenario.plate for o in rankable)
    top5 = sum(o.scenario.plate in o.ranked[:5] for o in rankable)
    reciprocal = sum(1 / (o.ranked.index(o.scenario.plate) + 1) for o in rankable if o.scenario.plate in o.ranked[:5])
    expected = [o.scenario.category in EXPECT_NO_MATCH for o in outcomes]
    predicted = [o.status == "NO_CONFIDENT_MATCH" for o in outcomes]
    tp = sum(e and p for e, p in zip(expected, predicted))
    fp = sum(p and not e for e, p in zip(expected, predicted))
    fn = sum(e and not p for e, p in zip(expected, predicted))
    promoted = [o for o in outcomes if o.promoted]
    wrong_promotions = [o.scenario.id for o in promoted if o.promoted != o.scenario.plate]
    all_reads = outcomes + sightings
    emitted = sum(o.emitted_chars for o in all_reads)
    wrong = sum(o.wrong_chars for o in all_reads)

    profiles = [o.profile for o in sightings if o.profile is not None]
    groups = {o.scenario.id: o.scenario.link_group for o in sightings}
    result = link_tracks(profiles)
    proposed = {tuple(sorted((link["a"], link["b"]))) for link in result.links}
    true_pairs = {tuple(sorted((a.scenario.id, b.scenario.id)))
                  for i, a in enumerate(sightings) for b in sightings[i + 1:]
                  if a.scenario.link_group == b.scenario.link_group}
    correct_links = len(proposed & true_pairs)
    by_category: dict[str, dict] = {}
    for category in sorted({o.scenario.category for o in outcomes}):
        members = [o for o in outcomes if o.scenario.category == category]
        counts: dict[str, int] = {}
        for member in members:
            counts[member.outcome] = counts.get(member.outcome, 0) + 1
        by_category[category] = {"cases": len(members), "outcomes": counts}
    return {
        "data": "labelled synthetic video fixtures, not real CCTV",
        "single_sighting_cases": len(outcomes), "cross_camera_sightings": len(sightings),
        "top1_accuracy": ratio(top1, len(rankable)), "top5_recall": ratio(top5, len(rankable)),
        "mrr": ratio(reciprocal, len(rankable)), "rankable_cases": len(rankable),
        "no_match_precision": ratio(tp, tp + fp), "no_match_recall": ratio(tp, tp + fn),
        "promoted": len(promoted), "wrong_promotions": wrong_promotions,
        "emitted_characters": emitted, "wrong_emitted_characters": wrong,
        "character_precision": ratio(emitted - wrong, emitted),
        "characters_emitted_on_hidden_slots": sum(o.hidden_emitted for o in all_reads),
        "link_precision": ratio(correct_links, len(proposed)), "link_recall": ratio(correct_links, len(true_pairs)),
        "links_proposed": len(proposed), "true_link_pairs": len(true_pairs),
        "negative_link_pairs": len(profiles) * (len(profiles) - 1) // 2 - len(true_pairs),
        "by_category": by_category,
        "failures": [
            {"id": o.scenario.id, "category": o.scenario.category, "truth": o.scenario.plate, "read": o.plate,
             "outcome": o.outcome}
            for o in outcomes
            if (o.scenario.category in EXPECT_PROMOTION and o.promoted != o.scenario.plate)
            or (o.scenario.category in EXPECT_NO_MATCH and o.promoted is not None)
        ],
        "unused_groups": len(set(groups.values())) - len(true_pairs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261127, help="Default is the final held-out seed.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    models.load()
    extra, cases, link_cases = build_cases(args.seed)
    rows = build_registry(5000) + extra
    registry = RegistryIndex(RegistryRecord(id=i, source="synthetic", **row) for i, row in enumerate(rows, 1))
    started = time.perf_counter()
    base = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix="vehicle-tracer-eval-") as folder:
        directory = Path(folder)
        outcomes = [process(item, directory, registry, base) for item in cases]
        sightings = [process(item, directory, registry, base + timedelta(minutes=10 * i))
                     for i, item in enumerate(link_cases)]
    report = {"seed": args.seed, **summarise(outcomes, sightings),
              "elapsed_sec": round(time.perf_counter() - started, 1)}
    report.pop("unused_groups", None)
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
