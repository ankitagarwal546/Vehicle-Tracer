"""Generate clearly labelled synthetic CCTV fixtures with a ground-truth manifest.

Every frame carries a burned-in SYNTHETIC banner. The vehicle texture is cropped from the sample
photo bundled with Ultralytics, then a synthetic plate is composited and the clip is degraded.
The clips exercise the real pipeline. They do not represent real-world CCTV accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.seed_registry import build_registry  # noqa: E402

FPS = 20
WIDTH, HEIGHT = 960, 540
VEHICLE_CROP = (345, 235, 715, 705)
BANNER = "SYNTHETIC TEST FIXTURE - NOT REAL CCTV"
TIMEZONE = "Asia/Kolkata"
COLOUR_SHIFT = {
    "blue": (0, 1.0, 1.0), "red": (70, 1.0, 1.0), "green": (-50, 0.9, 0.9), "maroon": (70, 1.0, 0.6),
    "orange": (85, 1.0, 1.1), "yellow": (100, 1.0, 1.25), "white": (0, 0.08, 1.45), "silver": (0, 0.1, 1.1),
    "grey": (0, 0.1, 0.75), "black": (0, 0.2, 0.35), "brown": (85, 0.7, 0.55), "beige": (100, 0.3, 1.25),
}


@dataclass
class Scenario:
    id: str
    file: str
    camera: str
    location: str
    plate: str
    colour: str
    category: str
    in_registry: bool
    hidden: list[int] = field(default_factory=list)
    moving_cover: bool = False
    plate_blur: float = 0.0
    motion_blur: int = 5
    seed: int = 1
    direction: int = 1
    seconds: float = 3.0
    link_group: str | None = None
    capture_offset_min: float | None = 0.0
    latitude: float | None = None
    longitude: float | None = None
    expected: str = ""
    note: str = ""


def motion_blur(image: np.ndarray, length: int) -> np.ndarray:
    if length <= 1:
        return image
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1
    return cv2.filter2D(image, -1, kernel / length)


def road(rng: np.random.Generator) -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), 74, dtype=np.uint8)
    frame[:170] = (112, 104, 96)
    cv2.rectangle(frame, (0, 150), (WIDTH, 176), (88, 92, 92), -1)
    for x in range(0, WIDTH, 120):
        cv2.rectangle(frame, (x, 40 + (x % 50)), (x + 74, 150), (92 + x % 30, 88, 84), -1)
    for x in range(-40, WIDTH, 130):
        cv2.line(frame, (x, 345), (x + 70, 345), (205, 205, 205), 4)
    return np.clip(frame + rng.normal(0, 4, frame.shape), 0, 255).astype(np.uint8)


def load_vehicle(colour: str) -> np.ndarray:
    """Crop the vehicle body from the Ultralytics sample, excluding bystanders, and recolour it."""
    from ultralytics.utils import ASSETS

    image = cv2.imread(str(ASSETS / "bus.jpg"))
    if image is None:
        raise RuntimeError("Ultralytics sample image is unavailable")
    crop = image[VEHICLE_CROP[1]:VEHICLE_CROP[3], VEHICLE_CROP[0]:VEHICLE_CROP[2]].copy()
    hue, saturation, value = COLOUR_SHIFT[colour]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.float32)
    painted = hsv[:, :, 1] > 70
    hsv[:, :, 0] = np.where(painted, (hsv[:, :, 0] + hue) % 180, hsv[:, :, 0])
    hsv[:, :, 1] = np.where(painted, np.clip(hsv[:, :, 1] * saturation, 0, 255), hsv[:, :, 1])
    hsv[:, :, 2] = np.where(painted, np.clip(hsv[:, :, 2] * value, 0, 255), hsv[:, :, 2])
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def plate_image(text: str, covered: set[int], blur: float) -> np.ndarray:
    plate = np.full((64, 300, 3), 245, dtype=np.uint8)
    cv2.rectangle(plate, (1, 1), (298, 62), (20, 20, 20), 2)
    step = 280 / len(text)
    for index, char in enumerate(text):
        x = int(10 + index * step)
        if index in covered:
            cv2.rectangle(plate, (x - 2, 8), (int(x + step) - 2, 56), (42, 42, 42), -1)
        else:
            cv2.putText(plate, char, (x, 48), cv2.FONT_HERSHEY_DUPLEX, 1.15, (15, 15, 15), 3, cv2.LINE_AA)
    return cv2.GaussianBlur(plate, (0, 0), blur) if blur > 0 else plate


def covered_slots(scenario: Scenario, progress: float) -> set[int]:
    covered = set(scenario.hidden)
    if scenario.moving_cover:
        length = len(scenario.plate)
        # A passing obstruction hides each end for part of the clip, so no single frame is complete.
        covered |= set(range(0, 2)) if progress < 0.5 else set(range(length - 2, length))
    return covered


def draw_vehicle(frame: np.ndarray, vehicle: np.ndarray, x: int, y: int, scale: float, plate: np.ndarray) -> None:
    body = vehicle.copy()
    height, width = body.shape[:2]
    plate_w, plate_h = int(width * 0.62), int(width * 0.62 * 64 / 300)
    px, py = (width - plate_w) // 2, int(height * 0.73)
    body[py:py + plate_h, px:px + plate_w] = cv2.resize(plate, (plate_w, plate_h), interpolation=cv2.INTER_AREA)
    scaled = cv2.resize(body, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = min(scaled.shape[0], HEIGHT - y), min(scaled.shape[1], WIDTH - x)
    shadow = frame.copy()
    cv2.ellipse(shadow, (x + w // 2, min(y + h, HEIGHT - 2)), (int(w * 0.56), 16), 0, 0, 360, (28, 28, 28), -1)
    frame[:] = cv2.addWeighted(shadow, 0.7, frame, 0.3, 0)
    frame[y:y + h, x:x + w] = scaled[:h, :w]


def render(scenario: Scenario, path: Path) -> None:
    rng = np.random.default_rng(scenario.seed)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open an MP4 writer")
    background = road(rng)
    vehicle = load_vehicle(scenario.colour)
    total = int(scenario.seconds * FPS)
    for index in range(total):
        t = index / max(total - 1, 1)
        scale = 0.74 + 0.30 * t
        x = int((70 + 440 * t) if scenario.direction > 0 else (540 - 440 * t))
        y = int(36 + 12 * t)
        frame = background.copy()
        draw_vehicle(frame, vehicle, x, y, scale, plate_image(scenario.plate, covered_slots(scenario, t),
                                                             scenario.plate_blur))
        frame = motion_blur(frame, scenario.motion_blur + int(2 * abs(np.sin(index / 5))))
        frame = cv2.GaussianBlur(frame, (3, 3), 0.7)
        noisy = np.clip(frame + rng.normal(0, 4, frame.shape), 0, 255).astype(np.uint8)
        cv2.rectangle(noisy, (0, 0), (392, 22), (0, 0, 0), -1)
        cv2.putText(noisy, BANNER, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 1, cv2.LINE_AA)
        ok, encoded = cv2.imencode(".jpg", noisy, [cv2.IMWRITE_JPEG_QUALITY, 70])
        writer.write(cv2.imdecode(encoded, cv2.IMREAD_COLOR) if ok else noisy)
    writer.release()


def demo_scenarios() -> list[Scenario]:
    """Six labelled sightings that cover each outcome the workbench must show honestly."""
    registry = build_registry(5000)
    primary = next(row for row in registry if row["plate"] == "MH14GT7319")
    second = next(row for row in registry if row["body_type"] == "bus" and row["colour"] == "red"
                  and len(row["plate"]) == 10 and row["plate"][:2] in {"KA", "GJ", "TN"})
    known = {row["plate"] for row in registry}
    outside = next(plate for plate in ("PB10ZX4821", "OD22QK6604", "KL07VM3915") if plate not in known)
    return [
        Scenario("gate", "synthetic_a_gate.mp4", "A Gate", "North gate", primary["plate"], primary["colour"],
                 "ambiguous_partial", True, hidden=[7, 8, 9], seed=11, link_group="vehicle_1", capture_offset_min=0,
                 latitude=18.5204, longitude=73.8567, expected="AMBIGUOUS",
                 note="Last three characters hidden; two registry plates fit."),
        Scenario("junction", "synthetic_b_junction.mp4", "B Junction", "Ring road", primary["plate"],
                 primary["colour"], "true_partial", True, hidden=[0, 1, 2], seed=22, direction=-1,
                 link_group="vehicle_1", capture_offset_min=6, latitude=18.5310, longitude=73.8740,
                 expected="PLATE_CANDIDATE", note="First three characters hidden; legitimate partial-plate shortlist."),
        Scenario("depot", "synthetic_c_depot.mp4", "C Depot", "Bus depot", second["plate"], second["colour"],
                 "true_partial", True, hidden=[4], moving_cover=True, seed=33, link_group="vehicle_2",
                 capture_offset_min=25, latitude=18.5600, longitude=73.9100, expected="PLATE_CANDIDATE",
                 note="A passing obstruction hides each end in turn; one middle character is never visible."),
        Scenario("ring", "synthetic_d_ring_road.mp4", "D Ring Road", "Ring road east", second["plate"],
                 second["colour"], "true_partial", True, hidden=[0, 1], seed=44, direction=-1, link_group="vehicle_2",
                 capture_offset_min=None, expected="PLATE_CANDIDATE",
                 note="No capture time is supplied, so temporal validation must show as unavailable."),
        Scenario("toll", "synthetic_e_toll.mp4", "E Toll", "Toll plaza", outside, "white", "out_of_registry", False,
                 seed=55, capture_offset_min=40, latitude=18.6000, longitude=73.9500,
                 expected="NO_REGISTRY_MATCH", note="Fully readable plate that is not in the registry."),
        Scenario("car_park", "synthetic_f_car_park.mp4", "F Car Park", "Car park", primary["plate"], "grey",
                 "unreadable", True, plate_blur=7.0, motion_blur=9, seed=66, capture_offset_min=55,
                 latitude=18.6100, longitude=73.9600, expected="UNREADABLE_PLATE",
                 note="Plate is too blurred to read; no character may be invented."),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "demo_clips")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    scenarios = demo_scenarios()
    start = datetime(2026, 11, 20, 10, 0, 0)
    records = []
    for scenario in scenarios:
        render(scenario, args.output / scenario.file)
        item = asdict(scenario)
        item["capture_time_local"] = None if scenario.capture_offset_min is None else \
            (start + timedelta(minutes=scenario.capture_offset_min)).isoformat(timespec="minutes")
        item["timezone"] = None if scenario.capture_offset_min is None else TIMEZONE
        item["plate_format"] = "india_rto"
        records.append(item)
    manifest = {
        "synthetic": True,
        "warning": "Generated test fixture. Plates, vehicles and owners are fictional.",
        "scenarios": records,
    }
    (args.output / "synthetic_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(records)} labelled synthetic clips to {args.output}")


if __name__ == "__main__":
    main()
