"""
Local, CPU-only detection stage. Finds candidate text regions on book spines
so we only send small crops to the (expensive) hosted VLM, instead of the
whole shelf photo per book.

Model: OpenCV's EAST text detector (frozen_east_text_detection.pb), a
pretrained off-the-shelf text-region detector. No spine-specific model
exists off-the-shelf, so we detect text blobs directly -- spine text is
what we actually need to read anyway. CPU inference, no training.

Weights are not committed (96MB); see scripts/download_weights.py.

TILING: EAST takes a fixed 320x320 input. Naively resizing a full shelf
photo (e.g. 857x1200) down to 320x320 shrinks spine letters to ~1-2px --
below what the model can see (verified: whole-image confidence maxed out
at 0.0002 on a real test photo, i.e. nothing detected). Instead we slide
a 320x320 window across the image at native resolution (no downscale per
tile) with overlap, run EAST on each tile, map results back to original
coordinates, then run one global NMS + merge pass across all tiles. This
is the fix that took real-photo confidence from ~0 to ~1.0 on the same
text.
"""
import os
import cv2
import numpy as np

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights", "frozen_east_text_detection.pb")

# EAST requires input dims that are multiples of 32.
INPUT_W, INPUT_H = 320, 320
TILE_STRIDE = 240  # 25% overlap between adjacent tiles, so text spanning
                    # a tile boundary still appears whole in a neighbor
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


def _tile_origins(length, tile_size, stride):
    """Top-left origins covering [0, length) with the given tile size and
    stride, always including a final tile flush with the far edge so
    nothing past the last full stride gets skipped."""
    if length <= tile_size:
        return [0]
    origins = list(range(0, length - tile_size + 1, stride))
    last = length - tile_size
    if origins[-1] != last:
        origins.append(last)
    return origins


def _run_east_on_tile(net, tile):
    """Run EAST on a single tile already at exactly INPUT_W x INPUT_H (no
    resize -- that's the whole point of tiling). Returns raw boxes in
    tile-local pixel coordinates plus confidences."""
    blob = cv2.dnn.blobFromImage(
        tile, 1.0, (INPUT_W, INPUT_H),
        (123.68, 116.78, 103.94), swapRB=True, crop=False,
    )
    net.setInput(blob)
    scores, geometry = net.forward([
        "feature_fusion/Conv_7/Sigmoid",
        "feature_fusion/concat_3",
    ])
    return _decode_predictions(scores, geometry)


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
    net = _get_net()

    x_origins = _tile_origins(orig_w, INPUT_W, TILE_STRIDE)
    y_origins = _tile_origins(orig_h, INPUT_H, TILE_STRIDE)

    all_boxes, all_confidences = [], []
    for ty in y_origins:
        for tx in x_origins:
            tile = img[ty:ty + INPUT_H, tx:tx + INPUT_W]
            th, tw = tile.shape[:2]
            if th < INPUT_H or tw < INPUT_W:
                # only happens if the image itself is smaller than one tile
                tile = cv2.copyMakeBorder(
                    tile, 0, INPUT_H - th, 0, INPUT_W - tw,
                    cv2.BORDER_REPLICATE,
                )
            boxes, confidences = _run_east_on_tile(net, tile)
            for (sx, sy, ex, ey), conf in zip(boxes, confidences):
                all_boxes.append((sx + tx, sy + ty, ex + tx, ey + ty))
                all_confidences.append(conf)

    if not all_boxes:
        return []

    indices = cv2.dnn.NMSBoxes(all_boxes, all_confidences, CONF_THRESHOLD, NMS_THRESHOLD)
    if indices is None or len(indices) == 0:
        return []

    raw_boxes = [all_boxes[i] for i in np.array(indices).flatten()]

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


def _merge_by_x_overlap(boxes, orig_h):
    """Union boxes into spine-level regions. Spine text stacks vertically
    within a narrow x-band with small gaps between words/lines, so we merge
    boxes that are BOTH close in x (same column) AND close in y (same
    shelf row) -- x-overlap alone was found to chain word-boxes down
    multiple shelves into a single giant strip on a real test photo, since
    a tall bookcase can have several spines that happen to line up in x.
    Union-Find over pairwise proximity, not a single sorted-sweep, so it
    isn't order-dependent."""
    if not boxes:
        return []

    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    x_gap = orig_h * 0.02  # small absolute tolerance, image-scale
    for i in range(n):
        x1i, y1i, x2i, y2i = boxes[i]
        for j in range(i + 1, n):
            x1j, y1j, x2j, y2j = boxes[j]
            x_close = x1i <= x2j + x_gap and x1j <= x2i + x_gap
            if not x_close:
                continue
            # y gap allowed scales with the boxes' own height -- word-to-word
            # spacing within a spine title, not shelf-to-shelf spacing.
            y_gap_allowed = max(y2i - y1i, y2j - y1j) * 1.5
            y_close = y1i <= y2j + y_gap_allowed and y1j <= y2i + y_gap_allowed
            if y_close:
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(boxes[i])

    merged = []
    for group in groups.values():
        x1 = min(b[0] for b in group)
        y1 = min(b[1] for b in group)
        x2 = max(b[2] for b in group)
        y2 = max(b[3] for b in group)
        merged.append((x1, y1, x2, y2))
    return merged
