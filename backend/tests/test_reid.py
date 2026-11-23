from datetime import datetime, timedelta, timezone

import numpy as np

from app.cv.plate_fusion import PlateRead, fuse_plate_reads
from app.cv.reid import TrackProfile, link_tracks, pair_similarity, plate_compatibility


def unit(*values):
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def profile(vid, clip, emb, plate="", body="suv", colour="white", start=None):
    return TrackProfile(
        vehicle_id=vid, clip_id=clip, embedding=emb, histogram=unit(*emb[:3], 1.0), plate_text=plate,
        body_type=body, colours=[{"label": colour, "confidence": 0.9}], make_models=[],
        start=start, end=start + timedelta(seconds=10) if start else None,
    )


def test_partial_plates_are_compatible():
    assert plate_compatibility("MH12??1433", "??12DE14??") == 1.0
    assert plate_compatibility("MH12DE1433", "KA05XY9988") < 0.35
    assert plate_compatibility("??", "MH12") is None


def test_same_vehicle_links_across_cameras():
    a = profile("a", "c1", unit(1, 0.1, 0), "MH12??1433")
    b = profile("b", "c2", unit(1, 0.12, 0), "??12DE14??")
    groups, links, _ = link_tracks([a, b])
    assert groups == [["a", "b"]] and links[0]["plate"] == 1.0
    assert links[0]["evidence_tier"] == "partial_plate"
    assert links[0]["temporal_status"] == "unavailable"


def test_plate_weight_redistributes_when_absent():
    pair = pair_similarity(profile("a", "c1", unit(1, 0, 0)), profile("b", "c2", unit(1, 0, 0)))
    assert pair["weights"]["plate"] == 0.0
    assert abs(sum(pair["weights"].values()) - 1.0) < 1e-3


def test_plate_conflict_blocks_link():
    a = profile("a", "c1", unit(1, 0, 0), "MH12DE1433")
    b = profile("b", "c2", unit(1, 0, 0), "KA05XY9988")
    result = link_tracks([a, b])
    assert result.groups == [] and result.blocked == 1


def test_attributes_and_visual_without_time_never_create_a_link():
    assert link_tracks([profile("a", "c1", unit(1, 0, 0)), profile("b", "c2", unit(1, 0, 0))]).groups == []


def test_strong_visual_with_plausible_time_is_proposed():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = profile("a", "c1", unit(1, 0, 0), start=start)
    b = profile("b", "c2", unit(1, 0, 0), start=start + timedelta(minutes=5))
    result = link_tracks([a, b])
    assert result.groups == [["a", "b"]] and result.links[0]["evidence_tier"] == "visual_time"


def test_implausible_time_blocks_visual_link():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = profile("a", "c1", unit(1, 0, 0), start=start)
    b = profile("b", "c2", unit(1, 0, 0), start=start + timedelta(seconds=2))
    assert link_tracks([a, b]).groups == []


def test_repetitive_partial_digits_do_not_link():
    a = profile("a", "c1", unit(1, 0, 0), "???????14444?")
    b = profile("b", "c2", unit(0, 1, 0), "?144?4")
    assert link_tracks([a, b]).groups == []


def test_tracks_in_same_clip_never_link():
    assert link_tracks([profile("a", "c1", unit(1, 0, 0), "MH12DE1433"),
                         profile("b", "c1", unit(1, 0, 0), "MH12DE1433")]).groups == []


def test_group_never_has_two_tracks_from_one_clip():
    tracks = [profile("a", "c1", unit(1, 0, 0), "MH12DE1433"), profile("b", "c2", unit(1, 0, 0), "MH12DE1433"),
              profile("c", "c1", unit(1, 0, 0), "MH12DE1433")]
    groups, _, _ = link_tracks(tracks)
    assert len(groups) == 1 and len(groups[0]) == 2


def test_simultaneous_sightings_are_penalised():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = profile("a", "c1", unit(1, 0, 0), start=start)
    plausible = profile("b", "c2", unit(1, 0, 0), start=start + timedelta(minutes=5))
    impossible = profile("c", "c2", unit(1, 0, 0), start=start + timedelta(seconds=2))
    assert pair_similarity(a, impossible)["score"] < pair_similarity(a, plausible)["score"]


def test_cross_camera_plate_merge():
    def read(frame, text):
        return PlateRead(frame, frame, text, [0.0 if c == "?" else 0.9 for c in text], 100, 1000, 0.9)

    assert fuse_plate_reads([read(1, "MH12??1433"), read(2, "??12DE14??")]).text == "MH12DE1433"
