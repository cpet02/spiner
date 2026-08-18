"""
Local, CPU-only detection stage. Finds candidate text regions on book spines
so we only send small crops to the (expensive) hosted VLM, instead of the
whole shelf photo per book.

Model: OpenCV's EAST text detector (frozen_east_text_detection.pb), a
pretrained off-the-shelf text-region detector. No spine-specific model
exists off-the-shelf, so we detect text blobs directly -- spine text is
what we actually need to read anyway. CPU inference, no training.

Weights are not committed (96MB); see scripts/download_weights.py.
"""
import os
import cv2
import numpy as np

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights", "frozen_east_text_detection.pb")

# EAST requires input dims that are multiples of 32.
INPUT_W, INPUT_H = 320, 320
CONF_THRESHOLD = 0.5
NMS_THRESHOLD = 0.4

_net = None


class DetectorError(Exception):
    pass


def _get_net():
    global _net
    if _net is None:
        if not os.path.exists(WEIGHTS_PATH):
            raise DetectorError(
                f"EAST weights not found at {WEIGHTS_PATH}. Run scripts/download_weights.py."
            )
        _net = cv2.dnn.readNet(WEIGHTS_PATH)
    return _net


def _decode_predictions(scores, geometry):
    boxes, confidences = [], []
    rows, cols = scores.shape[2], scores.shape[3]
    for y in range(rows):
        scores_row = scores[0, 0, y]
        x0, x1, x2, x3 = (geometry[0, i, y] for i in range(4))
        angles_row = geometry[0, 4, y]
        for x in range(cols):
            if scores_row[x] < CONF_THRESHOLD:
                continue
            offset_x, offset_y = x * 4.0, y * 4.0
            angle = angles_row[x]
            cos, sin = np.cos(angle), np.sin(angle)
            h = x0[x] + x2[x]
            w = x1[x] + x3[x]
            end_x = offset_x + (cos * x1[x]) + (sin * x2[x])
            end_y = offset_y - (sin * x1[x]) + (cos * x2[x])
            start_x = end_x - w
            start_y = end_y - h
            boxes.append((start_x, start_y, end_x, end_y))
            confidences.append(float(scores_row[x]))
    return boxes, confidences


def detect_regions(image_bytes: bytes, pad_frac: float = 0.15):
    """Detect candidate text regions in a shelf photo.

    Returns a list of dicts: {"crop": jpeg_bytes, "box": (x1,y1,x2,y2)},
    in the ORIGINAL image's pixel coordinates. Returns [] (never raises
    on "found nothing") if no regions clear the confidence threshold --
    callers must treat an empty list as a valid, handleable outcome.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise DetectorError("Could not decode image bytes")

    orig_h, orig_w = img.shape[:2]
    rW, rH = orig_w / float(INPUT_W), orig_h / float(INPUT_H)

    blob = cv2.dnn.blobFromImage(
        img, 1.0, (INPUT_W, INPUT_H),
        (123.68, 116.78, 103.94), swapRB=True, crop=False,
    )
    net = _get_net()
    net.setInput(blob)
    scores, geometry = net.forward([
        "feature_fusion/Conv_7/Sigmoid",
        "feature_fusion/concat_3",
    ])

    boxes, confidences = _decode_predictions(scores, geometry)
    if not boxes:
        return []

    indices = cv2.dnn.NMSBoxes(boxes, confidences, CONF_THRESHOLD, NMS_THRESHOLD)
    if indices is None or len(indices) == 0:
        return []

    raw_boxes = []
    for i in np.array(indices).flatten():
        sx, sy, ex, ey = boxes[i]
        x1, y1, x2, y2 = sx * rW, sy * rH, ex * rW, ey * rH
        raw_boxes.append((x1, y1, x2, y2))

    # EAST finds individual words/text lines, not whole spines. Book titles
    # on a spine are usually stacked as several separate word-boxes in the
    # same vertical column, so we merge boxes whose x-ranges overlap into a
    # single spine-level region before cropping. This is the difference
    # between "1 crop per book" and "1 crop per word" -- directly controls
    # how many VLM calls (i.e. how much $) we spend per photo.
    merged = _merge_by_x_overlap(raw_boxes, orig_h)

    results = []
    for x1, y1, x2, y2 in merged:
        pad_x, pad_y = (x2 - x1) * pad_frac, (y2 - y1) * pad_frac
        x1 = max(0, int(x1 - pad_x))
        y1 = max(0, int(y1 - pad_y))
        x2 = min(orig_w, int(x2 + pad_x))
        y2 = min(orig_h, int(y2 + pad_y))
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img[y1:y2, x1:x2]
        ok, enc = cv2.imencode(".jpg", crop)
        if not ok:
            continue
        results.append({"crop": enc.tobytes(), "box": (x1, y1, x2, y2)})

    return results


def _merge_by_x_overlap(boxes, orig_h, x_gap_frac=0.02):
    """Union boxes whose x-ranges overlap (or nearly touch) into one region
    spanning their combined extent. Spine text stacks vertically within a
    narrow x-band, so this collapses per-word boxes into per-spine boxes."""
    if not boxes:
        return []
    x_gap = orig_h * x_gap_frac  # small absolute tolerance, image-scale
    boxes = sorted(boxes, key=lambda b: b[0])
    merged = [list(boxes[0])]
    for x1, y1, x2, y2 in boxes[1:]:
        last = merged[-1]
        if x1 <= last[2] + x_gap:
            last[0] = min(last[0], x1)
            last[1] = min(last[1], y1)
            last[2] = max(last[2], x2)
            last[3] = max(last[3], y2)
        else:
            merged.append([x1, y1, x2, y2])
    return [tuple(b) for b in merged]
