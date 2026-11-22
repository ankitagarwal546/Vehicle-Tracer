"""Generate degraded two-camera CCTV test clips with a known ground truth.

The vehicle texture is cropped from the sample photo bundled with Ultralytics. A synthetic
plate is composited on it, then the clip is degraded with motion blur, noise and JPEG loss.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

FPS = 20
WIDTH, HEIGHT = 960, 540
PLATE = "MH14GT7319"
VEHICLE_CROP = (345, 235, 715, 705)


def motion_blur(image: np.ndarray, length: int, horizontal: bool = True) -> np.ndarray:
    if length <= 1:
        return image
    kernel = np.zeros((length, length), dtype=np.float32)
    if horizontal:
        kernel[length // 2, :] = 1
    else:
        kernel[:, length // 2] = 1
    return cv2.filter2D(image, -1, kernel / length)


def road(rng: np.random.Generator, tint: tuple[float, float, float]) -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), 74, dtype=np.uint8)
    frame[:170] = (112, 104, 96)
    cv2.rectangle(frame, (0, 150), (WIDTH, 176), (88, 92, 92), -1)
    for x in range(0, WIDTH, 120):
        cv2.rectangle(frame, (x, 40 + (x % 50)), (x + 74, 150), (92 + x % 30, 88, 84), -1)
    for x in range(-40, WIDTH, 130):
        cv2.line(frame, (x, 345), (x + 70, 345), (205, 205, 205), 4)
    noise = rng.normal(0, 4, frame.shape)
    return np.clip((frame + noise) * np.array(tint), 0, 255).astype(np.uint8)


def plate_image(text: str, visible: tuple[int, int]) -> np.ndarray:
    plate = np.full((64, 300, 3), 245, dtype=np.uint8)
    cv2.rectangle(plate, (1, 1), (298, 62), (20, 20, 20), 2)
    step = 28
    for index, char in enumerate(text):
        if visible[0] <= index < visible[1]:
            cv2.putText(plate, char, (10 + index * step, 48), cv2.FONT_HERSHEY_DUPLEX, 1.15, (15, 15, 15), 3, cv2.LINE_AA)
        else:
            cv2.rectangle(plate, (7 + index * step, 8), (7 + (index + 1) * step, 56), (42, 42, 42), -1)
    return plate


def load_vehicle() -> np.ndarray:
    """Crop the vehicle body from the sample photo bundled with Ultralytics, excluding bystanders."""
    from ultralytics.utils import ASSETS

    image = cv2.imread(str(ASSETS / "bus.jpg"))
    if image is None:
        raise RuntimeError("Ultralytics sample image is unavailable")
    return image[VEHICLE_CROP[1]:VEHICLE_CROP[3], VEHICLE_CROP[0]:VEHICLE_CROP[2]].copy()


def draw_vehicle(frame: np.ndarray, vehicle: np.ndarray, x: int, y: int, scale: float, plate: np.ndarray) -> None:
    body = vehicle.copy()
    height, width = body.shape[:2]
    plate_w, plate_h = int(width * 0.62), int(width * 0.62 * 64 / 300)
    px, py = (width - plate_w) // 2, int(height * 0.73)
    body[py:py + plate_h, px:px + plate_w] = cv2.resize(plate, (plate_w, plate_h), interpolation=cv2.INTER_AREA)
    scaled = cv2.resize(body, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = scaled.shape[:2]
    h = min(h, HEIGHT - y)
    w = min(w, WIDTH - x)
    shadow = frame.copy()
    cv2.ellipse(shadow, (x + w // 2, min(y + h, HEIGHT - 2)), (int(w * 0.56), 16), 0, 0, 360, (28, 28, 28), -1)
    frame[:] = cv2.addWeighted(shadow, 0.7, frame, 0.3, 0)
    frame[y:y + h, x:x + w] = scaled[:h, :w]


def render_camera(path: Path, seed: int, visible: tuple[int, int], tint, blur: int, direction: int,
                  plate_text: str, seconds: float = 6.0) -> None:
    rng = np.random.default_rng(seed)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open an MP4 writer")
    background = road(rng, tint)
    vehicle = load_vehicle()
    total = int(seconds * FPS)
    for index in range(total):
        t = index / max(total - 1, 1)
        scale = 0.74 + 0.30 * t
        x = int((70 + 440 * t) if direction > 0 else (540 - 440 * t))
        y = int(36 + 12 * t)
        frame = background.copy()
        draw_vehicle(frame, vehicle, x, y, scale, plate_image(plate_text, visible))
        amount = blur + int(3 * abs(np.sin(index / 5)))
        frame = motion_blur(frame, amount)
        frame = cv2.GaussianBlur(frame, (3, 3), 0.7)
        noisy = np.clip(frame + rng.normal(0, 5, frame.shape), 0, 255).astype(np.uint8)
        ok, encoded = cv2.imencode(".jpg", noisy, [cv2.IMWRITE_JPEG_QUALITY, 62])
        writer.write(cv2.imdecode(encoded, cv2.IMREAD_COLOR) if ok else noisy)
    writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "demo_clips")
    parser.add_argument("--plate", default=PLATE)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plate = args.plate.upper()
    render_camera(args.output / "camera_a_gate.mp4", 11, (0, 7), (0.82, 0.95, 1.12), 7, 1, plate)
    render_camera(args.output / "camera_b_junction.mp4", 22, (3, len(plate)), (1.05, 1.0, 0.92), 8, -1, plate)
    truth = {"plate": plate, "colour": "blue", "body_type": "bus",
             "camera_a_visible": plate[:7] + "?" * (len(plate) - 7),
             "camera_b_visible": "?" * 3 + plate[3:]}
    (args.output / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    print(f"Wrote clips and ground truth to {args.output}")


if __name__ == "__main__":
    main()
