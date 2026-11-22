"""Typed inputs and outputs of the matching engine."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

UNKNOWN = "?"
Anchor = Literal["full", "prefix", "suffix", "floating"]


class CharCandidate(BaseModel):
    char: str
    probability: float


class SlotEvidence(BaseModel):
    char: str = UNKNOWN
    confidence: float = 0.0
    candidates: list[CharCandidate] = Field(default_factory=list)
    locked: bool = False

    @property
    def known(self) -> bool:
        return self.char != UNKNOWN


class PlateEvidence(BaseModel):
    slots: list[SlotEvidence] = Field(default_factory=list)
    anchor: Anchor = "full"

    @property
    def text(self) -> str:
        return "".join(slot.char for slot in self.slots)

    @property
    def known_count(self) -> int:
        return sum(slot.known for slot in self.slots)

    @classmethod
    def from_text(cls, text: str, confidence: float = 0.9, anchor: Anchor | None = None) -> "PlateEvidence":
        cleaned = "".join(ch for ch in text.upper() if ch.isalnum() or ch == UNKNOWN)
        slots = [
            SlotEvidence(char=ch, confidence=0.0 if ch == UNKNOWN else confidence)
            for ch in cleaned
        ]
        resolved: Anchor = anchor or ("full" if len(slots) >= 9 else "floating")
        return cls(slots=slots, anchor=resolved)


class LabelScore(BaseModel):
    label: str
    confidence: float


class MakeModelScore(BaseModel):
    make: str
    model: str
    confidence: float


class QueryEvidence(BaseModel):
    plate: PlateEvidence = Field(default_factory=PlateEvidence)
    colours: list[LabelScore] = Field(default_factory=list)
    body_type: str | None = None
    body_confidence: float = 0.0
    make_models: list[MakeModelScore] = Field(default_factory=list)


class RegistryRecord(BaseModel):
    id: int | None = None
    plate: str
    make: str = "Unknown"
    model: str = "Unknown"
    body_type: str = "sedan"
    colour: str = "white"
    year: int | None = None
    owner_name: str | None = None
    owner_city: str | None = None
    status: str = "ACTIVE"


class SlotDiff(BaseModel):
    position: int
    query: str
    registry: str
    kind: Literal["exact", "confusable", "unknown", "mismatch", "hard_mismatch", "unobserved"]
    confidence: float
    contribution: float


class SubScores(BaseModel):
    plate: float
    colour: float | None
    body_type: float | None
    make_model: float | None
    coverage: float
    plate_quality: float


class Candidate(BaseModel):
    rank: int = 0
    vehicle: RegistryRecord
    score: float
    confidence: float
    sub_scores: SubScores
    weights: dict[str, float]
    slot_diff: list[SlotDiff]
    alignment_offset: int
    hard_mismatches: int
    vetoed: bool
    contradictions: list[str]
    reasons: list[str]


class MatchResult(BaseModel):
    status: Literal["CONFIDENT_SHORTLIST", "NO_CONFIDENT_MATCH"]
    regime: Literal["high_readability", "partial_plate", "severe_occlusion"]
    query_plate: str
    known_chars: int
    candidates: list[Candidate]
    rejected_candidates: list[Candidate]
    diagnostics: list[str]
    registry_size: int
    elapsed_ms: float
