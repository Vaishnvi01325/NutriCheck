"""
OCR Service — NutriCheck
=========================
Provides both standard text OCR and spatially-aware OCR that returns
bounding boxes for table-structured nutrition label parsing.

The key insight: food labels use a TWO/THREE-COLUMN table format:
   [Nutrient Label]  |  [gram value]  |  [% Daily Value]
We MUST pick the gram column, NOT the %DV column.

Multi-pass strategy (3 targeted passes, merged by bounding-box confidence voting):
  Pass 1: Detail mode, balanced thresholds → catches most label text
  Pass 2: Paragraph mode → catches faint/closely-spaced rows
  Pass 3: Very low contrast_ths → catches low-contrast numbers on coloured labels

Critical improvements in this version:
  - Resolution raised from 1000px → 1800px (longest side)
  - text_threshold lowered to 0.3, low_text to 0.2 for better recall
  - link_threshold=0.4 to prevent words merging across columns
  - % Daily Value column auto-detection and exclusion
  - Percent-only tokens (e.g. "12%") explicitly excluded from numeric parsing
  - Stronger CLAHE + unsharp mask for blurry/dark photos
"""

import cv2
import numpy as np
import easyocr
from config import OCR_LANGUAGES, OCR_GPU

# Lazy-loaded global reader
_reader = None


def get_reader():
    """Get or initialize the EasyOCR reader (lazy singleton)."""
    global _reader
    if _reader is None:
        _reader = warm_up()
    return _reader


def warm_up():
    """Download and initialize EasyOCR model weights into memory."""
    global _reader
    if _reader is not None:
        return _reader

    print("[NutriCheck OCR] Warming up EasyOCR models (this may take a minute on first run)…")
    try:
        _reader = easyocr.Reader(OCR_LANGUAGES, gpu=OCR_GPU)
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        _reader.readtext(dummy)
        print("[NutriCheck OCR] Models loaded and ready.")
    except Exception as e:
        print(f"[NutriCheck OCR] Warm-up failed: {e}")
        _reader = easyocr.Reader(OCR_LANGUAGES, gpu=OCR_GPU)
    return _reader


# ─────────────────────────────────────────────────────────
# Core Preprocessing
# ─────────────────────────────────────────────────────────

