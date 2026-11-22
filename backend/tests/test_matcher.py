import time

import pytest

from app.db.seed_registry import build_registry
from app.engine.confusion_matrices import body_similarity, colour_similarity
from app.engine.matcher import match, score_plate
from app.engine.schemas import (
    CharCandidate,
    LabelScore,
    MakeModelScore,
    PlateEvidence,
    QueryEvidence,
    RegistryRecord,
    SlotEvidence,
)


@pytest.fixture(scope="module")
def registry():
    return [RegistryRecord(id=i, **row) for i, row in enumerate(build_registry(), 1)]


def query(text, colour="white", body="suv", body_conf=0.8, conf=0.9, anchor=None, mm=None):
    return QueryEvidence(
        plate=PlateEvidence.from_text(text, conf, anchor),
        colours=[LabelScore(label=colour, confidence=0.8)] if colour else [],
        body_type=body,
        body_confidence=body_conf if body else 0,
        make_models=mm or [],
    )


def test_registry_has_600_unique_plates():
    rows = build_registry()
    assert len(rows) == 600 and len({r["plate"] for r in rows}) == 600
    assert build_registry() == rows


def test_exact_plate_ranks_first(registry):
    result = match(query("MH12DE1433"), registry)
    assert result.status == "CONFIDENT_SHORTLIST"
    assert result.candidates[0].vehicle.plate == "MH12DE1433"


def test_near_duplicate_cluster_is_separated_by_attributes(registry):
    result = match(query("MH12DE14?3", colour="white", body="sedan"), registry)
    assert result.candidates[0].vehicle.plate == "MH12DE1483"


def test_wildcards_are_neutral_but_reduce_coverage():
    plate = PlateEvidence.from_text("MH12??1433")
    score, quality, gamma, *_ = score_plate(plate, "MH12DE1433")
    assert quality == pytest.approx(1.0)
    assert gamma == pytest.approx(0.8)
    assert score == pytest.approx(0.8)


def test_confusable_scores_between_exact_and_mismatch():
    exact = score_plate(PlateEvidence.from_text("MH12DE1433", 0.7), "MH12DE1433")[1]
    confusable = score_plate(PlateEvidence.from_text("MH12DE1B33", 0.7), "MH12DE1833")[1]
    mismatch = score_plate(PlateEvidence.from_text("MH12DE1K33", 0.7), "MH12DE1833")[1]
    assert exact > confusable > mismatch


def test_runner_up_distribution_adds_bonus():
    base = PlateEvidence.from_text("MH12DE1B33", 0.7)
    boosted = base.model_copy(deep=True)
    boosted.slots[7] = SlotEvidence(char="B", confidence=0.7, candidates=[CharCandidate(char="8", probability=0.4)])
    assert score_plate(boosted, "MH12DE1833")[1] > score_plate(base, "MH12DE1833")[1]


def test_suffix_alignment_for_occluded_plate(registry):
    result = match(query("4829", colour="red", body="hatchback"), registry)
    top = result.candidates[0] if result.candidates else result.rejected_candidates[0]
    assert top.vehicle.plate.endswith("4829")
    assert top.alignment_offset == 6


def test_two_characters_cannot_inflate_confidence(registry):
    result = match(query("MH", colour="white", body="suv"), registry)
    for candidate in result.candidates + result.rejected_candidates:
        assert candidate.confidence <= 65.0


def test_no_plate_attribute_only_is_not_confident(registry):
    result = match(query("", colour="white", body="suv"), registry)
    assert result.status == "NO_CONFIDENT_MATCH"
    assert result.candidates == [] and result.rejected_candidates


def test_out_of_registry_plate_returns_no_match(registry):
    result = match(query("ZZ99QQ0000", conf=0.95), registry)
    assert result.status == "NO_CONFIDENT_MATCH"
    assert result.diagnostics


def test_hard_veto_two_wheeler_vs_car():
    records = [RegistryRecord(plate="MH12DE1433", body_type="suv", colour="white")]
    result = match(query("MH12DE1433", body="two-wheeler", body_conf=0.95), records)
    candidate = result.rejected_candidates[0]
    assert candidate.vetoed and candidate.contradictions
    assert result.status == "NO_CONFIDENT_MATCH"


def test_all_body_incompatible_gate():
    records = [RegistryRecord(plate="MH12DE1433", body_type="heavy_truck", colour="white")]
    result = match(query("MH12DE1433", body="two-wheeler", body_conf=0.6), records)
    assert result.status == "NO_CONFIDENT_MATCH"
    assert any("body-compatible" in d for d in result.diagnostics)


def test_hard_mismatch_gate():
    records = [RegistryRecord(plate="MH12DE1433", body_type="suv", colour="white")]
    result = match(query("MH12KA9933", conf=0.95), records)
    assert result.status == "NO_CONFIDENT_MATCH"


def test_unknown_make_model_is_neutral():
    records = [RegistryRecord(plate="MH12DE1433", make="Hyundai", model="Creta", body_type="suv", colour="white")]
    unknown = [MakeModelScore(make="Unknown", model="Unknown", confidence=0.2)]
    assert match(query("MH12DE1433", mm=unknown), records).candidates[0].sub_scores.make_model is None


def test_explanations_are_present(registry):
    candidate = match(query("MH12DE14?3"), registry).candidates[0]
    assert len(candidate.slot_diff) == 10
    assert any("Exact character match" in r for r in candidate.reasons)
    assert any(d.kind == "unknown" for d in candidate.slot_diff)


def test_rerank_is_fast(registry):
    started = time.perf_counter()
    match(query("MH12DE14?3"), registry)
    assert (time.perf_counter() - started) * 1000 < 50


def test_matrices():
    assert colour_similarity("silver", "grey") == 0.85
    assert colour_similarity("white", "black") == 0.05
    assert body_similarity("sedan", "hatchback") == 0.60
    assert body_similarity("two-wheeler", "sedan") == 0.0
