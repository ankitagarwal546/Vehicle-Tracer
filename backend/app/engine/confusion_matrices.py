"""Domain knowledge used by the matcher: OCR, colour and body-type confusion."""
from __future__ import annotations

import re

_OCR_GROUPS: dict[str, str] = {
    "0": "ODQ", "1": "ILT", "8": "B3", "5": "S", "2": "Z", "6": "G", "7": "T",
    "M": "NW", "C": "G", "U": "V", "P": "RF", "K": "X",
}

OCR_CONFUSABLE: frozenset[tuple[str, str]] = frozenset(
    pair
    for key, values in _OCR_GROUPS.items()
    for value in values
    for pair in ((key, value), (value, key))
)


def is_confusable(a: str, b: str) -> bool:
    return (a, b) in OCR_CONFUSABLE


COLOURS = (
    "white", "silver", "grey", "black", "red", "maroon",
    "blue", "green", "yellow", "orange", "brown", "beige",
)

_COLOUR_PAIRS: dict[tuple[str, str], float] = {
    ("silver", "grey"): 0.85, ("silver", "white"): 0.70, ("grey", "white"): 0.45,
    ("black", "grey"): 0.65, ("black", "blue"): 0.65, ("black", "silver"): 0.25,
    ("black", "maroon"): 0.35, ("black", "brown"): 0.40, ("black", "green"): 0.30,
    ("red", "maroon"): 0.80, ("red", "orange"): 0.55, ("maroon", "brown"): 0.50,
    ("orange", "yellow"): 0.55, ("orange", "brown"): 0.40, ("yellow", "beige"): 0.45,
    ("beige", "white"): 0.55, ("beige", "silver"): 0.50, ("beige", "brown"): 0.50,
    ("blue", "grey"): 0.40, ("blue", "green"): 0.30, ("green", "grey"): 0.25,
    ("white", "black"): 0.05,
}
_COLOUR_DEFAULT = 0.12


def colour_similarity(a: str, b: str) -> float:
    a, b = a.lower().replace("dark_blue", "blue"), b.lower().replace("dark_blue", "blue")
    if a == b:
        return 1.0
    return _COLOUR_PAIRS.get((a, b), _COLOUR_PAIRS.get((b, a), _COLOUR_DEFAULT))


BODY_TYPES = (
    "sedan", "hatchback", "suv", "two-wheeler", "auto-rickshaw",
    "pickup_truck", "heavy_truck", "bus", "van",
)

_BODY_ALIASES = {
    "car": "car", "truck": "heavy_truck", "motorcycle": "two-wheeler", "scooter": "two-wheeler",
    "motorbike": "two-wheeler", "two_wheeler": "two-wheeler", "auto_rickshaw": "auto-rickshaw",
    "autorickshaw": "auto-rickshaw", "pickup": "pickup_truck", "heavy truck": "heavy_truck",
}

_BODY_PAIRS: dict[tuple[str, str], float] = {
    ("sedan", "hatchback"): 0.60, ("suv", "hatchback"): 0.45, ("suv", "sedan"): 0.45,
    ("suv", "van"): 0.50, ("suv", "pickup_truck"): 0.45, ("van", "hatchback"): 0.35,
    ("van", "sedan"): 0.25, ("van", "bus"): 0.40, ("van", "pickup_truck"): 0.40,
    ("pickup_truck", "heavy_truck"): 0.55, ("heavy_truck", "bus"): 0.40,
    ("pickup_truck", "sedan"): 0.20, ("pickup_truck", "hatchback"): 0.15,
    ("auto-rickshaw", "van"): 0.10, ("auto-rickshaw", "hatchback"): 0.10,
    ("car", "sedan"): 0.90, ("car", "hatchback"): 0.90, ("car", "suv"): 0.75,
    ("car", "van"): 0.40, ("car", "pickup_truck"): 0.25,
}


def normalise_body(value: str) -> str:
    key = value.strip().lower()
    return _BODY_ALIASES.get(key, key)


def body_similarity(a: str, b: str) -> float:
    a, b = normalise_body(a), normalise_body(b)
    if a == b:
        return 1.0
    return _BODY_PAIRS.get((a, b), _BODY_PAIRS.get((b, a), 0.0))


PLATE_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("BH", re.compile(r"^[0-9]{2}BH[0-9]{4}[A-HJ-NP-Z]{1,2}$")),
    ("DELHI", re.compile(r"^DL[0-9]{1,2}[A-Z]{1,3}[0-9]{1,4}$")),
    ("RTO", re.compile(r"^[A-Z]{2}[0-9]{2}[A-HJ-NP-Z]{1,2}[0-9]{4}$")),
)


def plate_format(plate: str) -> str | None:
    for name, pattern in PLATE_FORMATS:
        if pattern.match(plate):
            return name
    return None


PLATE_FORMAT_OPTIONS = ("latin_any", "india_rto", "uk", "non_latin_digits")
_UK_PLATE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$")
_INDIA_PLATE = re.compile(r"^(?:[A-Z]{2}[0-9A-Z]{6,8}|[0-9]{2}BH[0-9A-Z]{4,6})$")


def plate_family(plate: str) -> str:
    """Broad format family of a registry plate, tolerant of the registry's OCR-lookalike entries."""
    if _UK_PLATE.match(plate):
        return "uk"
    if _INDIA_PLATE.match(plate):
        return "india_rto"
    return "other"


def format_accepts(plate_format: str, family: str) -> bool:
    """Whether a registry family can be compared with reads from a camera's plate format."""
    if plate_format == "latin_any":
        return True
    if plate_format == "non_latin_digits":
        return family == "other"
    return plate_format == family


def expected_char_classes(plate: str) -> str:
    """Return one class per slot: ``A`` for a letter and ``9`` for a digit."""
    return "".join("9" if char.isdigit() else "A" for char in plate)
