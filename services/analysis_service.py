import os
from services.ocr_service import extract_with_bboxes, extract_text
from models.nutrient_parser import parse_from_spatial, parse_nutrients, extract_product_name, PUBLIC_NUTRIENTS
from models.health_scorer import calculate_health_score
from database import save_analysis

# Minimum number of nutrients that must be detected before we trust the result.
# If fewer are found, we return a "low-confidence" fallback instead of a bad score.
_MIN_NUTRIENTS_REQUIRED = 3


def analyze_image(image_path, user_id=None):
    """
    Full analysis pipeline: preprocess → 3-pass OCR → spatial parse → score → save.

    Uses bounding-box aware OCR to correctly identify which column of a
    two-column nutrition table (per 100g vs per serve) each value belongs to.
    Falls back to text-regex parsing if spatial parsing fails.
    Returns a low-confidence notice if fewer than 3 nutrients are detected.
    """

    # ── Step 1: 3-pass Spatial OCR ────────────────────────────────────
    ocr_items, image_width, image_height = extract_with_bboxes(image_path)

    # ── Step 2: Spatial nutrient parsing (per-100g column only) ───────
    nutrients = parse_from_spatial(ocr_items, image_width, image_height)

    # ── Step 3: Text fallback for any still-missing nutrients ──────────
    missing = [k for k, v in nutrients.items() if v is None]
    flat_text = '\n'.join(i['text'] for i in ocr_items)

    if missing:
        text_nutrients = parse_nutrients(flat_text)
        for key in missing:
            if text_nutrients.get(key) is not None:
                nutrients[key] = text_nutrients[key]

    # ── Step 4: Last resort — full-image OCR if nothing was found ──────
    missing = [k for k, v in nutrients.items() if v is None]
    if len(missing) == len(PUBLIC_NUTRIENTS):
        try:
            fallback_ocr = extract_text(image_path)
            orig_nutrients = parse_nutrients(fallback_ocr['full_text'])
            for key in missing:
                if orig_nutrients.get(key) is not None:
                    nutrients[key] = orig_nutrients[key]
            if fallback_ocr.get('full_text'):
                flat_text = fallback_ocr['full_text']
        except Exception:
            pass

    # ── Step 5: Low-confidence fallback ──────────────────────────────
    # If fewer than _MIN_NUTRIENTS_REQUIRED nutrients were detected,
    # the OCR output is unreliable. Return a safe, honest response so
    # the app doesn't show nonsensical scores.
    detected_count = sum(1 for v in nutrients.values() if v is not None)
    if detected_count < _MIN_NUTRIENTS_REQUIRED:
        low_conf_result = {
            'product_name': 'Detected Product',
            'image_path': image_path,
            'calories': None,
            'sugar':    None,
            'fat':      None,
            'sodium':   None,
            'protein':  None,
            'fiber':    None,
            'health_score': 50,
            'verdict': 'Low Image Confidence',
            'explanation': (
                f'Only {detected_count} of 6 nutrients could be read from the label. '
                'The image may be blurry, too dark, or at an angle.'
            ),
            'recommendation': (
                'For best results: lay the product flat, use good lighting, '
                'and photograph the nutrition panel straight-on from ~30cm away.'
            ),
            'raw_ocr_text': flat_text,
            'breakdown': {},
            'low_confidence': True,
        }
        row_id = save_analysis(low_conf_result, user_id=user_id)
        low_conf_result['id'] = row_id
        return low_conf_result

    # ── Step 6: Extract product name ───────────────────────────────────
    texts = [i['text'] for i in ocr_items]
    product_name = extract_product_name(texts)

    # ── Step 7: DNN health scoring ─────────────────────────────────────
    health_result = calculate_health_score(nutrients)

    # ── Step 8: Build result dict ──────────────────────────────────────
    result = {
        'product_name': product_name,
        'image_path': image_path,
        'calories': nutrients.get('calories'),
        'sugar':    nutrients.get('sugar'),
        'fat':      nutrients.get('fat'),
        'sodium':   nutrients.get('sodium'),
        'protein':  nutrients.get('protein'),
        'fiber':    nutrients.get('fiber'),
        'health_score':    health_result['health_score'],
        'verdict':         health_result['verdict'],
        'explanation':     health_result['explanation'],
        'recommendation':  health_result['recommendation'],
        'raw_ocr_text':    flat_text,
        'breakdown':       health_result['breakdown'],
        'low_confidence':  False,
    }

    # ── Step 9: Save to database ───────────────────────────────────────
    row_id = save_analysis(result, user_id=user_id)
    result['id'] = row_id

    return result
