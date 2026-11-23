"""YOLOv8 vehicle detection with ByteTrack identity assignment."""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.config import settings
from app.cv.device import active_device
from app.cv.track_stitcher import StitchDecision
from app.cv.video_processor import SampledFrame, sharpness_score

logger = logging.getLogger(__name__)

COCO_VEHICLES = {2: "car", 3: "two-wheeler", 5: "bus", 7: "truck"}
MIN_BOX_AREA_RATIO = 0.0015
KEEP_OBSERVATIONS = 16
CROP_MARGIN = 0.06
EDGE_MARGIN_PX = 3
TRUNCATED_RANK_FACTOR = 0.35
MAX_SCENE_WIDTH = 1280
TRACKER_CONFIG = Path(__file__).with_name("bytetrack_forensic.yaml")
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
    scene_scale: float = 1.0
    truncated: bool = False
    lower_occlusion: float = 0.0
    occluders_in_crop: list[tuple[int, int, int, int]] = field(default_factory=list)
    target_in_crop: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class VehicleTrack:
    track_id: int
    first_seen_sec: float
    last_seen_sec: float
    frames_tracked: int = 0
    truncated_frames: int = 0
    class_votes: Counter = field(default_factory=Counter)
    trajectory: list[tuple[float, tuple[int, int, int, int]]] = field(default_factory=list)
    merged_track_ids: list[int] = field(default_factory=list)
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

    @property
    def mostly_truncated(self) -> bool:
        return self.frames_tracked > 0 and self.truncated_frames / self.frames_tracked >= 0.8

    def _keep(self, observation: TrackObservation) -> None:
        area = (observation.bbox[2] - observation.bbox[0]) * (observation.bbox[3] - observation.bbox[1])
        rank = observation.sharpness * np.sqrt(max(area, 1))
        if observation.truncated:
            rank *= TRUNCATED_RANK_FACTOR
        # The plate sits low on a vehicle, so prefer frames where that area is unobstructed.
        rank *= (1.0 - observation.lower_occlusion) ** 2 + 0.02
        entry = (rank, next(_tiebreak), observation)
        if len(self._heap) < KEEP_OBSERVATIONS:
            heapq.heappush(self._heap, entry)
        elif rank > self._heap[0][0]:
            heapq.heapreplace(self._heap, entry)

    def add(self, observation: TrackObservation, label: str, score: float) -> None:
        self.frames_tracked += 1
        self.truncated_frames += observation.truncated
        self.last_seen_sec = max(self.last_seen_sec, observation.timestamp_sec)
        self.first_seen_sec = min(self.first_seen_sec, observation.timestamp_sec)
        self.class_votes[label] += score
        self.trajectory.append((observation.timestamp_sec, observation.bbox))
        self._keep(observation)

    def absorb(self, other: "VehicleTrack") -> None:
        shared = {round(t, 3) for t, _ in self.trajectory} & {round(t, 3) for t, _ in other.trajectory}
        self.frames_tracked += other.frames_tracked - len(shared)
        self.truncated_frames += other.truncated_frames
        self.truncated_frames = min(self.truncated_frames, self.frames_tracked)
        self.first_seen_sec = min(self.first_seen_sec, other.first_seen_sec)
        self.last_seen_sec = max(self.last_seen_sec, other.last_seen_sec)
        self.class_votes.update(other.class_votes)
        known = {round(t, 3) for t, _ in self.trajectory}
        self.trajectory = sorted(self.trajectory + [p for p in other.trajectory if round(p[0], 3) not in known],
                                 key=lambda p: p[0])
        self.merged_track_ids = sorted({*self.merged_track_ids, *other.merged_track_ids, other.track_id})
        seen_frames = {entry[2].frame_idx for entry in self._heap}
        for _, _, observation in other._heap:
            if observation.frame_idx not in seen_frames:
                self._keep(observation)


def is_in_front(other: tuple[int, int, int, int], box: tuple[int, int, int, int]) -> bool:
    """On an elevated camera, the overlapping vehicle with the lower bottom edge is nearer."""
    overlaps = min(other[2], box[2]) > max(other[0], box[0]) and min(other[3], box[3]) > max(other[1], box[1])
    return overlaps and other[3] > box[3]


