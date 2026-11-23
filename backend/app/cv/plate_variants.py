"""Traceable plate image variants.

Only ``raw`` is source evidence. Every other variant is a labelled derivative: geometric,
interpolated or filtered views help OCR and human review, but cannot create evidence alone.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MIN_RECTIFY_HEIGHT = 18
MIN_QUAD_AREA_SHARE = 0.45
MIN_PLATE_ASPECT = 1.5
MAX_PLATE_ASPECT = 8.0
MIN_SKEW_DEGREES = 1.5
MAX_SKEW_DEGREES = 25.0
MAX_BOUNDARY_ROUGHNESS = 1.35

VARIANTS: dict[str, dict] = {
    "raw": {"label": "Raw crop", "kind": "source", "weight": 1.0},
    "perspective": {"label": "Perspective corrected", "kind": "geometric", "weight": 0.8},
    "upscale_2x": {"label": "2x interpolation", "kind": "interpolated", "weight": 0.5},
    "upscale_4x": {"label": "4x interpolation", "kind": "interpolated", "weight": 0.5},
    "gray_clahe": {"label": "Grayscale + CLAHE", "kind": "filtered", "weight": 0.4},
    "denoised": {"label": "Denoised", "kind": "filtered", "weight": 0.4},
    "unsharp": {"label": "Restrained unsharp", "kind": "filtered", "weight": 0.3},
}


@dataclass(frozen=True)
class Rectification:
    status: str  # applied | not_needed | unavailable
    reason: str
    corners: list[list[int]] | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason, "corners": self.corners}


def _order_corners(points: np.ndarray) -> np.ndarray:
    """Return corners as top-left, top-right, bottom-right, bottom-left."""
    total = points.sum(axis=1)
    delta = np.diff(points, axis=1).ravel()
    return np.array([points[np.argmin(total)], points[np.argmin(delta)],
                     points[np.argmax(total)], points[np.argmax(delta)]], dtype=np.float32)


def _max_skew(corners: np.ndarray) -> float:
    edges = [(0, 1), (3, 2)]
    angles = []
    for a, b in edges:
        dx, dy = corners[b] - corners[a]
        angles.append(abs(np.degrees(np.arctan2(dy, dx))))
    for a, b in [(0, 3), (1, 2)]:
        dx, dy = corners[b] - corners[a]
        angles.append(abs(90.0 - abs(np.degrees(np.arctan2(dy, dx)))))
    return float(max(angles))


def rectify_plate(image: np.ndarray) -> tuple[np.ndarray | None, Rectification]:
    """Warp from plate corners only when four reliable corners are found."""
    height, width = image.shape[:2]
    if height < MIN_RECTIFY_HEIGHT:
        return None, Rectification("unavailable", "crop too small to locate corners reliably")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, Rectification("unavailable", "no plate boundary found")
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < MIN_QUAD_AREA_SHARE * width * height:
        return None, Rectification("unavailable", "plate boundary covers too little of the crop")
    perimeter = cv2.arcLength(largest, True)
    quad = cv2.approxPolyDP(largest, 0.04 * perimeter, True)
    if len(quad) != 4 or not cv2.isContourConvex(quad):
        return None, Rectification("unavailable", "four reliable corners were not found")
    if perimeter > MAX_BOUNDARY_ROUGHNESS * cv2.arcLength(quad, True):
        return None, Rectification("unavailable", "plate boundary is too irregular to trust its corners")
    corners = _order_corners(quad.reshape(4, 2).astype(np.float32))
    target_w = int(max(np.linalg.norm(corners[1] - corners[0]), np.linalg.norm(corners[2] - corners[3])))
    target_h = int(max(np.linalg.norm(corners[3] - corners[0]), np.linalg.norm(corners[2] - corners[1])))
    if target_h < 1 or not MIN_PLATE_ASPECT <= target_w / target_h <= MAX_PLATE_ASPECT:
        return None, Rectification("unavailable", "corner geometry is not plate-shaped")
    points = [[int(x), int(y)] for x, y in corners]
    skew = _max_skew(corners)
    if skew < MIN_SKEW_DEGREES:
        return None, Rectification("not_needed", f"plate is already aligned ({skew:.1f} degrees)", points)
    if skew > MAX_SKEW_DEGREES:
        return None, Rectification("unavailable", f"corner skew {skew:.1f} degrees is not reliable", points)
    destination = np.array([[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
                           dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners, destination)
    warped = cv2.warpPerspective(image, matrix, (target_w, target_h), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
    return warped, Rectification("applied", f"corrected {skew:.1f} degrees of skew", points)


def clahe_view(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.createCLAHE(clipLimit=2.0, tileGridSize=(3, 6)).apply(gray), cv2.COLOR_GRAY2BGR)


def denoised_view(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.fastNlMeansDenoising(gray, None, 6, 5, 11), cv2.COLOR_GRAY2BGR)


def unsharp_view(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.0)
    return cv2.cvtColor(cv2.addWeighted(gray, 1.35, blurred, -0.35, 0), cv2.COLOR_GRAY2BGR)


def build_variants(raw: np.ndarray) -> tuple[dict[str, np.ndarray], Rectification]:
    """Build derivatives. The raw array is copied, so the source crop is never altered."""
    views = {
        "raw": raw.copy(),
        "upscale_2x": cv2.resize(raw, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
        "upscale_4x": cv2.resize(raw, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC),
        "gray_clahe": clahe_view(raw),
        "denoised": denoised_view(raw),
        "unsharp": unsharp_view(raw),
    }
    warped, rectification = rectify_plate(raw)
    if warped is not None:
        views["perspective"] = warped
    return views, rectification
