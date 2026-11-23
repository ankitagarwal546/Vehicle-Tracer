"""One source of truth for case counts, registry coverage and validation status.

The workspace, HTML report, PDF report and exports all read these values, so they cannot disagree.
"""
from __future__ import annotations

from collections import Counter

from app.engine.confusion_matrices import PLATE_FORMAT_NAMES, plate_family
from app.engine.matcher import THRESHOLDS, RegistryIndex

READABLE_CHARS = int(THRESHOLDS["min_readable_chars"])
MIN_HINT_READS = 3
FAMILY_LABELS = {"india_rto": "India RTO / BH", "uk": "UK", "other": "Other / unclassified"}


def readability(known_chars: int) -> str:
    if known_chars <= 0:
        return "none"
    return "partial" if known_chars < READABLE_CHARS else "readable"


def registry_snapshot(index: RegistryIndex) -> dict:
    total = len(index.records)
    synthetic = sum(record.source == "synthetic" for record in index.records)
    families = index.family_counts()
    if total == 0:
        note = "The registry is empty."
    elif synthetic == total:
        note = f"The {total:,}-vehicle registry is entirely synthetic test data. Its people and plates are fictional."
    elif synthetic:
        note = f"{synthetic:,} of {total:,} registry vehicles are synthetic test data with fictional people and plates."
    else:
        note = f"The registry contains {total:,} operator-supplied vehicles."
    return {
        "total": total, "synthetic": synthetic, "note": note, "fingerprint": index.fingerprint(),
        "by_family": [{"family": key, "label": FAMILY_LABELS.get(key, key), "records": count}
                      for key, count in sorted(families.items())],
    }


def clip_coverage(clips, index: RegistryIndex) -> list[dict]:
    rows = []
    for clip in clips:
        compatible = index.compatible_count(clip.plate_format)
        rows.append({
            "clip_id": clip.id, "camera_label": clip.camera_label, "plate_format": clip.plate_format,
            "format_label": PLATE_FORMAT_NAMES.get(clip.plate_format, clip.plate_format),
            "compatible_records": compatible, "total_records": len(index.records),
            "status": "covered" if compatible else "no_coverage",
        })
    return rows


def format_hints(vehicles, clips, index: RegistryIndex) -> list[dict]:
    """Warn when a Latin-any camera mostly reads a plate family the registry does not contain.

    This is a prompt for the investigator. It never changes a format, read or outcome.
    """
    available = index.family_counts()
    hints = []
    for clip in clips:
        if clip.plate_format != "latin_any":
            continue
        reads = [text for vehicle in vehicles if vehicle.clip_id == clip.id
                 and (text := (vehicle.match_result or {}).get("query_plate", ""))
                 and "?" not in text and len(text) >= READABLE_CHARS]
        for family, count in Counter(plate_family(text) for text in reads).items():
            if family != "other" and not available.get(family) and count >= MIN_HINT_READS and count * 2 >= len(reads):
                label = FAMILY_LABELS[family]
                hints.append({
                    "clip_id": clip.id, "camera_label": clip.camera_label, "family": family, "family_label": label,
                    "reads": count, "complete_reads": len(reads),
                    "message": f"{clip.camera_label} is set to {PLATE_FORMAT_NAMES['latin_any']}. {count} of "
                               f"{len(reads)} complete plate reads look {label}, but the registry has 0 {label} "
                               "records. Their no-match results may reflect missing coverage. Set the camera's plate "
                               "format to confirm.",
                })
    return hints


def build_preflight(case, index: RegistryIndex) -> dict:
    """Checks shown before analysis starts. Coverage gaps need explicit acknowledgement."""
    coverage = clip_coverage(case.clips, index)
    uncovered = [row for row in coverage if row["status"] == "no_coverage"]
    warnings: list[dict] = []
    for row in uncovered:
        warnings.append({
            "code": "NO_REGISTRY_COVERAGE", "severity": "high", "clip_id": row["clip_id"],
            "message": f"{row['camera_label']} uses {row['format_label']} plates, but the active registry has 0 "
                       f"compatible records out of {row['total_records']:,}. Plates can be read as OCR evidence, "
                       "but they cannot be compared with the registry.",
        })
    missing_time = [clip.camera_label for clip in case.clips if clip.recorded_at is None]
    if missing_time:
        warnings.append({
            "code": "MISSING_CAPTURE_TIME", "severity": "medium", "clip_id": None,
            "message": f"Capture time is missing for {', '.join(missing_time)}. Temporal validation is disabled "
                       "for those clips.",
        })
    if len(case.clips) == 1:
        warnings.append({
            "code": "SINGLE_CLIP", "severity": "info", "clip_id": None,
            "message": "This case has one clip, so cross-camera re-identification will not be tested.",
        })
    next_steps = []
    if uncovered:
        next_steps = ["Upload a registry containing plates in this format.",
                      "Or change the camera's plate format if it was set incorrectly.",
                      "Or continue to collect OCR evidence without a registry comparison."]
    return {
        "coverage": coverage, "registry": registry_snapshot(index), "warnings": warnings, "next_steps": next_steps,
        "requires_acknowledgement": bool(uncovered),
    }