def lower_occlusion(box: tuple[int, int, int, int], in_front: list[tuple[int, int, int, int]]) -> float:
    """Fraction of the lower half of ``box`` hidden by nearer vehicles."""
    x1, y1, x2, y2 = box
    top = (y1 + y2) // 2
    width, height = max(x2 - x1, 1), max(y2 - top, 1)
    mask = np.zeros((height, width), dtype=bool)
    for a, b, c, d in in_front:
        mask[max(b - top, 0):max(d - top, 0), max(a - x1, 0):max(c - x1, 0)] = True
    return float(mask.mean())


def apply_stitching(tracks: list[VehicleTrack], decisions: list[StitchDecision]) -> list[VehicleTrack]:
    by_id = {track.track_id: track for track in tracks}
    roots: dict[int, int] = {}
    for decision in decisions:
        roots[decision.merged] = decision.kept

    def root(track_id: int) -> int:
        while track_id in roots:
            track_id = roots[track_id]
        return track_id

    for decision in decisions:
        by_id[root(decision.kept)].absorb(by_id[decision.merged])
    merged = {decision.merged for decision in decisions}
    return sorted((t for t in tracks if t.track_id not in merged), key=lambda t: (t.first_seen_sec, t.track_id))


class VehicleDetectorTracker:
    def __init__(self) -> None:
        from ultralytics import YOLO

        self.device = active_device()
        accelerated = self.device != "cpu"
        name = settings.yolo_model if settings.yolo_model != "auto" else ("yolov8s.pt" if accelerated else "yolov8n.pt")
        self.weights_name = name
        self.imgsz = settings.yolo_imgsz or (960 if accelerated else 640)
        self.model = YOLO(str(settings.model_dir / name))
        self._lock = threading.Lock()

    def _track(self, image: np.ndarray):
        kwargs = dict(
            persist=True, tracker=str(TRACKER_CONFIG), classes=list(COCO_VEHICLES), conf=settings.yolo_conf,
            imgsz=self.imgsz, agnostic_nms=True, verbose=False,
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
        return sorted(tracks.values(), key=lambda track: track.first_seen_sec)

    @staticmethod
    def _collect(result, frame: SampledFrame, tracks: dict[int, VehicleTrack]) -> None:
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            return
        height, width = frame.image.shape[:2]
        min_area = width * height * MIN_BOX_AREA_RATIO
        frame_jpeg: bytes | None = None
        scene_scale = min(MAX_SCENE_WIDTH / width, 1.0)
        all_boxes = [tuple(int(round(v)) for v in xyxy) for xyxy in boxes.xyxy.cpu().numpy()]
        for index, (xyxy, track_id, cls, conf) in enumerate(zip(
            all_boxes, boxes.id.int().cpu().numpy(),
            boxes.cls.int().cpu().numpy(), boxes.conf.cpu().numpy(),
        )):
            x1, y1, x2, y2 = xyxy
            if (x2 - x1) * (y2 - y1) < min_area:
                continue
            margin_x, margin_y = int((x2 - x1) * CROP_MARGIN), int((y2 - y1) * CROP_MARGIN)
            cx1, cy1 = max(x1 - margin_x, 0), max(y1 - margin_y, 0)
            cx2, cy2 = min(x2 + margin_x, width), min(y2 + margin_y, height)
            crop = frame.image[cy1:cy2, cx1:cx2].copy()
            if crop.size == 0:
                continue
            if frame_jpeg is None:
                scene = frame.image if scene_scale >= 1 else cv2.resize(
                    frame.image, None, fx=scene_scale, fy=scene_scale, interpolation=cv2.INTER_AREA)
                frame_jpeg = cv2.imencode(".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tobytes()
            truncated = x1 <= EDGE_MARGIN_PX or y1 <= EDGE_MARGIN_PX \
                or x2 >= width - EDGE_MARGIN_PX or y2 >= height - EDGE_MARGIN_PX
            in_front = [other for j, other in enumerate(all_boxes) if j != index and is_in_front(other, xyxy)]
            occluders = [(a - cx1, b - cy1, c - cx1, d - cy1) for a, b, c, d in in_front]
            track = tracks.setdefault(
                int(track_id), VehicleTrack(int(track_id), frame.timestamp_sec, frame.timestamp_sec)
            )
            track.add(
                TrackObservation(frame.frame_idx, frame.timestamp_sec, (x1, y1, x2, y2), float(conf),
                                 sharpness_score(crop), crop, frame_jpeg, scene_scale, truncated,
                                 lower_occlusion(xyxy, in_front), occluders,
                                 (x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1)),
                COCO_VEHICLES[int(cls)], float(conf),
            )
