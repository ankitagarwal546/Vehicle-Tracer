import cv2
import numpy as np
import pytest

from app.cv.attributes import estimate_colour, gray_world
from app.cv.plate_ocr import enhance_plate
from app.cv.video_processor import sharpness_score


def vehicle(bgr, glass=True):
    image = np.full((200, 300, 3), bgr, dtype=np.uint8)
    if glass:
        image[60:115, 30:270] = (28, 26, 24)
    return np.clip(image + np.random.default_rng(0).normal(0, 3, image.shape), 0, 255).astype(np.uint8)


@pytest.mark.parametrize("bgr,label", [
    ((175, 80, 20), "blue"), ((35, 35, 185), "red"), ((240, 240, 240), "white"), ((24, 24, 24), "black"),
])
def test_colour_ignores_glass_and_keeps_paint(bgr, label):
    assert estimate_colour([vehicle(bgr)])[0]["label"] == label


def test_colour_probabilities_are_top_two():
    result = estimate_colour([vehicle((175, 80, 20))])
    assert len(result) == 2 and result[0]["confidence"] >= result[1]["confidence"]


def test_gray_world_reduces_sodium_cast():
    scene = np.zeros((90, 90, 3), dtype=np.uint8)
    scene[:30], scene[30:60], scene[60:] = (200, 60, 60), (60, 200, 60), (60, 60, 200)
    cast = np.clip(scene * np.array([0.65, 0.95, 1.3]), 0, 255).astype(np.uint8)
    before = cast.reshape(-1, 3).mean(axis=0)
    after = gray_world(cast).reshape(-1, 3).mean(axis=0)
    assert np.ptp(after) < np.ptp(before)


def test_white_vehicle_recovers_under_sodium_light_with_scene_context():
    gains = np.array([0.62, 0.92, 1.25])
    crop = np.clip(vehicle((225, 225, 225), glass=False) * gains, 0, 255).astype(np.uint8)
    scene = np.clip(np.full((270, 480, 3), 105, dtype=np.uint8) * gains, 0, 255).astype(np.uint8)
    scene[60:260, 90:390] = crop
    assert estimate_colour([crop], scenes=[scene])[0]["label"] in {"white", "silver"}


def test_enhancement_upscales_and_adds_detail():
    plate = np.full((30, 120, 3), 225, dtype=np.uint8)
    cv2.putText(plate, "MH12", (6, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
    blurred = cv2.GaussianBlur(plate, (5, 5), 1.2)
    enhanced = enhance_plate(blurred)
    assert enhanced.shape[:2] == (60, 240)
    assert sharpness_score(cv2.resize(enhanced, (120, 30), interpolation=cv2.INTER_AREA)) > sharpness_score(blurred)
