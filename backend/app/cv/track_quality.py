"""Grade track evidence without removing any vehicle from the results."""
from __future__ import annotations

import numpy as np

BRIEF_FRAMES = 6
LOW_DETECTOR_CONFIDENCE = 0.40
HIGH_OCCLUSION = 0.70
LITTLE_MOTION = 0.12
PARTIAL_VIEW_SHARE = 0.8


def assess_track(track) -> dict:
    """Return measurements and review reasons. A flagged track is kept, never suppressed."""
    frames = max(track.frames_tracked, 1)
    duration = max(track.last_seen_sec - track.first_seen_sec, 0.0)
    confidence = track.confidence_sum / frames
    occlusion = track.occlusion_sum / frames
    truncated = track.truncated_frames / frames
    boxes = np.asarray([box for _, box in track.trajectory], dtype=np.float64)
    centers = (boxes[:, :2] + boxes[:, 2:]) / 2
    size = float(np.median(np.hypot(boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1])))
    motion = float(np.linalg.norm(centers[-1] - centers[0]) / max(size, 1.0))
    best = max(track.observations, key=lambda item: item.sharpness, default=None)
    reasons: list[str] = []
    if frames < BRIEF_FRAMES:
        reasons.append(f"brief track ({frames} sampled frames)")
    if confidence < LOW_DETECTOR_CONFIDENCE:
        reasons.append(f"low detector confidence ({confidence:.2f})")
    if occlusion >= HIGH_OCCLUSION:
        reasons.append(f"lower body usually hidden by nearer vehicles ({occlusion:.0%})")
    if truncated >= PARTIAL_VIEW_SHARE:
        reasons.append("vehicle usually cut off by the frame edge")
    if frames < BRIEF_FRAMES and motion < LITTLE_MOTION:
        reasons.append("little motion, so this may be a background object")
    return {
        "tier": "review" if reasons else "reliable",
        "reasons": reasons,
        "duration_sec": round(duration, 2),
        "sampled_frames": track.frames_tracked,
        "mean_detector_confidence": round(confidence, 3),
        "mean_lower_occlusion": round(occlusion, 3),
        "truncated_share": round(truncated, 3),
        "motion_ratio": round(motion, 3),
        "best_frame_sharpness": round(best.sharpness, 1) if best else None,
        "median_box": [round(float(np.median(boxes[:, 2] - boxes[:, 0]))),
                       round(float(np.median(boxes[:, 3] - boxes[:, 1])))],
        "merged_fragments": len(track.merged_track_ids),
    }
