"""One vocabulary for every user-facing outcome, shared by the API and reports."""
from __future__ import annotations

OUTCOME_LABELS = {
    "PLATE_CANDIDATE": "Plate-supported candidate",
    "AMBIGUOUS": "Ambiguous candidates",
    "NO_REGISTRY_MATCH": "No registry match",
    "INSUFFICIENT_PLATE": "Partial plate only",
    "UNREADABLE_PLATE": "Plate unreadable",
}
ENTITY_STATUS_LABELS = {"proposed": "Possible link", "confirmed": "Confirmed vehicle", "rejected": "Rejected"}
EVIDENCE_TIER_LABELS = {
    "strong_plate": "Consistent plate characters",
    "partial_plate": "Partial plate plus visual similarity",
    "visual_time": "Strong visual similarity with plausible time",
    "legacy_unverified": "Older analysis, re-run required",
}


def pretty(value: object) -> str:
    return str(value).replace("_", " ")
