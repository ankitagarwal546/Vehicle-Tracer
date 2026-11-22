"""YOLOv8 vehicle detection with ByteTrack identity assignment."""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings
from app.cv.device import active_device
from app.cv.video_processor import SampledFrame, sharpness_score

logger = logging.getLogger(__name__)

COCO_VEHICLES = {2: "car", 3: "two-wheeler", 5: "bus", 7: "truck"}
MIN_BOX_AREA_RATIO = 0.002
KEEP_OBSERVATIONS = 12
CROP_MARGIN = 0.06
_tiebreak = itertools.count()


@dataclass
class TrackObservation:
    frame_idx: int
    timestamp_sec: float
    bbox: tuple[int, int, int, int]
    confidence: float
    sharpness: float
    crop: np.ndarray
    frame_jpeg: bytes


@dataclass
class VehicleTrack:
    track_id: int
    first_seen_sec: float
    last_seen_sec: float
    frames_tracked: int = 0
    class_votes: Counter = field(default_factory=Counter)
    _heap: list = field(default_factory=list)

    @property
    def yolo_class(self) -> str:
        return self.class_votes.most_common(1)[0][0]

    @property
    def yolo_confidence(self) -> float:
        total = sum(self.class_votes.values())
        return self.class_votes[self.yolo_class] / total if total else 0.0

    @property
    def observations(self) -> list[TrackObservation]:
        return [item[2] for item in sorted(self._heap, key=lambda entry: -entry[0])]

    def add(self, observation: TrackObservation, label: str, score: float) -> None:
        self.frames_tracked += 1
        self.last_seen_sec = max(self.last_seen_sec, observation.timestamp_sec)
        self.first_seen_sec = min(self.first_seen_sec, observation.timestamp_sec)
        self.class_votes[label] += score
        area = (observation.bbox[2] - observation.bbox[0]) * (observation.bbox[3] - observation.bbox[1])
        rank = observation.sharpness * np.sqrt(max(area, 1))
        entry = (rank, next(_tiebreak), observation)
        if len(self._heap) < KEEP_OBSERVATIONS:
            heapq.heappush(self._heap, entry)
        elif rank > self._heap[0][0]:
            heapq.heapreplace(self._heap, entry)


class VehicleDetectorTracker:
    def __init__(self) -> None:
        from ultralytics import YOLO

        weights = settings.model_dir / settings.yolo_model
        self.model = YOLO(str(weights))
        self.device = active_device()
        self._lock = threading.Lock()

    def _track(self, image: np.ndarray):
        kwargs = dict(
            persist=True, tracker="bytetrack.yaml", classes=list(COCO_VEHICLES), conf=settings.yolo_conf,
            imgsz=settings.yolo_imgsz, verbose=False,
        )
        try:
            return self.model.track(image, device=self.device, **kwargs)[0]
        except (RuntimeError, NotImplementedError) as error:
            if self.device == "cpu":
                raise
            logger.warning("Tracking failed on %s (%s). Falling back to CPU.", self.device, error)
            self.device = "cpu"
            return self.model.track(image, device="cpu", **kwargs)[0]

    def track_clip(
        self,
        frames: Iterable[SampledFrame],
        on_frame: Callable[[int], None] | None = None,
    ) -> list[VehicleTrack]:
        with self._lock:
            self.model.predictor = None  # Track IDs must not leak between cameras.
            tracks: dict[int, VehicleTrack] = {}
            for count, frame in enumerate(frames, start=1):
                result = self._track(frame.image)
                self._collect(result, frame, tracks)
                if on_frame:
                    on_frame(count)
            self.model.predictor = None
        kept = [track for track in tracks.values() if track.frames_tracked >= settings.min_track_frames]
        return sorted(kept, key=lambda track: track.first_seen_sec)

    @staticmethod
    def _collect(result, frame: SampledFrame, tracks: dict[int, VehicleTrack]) -> None:
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            return
        height, width = frame.image.shape[:2]
        min_area = width * height * MIN_BOX_AREA_RATIO
        frame_jpeg: bytes | None = None
        for xyxy, track_id, cls, conf in zip(
            boxes.xyxy.cpu().numpy(), boxes.id.int().cpu().numpy(),
            boxes.cls.int().cpu().numpy(), boxes.conf.cpu().numpy(),
        ):
            x1, y1, x2, y2 = (int(round(v)) for v in xyxy)
            if (x2 - x1) * (y2 - y1) < min_area:
                continue
            margin_x, margin_y = int((x2 - x1) * CROP_MARGIN), int((y2 - y1) * CROP_MARGIN)
            cx1, cy1 = max(x1 - margin_x, 0), max(y1 - margin_y, 0)
            cx2, cy2 = min(x2 + margin_x, width), min(y2 + margin_y, height)
            crop = frame.image[cy1:cy2, cx1:cx2].copy()
            if crop.size == 0:
                continue
            if frame_jpeg is None:
                frame_jpeg = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tobytes()
            track = tracks.setdefault(
                int(track_id), VehicleTrack(int(track_id), frame.timestamp_sec, frame.timestamp_sec)
            )
            track.add(
                TrackObservation(frame.frame_idx, frame.timestamp_sec, (x1, y1, x2, y2), float(conf),
                                 sharpness_score(crop), crop, frame_jpeg),
                COCO_VEHICLES[int(cls)], float(conf),
            )
