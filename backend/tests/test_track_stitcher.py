from dataclasses import dataclass

from app.cv.track_stitcher import fragment_geometry, plan_merges


@dataclass
class T:
    track_id: int
    trajectory: list


def moving(track_id, start, count, x=100, step=10):
    return T(track_id, [(start + i * 0.2, (x + i * step, 100, x + 100 + i * step, 180)) for i in range(count)])


def test_fragment_on_same_path_is_merged():
    first = moving(1, 0.0, 6)
    second = moving(2, 2.0, 6, x=200)
    decisions = plan_merges([first, second], lambda a, b: 0.95)
    assert [(d.kept, d.merged) for d in decisions] == [(1, 2)]


def test_different_appearance_is_not_merged():
    assert plan_merges([moving(1, 0.0, 6), moving(2, 2.0, 6, x=200)], lambda a, b: 0.6) == []


def test_far_apart_tracks_are_not_merged():
    assert fragment_geometry(moving(1, 0.0, 6), moving(2, 2.0, 6, x=900)) is None
    assert plan_merges([moving(1, 0.0, 6), moving(2, 2.0, 6, x=900)], lambda a, b: 0.99) == []


def test_long_gap_is_not_merged():
    assert plan_merges([moving(1, 0.0, 3), moving(2, 9.0, 3, x=120)], lambda a, b: 0.99) == []


def test_concurrent_duplicate_box_is_merged():
    decisions = plan_merges([moving(1, 0.0, 6), moving(2, 0.0, 6, x=103)], lambda a, b: 0.9)
    assert decisions and decisions[0].reason == "concurrent duplicate"


def test_two_side_by_side_vehicles_stay_separate():
    assert plan_merges([moving(1, 0.0, 6), moving(2, 0.0, 6, x=260)], lambda a, b: 0.99) == []