def summarise(vehicles, entities, clips, index: RegistryIndex, runtime: dict | None = None) -> dict:
    results = [vehicle.match_result or {} for vehicle in vehicles]
    outcomes = Counter(result.get("outcome", "UNREADABLE_PLATE") for result in results)
    read_levels = Counter(readability(result.get("known_chars", 0)) for result in results)
    quality = Counter(((vehicle.attributes or {}).get("track_quality") or {}).get("tier", "not_assessed")
                      for vehicle in vehicles)
    links = Counter(entity.review_status for entity in entities)
    coverage = clip_coverage(clips, index)
    uncovered = [row for row in coverage if row["status"] == "no_coverage"]
    clip_count = len(clips)
    missing_time = sum(clip.recorded_at is None for clip in clips)
    if clip_count < 2:
        cross_status = "not_tested_single_clip"
        cross_note = "This case has one clip, so cross-camera re-identification was not tested."
    else:
        cross_status = "evaluated"
        cross_note = (f"{clip_count} clips were compared. {links['proposed']} possible link(s) await review and "
                      f"{links['confirmed']} are confirmed. Links are not automatic identifications.")
    if missing_time == 0:
        temporal_status, temporal_note = "available", "Capture times were supplied for every clip."
    elif missing_time == clip_count:
        temporal_status = "unavailable"
        temporal_note = "Capture time is missing, so temporal validation is disabled."
    else:
        temporal_status = "partial"
        temporal_note = f"Capture time is missing for {missing_time} of {clip_count} clips, so temporal validation " \
                        "is disabled for links involving them."
    recorded = (runtime or {}).get("registry_fingerprint")
    format_changed = any(
        (vehicle.match_result or {}).get("registry_coverage")
        and vehicle.match_result["registry_coverage"]["plate_format"] != vehicle.clip.plate_format
        for vehicle in vehicles
    )
    return {
        "tracks": len(results),
        "plate_candidates": outcomes["PLATE_CANDIDATE"], "ambiguous": outcomes["AMBIGUOUS"],
        "no_registry_match": outcomes["NO_REGISTRY_MATCH"], "no_registry_coverage": outcomes["NO_REGISTRY_COVERAGE"],
        "insufficient_plate": outcomes["INSUFFICIENT_PLATE"], "unreadable_plate": outcomes["UNREADABLE_PLATE"],
        "readable_plates": read_levels["readable"], "partial_plates": read_levels["partial"],
        "no_plate_chars": read_levels["none"],
        "tracks_reliable": quality["reliable"], "tracks_review": quality["review"],
        "possible_links": links["proposed"], "confirmed_links": links["confirmed"], "rejected_links": links["rejected"],
        "fragments_merged": sum((clip.processing or {}).get("fragments_merged", 0) for clip in clips),
        "clip_count": clip_count, "clips_missing_time": missing_time,
        "cross_camera_status": cross_status, "cross_camera_note": cross_note,
        "temporal_status": temporal_status, "temporal_note": temporal_note,
        "coverage": coverage, "coverage_status": "none" if clip_count and len(uncovered) == clip_count
        else "partial" if uncovered else "covered",
        "registry": registry_snapshot(index),
        "registry_changed": bool(vehicles) and recorded is not None and recorded != index.fingerprint(),
        "format_changed": format_changed,
        "format_hints": format_hints(vehicles, clips, index),
        "score_note": "Match scores are uncalibrated ranking values, not probabilities.",
    }


def headline(summary: dict) -> str:
    compared = summary["plate_candidates"] + summary["ambiguous"] + summary["no_registry_match"]
    parts = [f"{summary['readable_plates']} readable plate(s), {summary['partial_plates']} partial and "
             f"{summary['no_plate_chars']} unreadable."]
    if summary["no_registry_coverage"]:
        parts.append(f"{summary['no_registry_coverage']} readable plate(s) could not be searched because the registry "
                     "has no compatible records. These are not no-match results.")
    if compared:
        parts.append(f"{compared} were compared with compatible records, and {summary['no_registry_match']} of those "
                     "matched no registry vehicle.")
    return " ".join(parts)
