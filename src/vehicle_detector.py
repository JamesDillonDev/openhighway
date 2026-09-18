"""Single-frame vehicle detection using OpenCV Zoo's YOLOX-s ONNX model
(https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox,
Apache 2.0). Preprocessing/postprocessing mirrors that repo's own yolox.py
and demo.py as closely as possible since it's tested, working reference code.

Unlike the earlier background-subtraction approach, this needs no frame
history or per-camera warmup - it detects vehicles directly in one image,
so it works even on camera feeds that refresh rarely or never.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.request import urlretrieve

import cv2
import numpy as np

logger = logging.getLogger("openhighway.vehicle_detector")

# The opencv_zoo repo tracks this file via git-lfs, so a plain raw.githubusercontent
# URL only returns the LFS pointer text - the media endpoint resolves the
# actual binary.
_MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/object_detection_yolox/object_detection_yolox_2022nov.onnx"
)

_STRIDES = (8, 16, 32)

# Standard COCO 80-class order, matching the model's training labels.
COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)

VEHICLE_CLASSES = {"car", "motorcycle", "bus", "truck"}
VEHICLE_CLASS_IDS = {i for i, name in enumerate(COCO_CLASSES) if name in VEHICLE_CLASSES}


def _ensure_downloaded(dest: Path) -> None:

    if dest.exists():
        return

    logger.info("Downloading vehicle detection model -> %s", dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_dest = dest.with_suffix(dest.suffix + ".part")
    urlretrieve(_MODEL_URL, tmp_dest)
    tmp_dest.rename(dest)


def _letterbox(image: np.ndarray, size: int) -> np.ndarray:
    """Resize keeping aspect ratio, padding the rest with grey - matches how
    the model was trained/benchmarked upstream."""

    padded = np.full((size, size, 3), 114.0, dtype=np.float32)
    ratio = min(size / image.shape[0], size / image.shape[1])

    resized = cv2.resize(
        image, (int(image.shape[1] * ratio), int(image.shape[0] * ratio)),
        interpolation=cv2.INTER_LINEAR,
    ).astype(np.float32)

    padded[: resized.shape[0], : resized.shape[1]] = resized

    return padded


def _normalise_contrast(bgr: np.ndarray) -> np.ndarray:
    """Boost local contrast on the luminance channel only (CLAHE) - traffic
    cameras are frequently hazy, backlit or shot at night, and low contrast
    hides vehicles from the detector. Cheap (a few ms) next to inference."""

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)

    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


class VehicleDetector:
    """Loads the model once and reuses it for every frame - stateless per
    camera, unlike a background subtractor."""

    def __init__(
        self,
        model_dir: Path,
        input_size: int = 640,
        confidence_threshold: float = 0.5,
        nms_threshold: float = 0.5,
    ) -> None:

        model_path = model_dir / "yolox_s.onnx"
        _ensure_downloaded(model_path)

        self.net = cv2.dnn.readNet(str(model_path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

        self.input_size = (input_size, input_size)
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold

        self.grids, self.expanded_strides = self._generate_anchors()

    def _generate_anchors(self):

        hsizes = [self.input_size[0] // stride for stride in _STRIDES]
        wsizes = [self.input_size[1] // stride for stride in _STRIDES]

        grids = []
        expanded_strides = []

        for hsize, wsize, stride in zip(hsizes, wsizes, _STRIDES):

            xv, yv = np.meshgrid(np.arange(hsize), np.arange(wsize))
            grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
            grids.append(grid)
            expanded_strides.append(np.full((*grid.shape[:2], 1), stride))

        return np.concatenate(grids, 1), np.concatenate(expanded_strides, 1)

    def count_vehicles(self, frame: np.ndarray) -> int:

        frame = _normalise_contrast(frame)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        padded = _letterbox(rgb, self.input_size[0])

        blob = np.transpose(padded, (2, 0, 1))[np.newaxis, :, :, :]

        self.net.setInput(blob)
        output = self.net.forward(self.net.getUnconnectedOutLayersNames())[0]

        dets = output[0]
        dets[:, :2] = (dets[:, :2] + self.grids) * self.expanded_strides
        dets[:, 2:4] = np.exp(dets[:, 2:4]) * self.expanded_strides

        boxes = dets[:, :4]
        boxes_xywh = np.empty_like(boxes)
        boxes_xywh[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
        boxes_xywh[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
        boxes_xywh[:, 2] = boxes[:, 2]
        boxes_xywh[:, 3] = boxes[:, 3]

        scores = dets[:, 4:5] * dets[:, 5:]
        max_scores = np.amax(scores, axis=1)
        max_class_ids = np.argmax(scores, axis=1)

        # Restrict to vehicle classes before NMS - class-aware NMS treats
        # classes independently, so this can't change which vehicle boxes
        # survive, it just skips scoring/suppressing irrelevant ones.
        is_vehicle = np.isin(max_class_ids, list(VEHICLE_CLASS_IDS))
        keep_mask = is_vehicle & (max_scores >= self.confidence_threshold)

        if not np.any(keep_mask):
            return 0

        indices = cv2.dnn.NMSBoxesBatched(
            boxes_xywh[keep_mask].tolist(),
            max_scores[keep_mask].tolist(),
            max_class_ids[keep_mask].tolist(),
            self.confidence_threshold,
            self.nms_threshold,
        )

        return len(indices)

