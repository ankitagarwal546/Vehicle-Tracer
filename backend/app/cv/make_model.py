"""Zero-shot make/model recognition gated by body type."""
from __future__ import annotations

import numpy as np

from app.cv.clip_service import ClipService
from app.engine.confusion_matrices import body_similarity, normalise_body
from app.engine.taxonomy import VEHICLE_TAXONOMY

MIN_TOP1_CONFIDENCE = 0.35
COMPATIBLE_BODY = 0.45


def candidates_for_body(body_type: str) -> list[tuple[str, str, str]]:
    body = normalise_body(body_type)
    exact = [entry for entry in VEHICLE_TAXONOMY if entry[2] == body]
    if exact:
        return exact
    return [entry for entry in VEHICLE_TAXONOMY if body_similarity(body, entry[2]) >= COMPATIBLE_BODY]


def recognise(embedding: np.ndarray | None, body_type: str, clip: ClipService | None) -> dict:
    """Return top-3 predictions, or ``Unknown`` when top-1 is below the threshold."""
    unknown = {"make": "Unknown", "model": "Unknown", "confidence": 0.0}
    if embedding is None or clip is None or not clip.available:
        return {"status": "unavailable", "predictions": [unknown], "below_threshold": []}
    entries = candidates_for_body(body_type)
    if not entries:
        return {"status": "unknown", "predictions": [unknown], "below_threshold": []}
    prompts = [[f"a photo of a {make} {model}", f"a CCTV image of a {make} {model} {body.replace('_', ' ')}"]
               for make, model, body in entries]
    probabilities = clip.zero_shot(embedding, prompts)
    order = np.argsort(probabilities)[::-1][:3]
    ranked = [{"make": entries[i][0], "model": entries[i][1], "confidence": round(float(probabilities[i]), 4)}
              for i in order]
    if ranked[0]["confidence"] < MIN_TOP1_CONFIDENCE:
        return {"status": "unknown", "predictions": [unknown], "below_threshold": ranked}
    return {"status": "recognised", "predictions": ranked, "below_threshold": []}