def _strong_preprocess(image_path: str) -> tuple[np.ndarray, int, int]:
    """
    Strong preprocessing pipeline purpose-built for nutrition label OCR.

    Steps:
    1. Load + resize so longest dimension = 1800px (optimal for EasyOCR accuracy)
    2. White border padding — prevents edge-clipping of rightmost values
    3. Grayscale conversion
    4. CLAHE contrast enhancement — equalises uneven phone lighting
    5. Unsharp mask sharpening — recovers blurry label text
    6. Adaptive threshold (blockSize=15, C=8) — better separation for small text

    Returns: (preprocessed_img, width, height)
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    # 1. Resize so longest side = 1800px — critical for small digit accuracy
    h, w = img.shape[:2]
    target = 1800
    scale = target / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    elif scale > 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    h, w = img.shape[:2]

    # 2. White border padding — text at the edge of a crop is often clipped
    BORDER = 30
    img = cv2.copyMakeBorder(img, BORDER, BORDER, BORDER, BORDER,
                              cv2.BORDER_CONSTANT, value=(255, 255, 255))
    h, w = img.shape[:2]

    # 3. Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 4. CLAHE — boost local contrast (fixes underexposed/uneven phone photos)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 5. Unsharp mask sharpening — recovers soft text from phone camera compression
    blurred = cv2.GaussianBlur(gray, (0, 0), 2)
    gray = cv2.addWeighted(gray, 1.8, blurred, -0.8, 0)

    # 6. Adaptive threshold with smaller block for small text
    processed = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15,
        C=8,
    )

    return processed, w, h


def _color_preprocess(image_path: str) -> np.ndarray:
    """
    Return a color-channel-aware version of the preprocessed image.
    Extracts the red channel (makes blue text appear dark, useful for
    standard US nutrition fact labels with black/dark text on white).
    """
    img = cv2.imread(image_path)
    if img is None:
        return None

    h, w = img.shape[:2]
    scale = 1800 / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    elif scale > 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    BORDER = 30
    img = cv2.copyMakeBorder(img, BORDER, BORDER, BORDER, BORDER,
                              cv2.BORDER_CONSTANT, value=(255, 255, 255))

    # Use the minimum of R and G channels to capture dark text in either
    r = img[:, :, 2]
    g = img[:, :, 1]
    combined = np.minimum(r, g)

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(combined)
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


# ─────────────────────────────────────────────────────────
# OCR Pass Helpers
# ─────────────────────────────────────────────────────────

def _bbox_to_item(bbox, text: str, conf: float) -> dict:
    """Convert raw EasyOCR (bbox, text, conf) into our item dict."""
    text = text.strip()
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return {
        'text': text,
        'conf': float(conf),
        'cx': sum(xs) / 4,
        'cy': sum(ys) / 4,
        'x_min': min(xs),
        'x_max': max(xs),
        'y_min': min(ys),
        'y_max': max(ys),
    }


def _is_garbage(text: str) -> bool:
    """
    Filter out junk OCR detections that would pollute the parser.

    Removes:
      - Single characters (true noise)
      - Pure punctuation / symbol blobs
      - Strings of only spaces / empty

    Does NOT remove:
      - 2–3 char nutrient abbreviations like "Na", "Fat", "Ca", "kJ"
      - Short numbers like "0", "1g"
    """
    t = text.strip()
    if len(t) < 2:
        return True
    if all(not c.isalnum() for c in t):
        return True
    return False


def _is_percent_only(text: str) -> bool:
    """
    Returns True if the token is ONLY a percentage value (e.g. "12%", "37%").
    These are %Daily Value column readings that must NOT be parsed as nutrient grams.
    """
    import re
    t = text.strip()
    # Match "12%", "12 %", "0%", "100%" — pure percentage with no other content
    return bool(re.fullmatch(r'\d+\s*%', t))


def _boxes_overlap(a: dict, b: dict, iou_thresh: float = 0.35) -> bool:
    """IoU-based bounding box overlap check."""
    ix1 = max(a['x_min'], b['x_min'])
    iy1 = max(a['y_min'], b['y_min'])
    ix2 = min(a['x_max'], b['x_max'])
    iy2 = min(a['y_max'], b['y_max'])
    if ix2 <= ix1 or iy2 <= iy1:
        return False
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1, (a['x_max'] - a['x_min']) * (a['y_max'] - a['y_min']))
    area_b = max(1, (b['x_max'] - b['x_min']) * (b['y_max'] - b['y_min']))
    iou = inter / (area_a + area_b - inter)
    return iou >= iou_thresh


def _merge_into(base: list, new_items: list) -> list:
    """
    Merge new_items into base list.
    - Overlapping region → keep higher-confidence detection.
    - Non-overlapping → append as new detection.
    """
    result = list(base)
    for item in new_items:
        matched = False
        for i, existing in enumerate(result):
            if _boxes_overlap(existing, item):
                if item['conf'] > existing['conf']:
                    result[i] = item
                matched = True
                break
        if not matched:
            result.append(item)
    return result


def _raw_to_items(raw_results: list, min_conf: float = 0.15) -> list:
    """
    Convert EasyOCR raw output → filtered item list.
    Applies garbage filter and minimum confidence threshold.

    min_conf=0.15 to maximise recall; garbage filter handles noise.
    Percent-only tokens are kept in list but tagged so parser can skip them.
    """
    items = []
    for entry in raw_results:
        if len(entry) == 3:
            bbox, text, conf = entry
        else:
            continue
        text = text.strip()
        if not text or conf < min_conf:
            continue
        if _is_garbage(text):
            continue
        item = _bbox_to_item(bbox, text, conf)
        # Tag percent-only tokens so the parser can filter them
        item['is_percent_dv'] = _is_percent_only(text)
        items.append(item)
    return items


def _detect_pct_dv_column(items: list, image_width: int) -> float | None:
    """
    Detect the x-position of the % Daily Value column.
    This is the RIGHTMOST cluster of items that are all percent values.
    Returns the leftmost x boundary of that column, or None.
    """
    import re
    pct_xs = []
    for item in items:
        if item.get('is_percent_dv') or re.fullmatch(r'\d+\s*%', item['text'].strip()):
            pct_xs.append(item['x_min'])

    if len(pct_xs) < 2:
        return None

    # The %DV column starts around the mean x_min of percent tokens
    return float(np.percentile(pct_xs, 25))  # conservative: left quartile


# ─────────────────────────────────────────────────────────
# Spatial OCR (Primary — 3-pass with confidence voting)
# ─────────────────────────────────────────────────────────

def extract_with_bboxes(image_path: str) -> tuple[list[dict], int, int]:
    """
    Run 3-pass EasyOCR with confidence voting and return all detected
    text blocks with spatial metadata.

    Pass 1: detail=1, paragraph=False, sensitive thresholds
            → Detects individual text elements (labels + numbers)
    Pass 2: detail=1, paragraph=True
            → Catches faint/closely-spaced text that detail mode misses
    Pass 3: Very low contrast_ths + high sensitivity
            → Catches low-contrast numbers on coloured label backgrounds
    Pass 4: Color-channel variant image
            → Catches text that binarization destroys (colored text)

    All passes merged by bounding-box IoU; highest-confidence wins.
    % Daily Value column is detected and items from it are tagged.

    Returns: (items_list, image_width, image_height)
    """
    reader = get_reader()
    processed, width, height = _strong_preprocess(image_path)

    # ── Pass 1: Sensitive detail mode ─────────────────────────────────
    raw1 = reader.readtext(
        processed,
        detail=1,
        paragraph=False,
        text_threshold=0.3,    # Lower = more recall
        low_text=0.2,          # Lower = catches faint characters
        link_threshold=0.4,    # Higher = less horizontal merging (preserves columns)
        width_ths=0.6,
        contrast_ths=0.1,
    )
    items = _raw_to_items(raw1)

    # ── Pass 2: Paragraph mode (catches faint / closely spaced rows) ───
    raw2 = reader.readtext(
        processed,
        detail=1,
        paragraph=True,
        text_threshold=0.3,
        low_text=0.2,
        link_threshold=0.4,
        contrast_ths=0.1,
    )
    items2 = _raw_to_items(raw2)
    items = _merge_into(items, items2)

    # ── Pass 3: Ultra-sensitive pass for low-contrast numbers ──────────
    raw3 = reader.readtext(
        processed,
        detail=1,
        paragraph=False,
        text_threshold=0.2,
        low_text=0.15,
        link_threshold=0.5,
        contrast_ths=0.05,     # Very low — catches low-contrast digits
    )
    items3 = _raw_to_items(raw3)
    items = _merge_into(items, items3)

    # ── Pass 4: Color-channel variant ─────────────────────────────────
    try:
        color_proc = _color_preprocess(image_path)
        if color_proc is not None:
            raw4 = reader.readtext(
                color_proc,
                detail=1,
                paragraph=False,
                text_threshold=0.3,
                low_text=0.2,
                link_threshold=0.4,
                contrast_ths=0.1,
            )
            items4 = _raw_to_items(raw4)
            items = _merge_into(items, items4)
    except Exception:
        pass  # color pass is best-effort

    # ── Tag % DV column items ──────────────────────────────────────────
    pct_col_x = _detect_pct_dv_column(items, width)
    if pct_col_x is not None:
        for item in items:
            if item['x_min'] >= pct_col_x - 20 and _looks_like_pct_dv(item['text']):
                item['is_percent_dv'] = True

    # Sort top → bottom, left → right (bucket rows into 20px bands for accuracy)
    items.sort(key=lambda x: (round(x['cy'] / 20) * 20, x['cx']))

    n1 = len(_raw_to_items(raw1))
    n2 = len(items2)
    n3 = len(items3)
    print(f"[NutriCheck OCR] Detected {len(items)} items "
          f"(p1={n1}, p2={n2}, p3={n3}, pct_col_x={pct_col_x})")

    return items, width, height


def _looks_like_pct_dv(text: str) -> bool:
    """Returns True if the token looks like a %DV value (e.g. '12%', '37%', '0%')."""
    import re
    t = text.strip()
    return bool(re.fullmatch(r'\d{1,3}\s*%', t))


# ─────────────────────────────────────────────────────────
# Simple Text OCR (Fallback)
# ─────────────────────────────────────────────────────────

def extract_text(image_input) -> dict:
    """
    Basic OCR: returns flat text. Used as last-resort fallback.
    Runs the same strong preprocessing then a single sensitive pass.
    """
    reader = get_reader()

    if isinstance(image_input, str):
        processed, _, _ = _strong_preprocess(image_input)
        image_input = processed

    raw = reader.readtext(
        image_input,
        detail=1,
        paragraph=False,
        text_threshold=0.3,
        low_text=0.2,
        link_threshold=0.4,
        contrast_ths=0.1,
    )
    texts = [e[1] for e in raw if len(e) == 3 and not _is_garbage(e[1])]
    return {
        'texts': texts,
        'full_text': '\n'.join(texts),
        'raw_results': raw,
    }


def extract_text_multipass(image_path: str) -> dict:
    """Multipass OCR returning a flat text dict (used as parser fallback)."""
    items, _, _ = extract_with_bboxes(image_path)
    texts = [i['text'] for i in items]
    return {
        'texts': texts,
        'full_text': '\n'.join(texts),
        'raw_results': [],
    }


def extract_text_from_path(image_path: str) -> dict:
    """Convenience wrapper."""
    return extract_text_multipass(image_path)
