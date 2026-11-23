import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evaluate_pipeline import character_errors  # noqa: E402


def test_dropped_character_does_not_count_later_characters_as_wrong():
    assert character_errors("UP16R4569", "UP16RX4569", {5}) == (0, 9, 0)


def test_wrong_and_hidden_characters_are_counted():
    assert character_errors("MH12DE1439", "MH12DE1433", set())[0] == 1
    assert character_errors("MH12XE1433", "MH12DE1433", {4}) == (1, 10, 1)


def test_unknown_characters_are_not_emitted():
    assert character_errors("MH12??1433", "MH12DE1433", {4, 5}) == (0, 8, 0)
