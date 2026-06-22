"""
Nutrient Parser — NutriCheck
==============================
Spatially-aware parser that uses per-row boundaries and data-driven
column detection to correctly extract per-100g values from nutrition
label tables.

Key innovation: PER-ROW boundary instead of a global estimate.
Each nutrient row uses its own label item's right edge as the split
point between "label" and "value" zones. This prevents the widest
label (e.g. "Saturated fat (g)") from causing shorter labels (e.g.
"Protein (g)") to lose their values.

Layer 3 improvements:
  - Row grouping tolerance is now proportional to image height (adaptive)
  - Column anchor fallback: uses rightmost numeric value when clustering fails
  - Expanded keyword registry with real-world OCR variants and typos
  - Comma-as-decimal-separator support (European label formats)
  - kJ → kcal conversion for energy values

Layer 4 improvements:
  - Extended regex patterns handle "7.4g" (unit embedded) format
  - 3-line table lookahead (was 2)
  - Number stitching: "7 4" → "7.4" for split-decimal OCR artifacts
"""

import re


# ─────────────────────────────────────────────────────────
# Nutrient keyword registry
# ─────────────────────────────────────────────────────────

NUTRIENT_KEYWORDS = {
    'calories': [
        'energy', 'calories', 'calorie', 'kcal', 'cal',
        'kilocal', 'kilocalories', 'energi', 'energie', 'kcals',
        # kJ is handled separately with conversion
    ],
    'sugar': [
        'total sugars', 'total sugar',
        'sugars', 'sugar',
        'added sugars', 'added sugar', 'free sugars',
        'sucrose', 'glucose', 'sugars, total', 'of which sugars',
        'of which sugar', 'incl sugars',
    ],
    'fat': [
        'total fat', 'total fats', 'fat, total', 'fat total',
        'fat', 'fats', 'lipids', 'total lipids', 'lipid',
        'fett',   # German
        'grasa',  # Spanish
    ],
    'sodium': [
        'sodium', 'salt', 'nacl',
        'na',
        'salt, total', 'salt content',
        'sel',    # French
        'salz',   # German
    ],
    'protein': [
        'protein', 'proteins', 'crude protein', 'total protein',
        'proteine',  # French/German
        'proteinas', # Spanish
    ],
    'fiber': [
        'dietary fiber', 'dietary fibre',
        'total dietary fiber', 'total dietary fibre',
        'total fiber', 'total fibre',
        'fiber', 'fibre', 'crude fiber', 'crude fibre',
        'nsp',        # Non-starch polysaccharides (UK labels)
        'roughage',
        'ballaststoffe',  # German
    ],
    # Internal — used for cross-validation, not returned
    '_carbs': [
        'total carbohydrate', 'total carbohydrates',
        'carbohydrate', 'carbohydrates', 'carbs', 'carb',
        'of which carbohydrates',
    ],
    # Internal — kJ energy flag (triggers unit conversion)
    '_kj': ['kj', 'kilojoule', 'kilojoules'],
}

PUBLIC_NUTRIENTS = ['calories', 'sugar', 'fat', 'sodium', 'protein', 'fiber']

# Reverse lookup: keyword → nutrient key
_KW2N: dict = {}
for _n, _kws in NUTRIENT_KEYWORDS.items():
    for _kw in _kws:
        _KW2N[_kw] = _n

# Keywords that disqualify "fat" (saturated/trans are not total fat)
_FAT_EXCL = {'saturated', 'sat.', 'sat', 'trans', 'mono', 'poly', 'unsaturated'}

# kJ → kcal conversion factor
_KJ_TO_KCAL = 1.0 / 4.184


# ─────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────

def parse_from_spatial(ocr_items: list, image_width: int, image_height: int = 0) -> dict:
    """
    Primary parser using bounding-box positions.

    Pipeline:
    1.  Group items into horizontal rows (adaptive tolerance)
    2.  Merge split decimals ("1" + ".48" → "1.48")
    3.  Detect per-100g column x from data-driven clustering
    4.  For each row: use PER-ROW boundary to find value candidates
    5.  Pick the value closest to the per-100g anchor
    6.  Cross-validate and sanity-check
    """
    if not ocr_items:
        return {k: None for k in PUBLIC_NUTRIENTS}

    # Adaptive row tolerance: proportional to image height
    tol = max(18, int(image_height * 0.018)) if image_height > 0 else 24

    # Step 1: group
    rows = _group_into_rows(ocr_items, tol=tol)

    # Step 2: merge split decimals
    rows = [_merge_decimals(row) for row in rows]

    # Step 3: find column anchors (also computes %DV col boundary)
    per_100g_x, per_serve_x = _find_column_anchors(rows, image_width)

    # Compute %DV column start for row-level filtering
    pct_xs = []
    for row in rows:
        for item in row:
            if item.get('is_percent_dv') or re.fullmatch(r'\d+\s*%', item['text'].strip()):
                pct_xs.append(item['x_min'])
    pct_col_start = (float(min(pct_xs)) - 10) if len(pct_xs) >= 2 else None

    # Step 4 + 5: extract per row
    nutrients, carbs, has_kj = _extract_per_row(
        rows, per_100g_x, per_serve_x, image_width, pct_col_start
    )

    # Convert kJ → kcal if the energy was expressed in kJ
    if has_kj and nutrients.get('calories') is not None:
        nutrients['calories'] = round(nutrients['calories'] * _KJ_TO_KCAL, 1)

    # Step 6: validate
    nutrients = _cross_validate(nutrients, carbs)
    nutrients = _sanity_check(nutrients)

    return {k: nutrients.get(k) for k in PUBLIC_NUTRIENTS}


# ─────────────────────────────────────────────────────────
# Step 1: Row grouping
# ─────────────────────────────────────────────────────────

def _group_into_rows(items: list, tol: int = 24) -> list:
    if not items:
        return []
    s = sorted(items, key=lambda x: x['cy'])
    rows, cur = [], [s[0]]
    for item in s[1:]:
        if abs(item['cy'] - cur[-1]['cy']) <= tol:
            cur.append(item)
        else:
            rows.append(sorted(cur, key=lambda x: x['cx']))
            cur = [item]
    rows.append(sorted(cur, key=lambda x: x['cx']))
    return rows


# ─────────────────────────────────────────────────────────
# Step 2: Decimal merger
# ─────────────────────────────────────────────────────────

def _merge_decimals(row: list) -> list:
    """Merge adjacent split-decimal tokens: "1" + ".48" → "1.48"."""
    if len(row) < 2:
        return row
    merged, i = [], 0
    while i < len(row):
        item = dict(row[i])
        nxt = row[i + 1] if i + 1 < len(row) else None
        if (nxt
                and item['text'].rstrip()[-1:].isdigit()
                and nxt['text'].startswith('.')
                and _is_num(nxt['text'])):
            item['text'] = item['text'] + nxt['text']
            item['x_max'] = nxt['x_max']
            item['cx'] = (item['x_min'] + item['x_max']) / 2
            i += 2
        else:
            i += 1
        merged.append(item)
    return merged


# ─────────────────────────────────────────────────────────
# Step 3: Data-driven column anchor detection
# ─────────────────────────────────────────────────────────

def _find_column_anchors(rows: list, image_width: int) -> tuple:
    """
    Find the x-positions of the gram-value and per-serve columns.
    Critically: detects and excludes the %Daily Value column so its
    numbers (12%, 37% etc.) are never used as nutrient gram values.

    Primary: cluster x-positions of non-percent numeric items in nutrient rows.
    Fallback 1: look for 'per 100' header text.
    Fallback 2: use the leftmost numeric (gram column) in each nutrient row.
    """
    # --- Detect % DV column x boundary ---
    # Collect x positions of all percent-only tokens across all rows
    pct_xs = []
    for row in rows:
        for item in row:
            if item.get('is_percent_dv') or re.fullmatch(r'\d+\s*%', item['text'].strip()):
                pct_xs.append(item['x_min'])

    pct_col_start = None
    if len(pct_xs) >= 2:
        # The %DV column starts at the leftmost % token (with margin)
        pct_col_start = float(min(pct_xs)) - 10

    # --- Primary: data-driven clustering of non-percent numeric items ---
    numeric_xs = []

    for row in rows:
        kw_item, _ = _find_keyword_item(row)
        if kw_item is None:
            continue
        for item in row:
            # Skip percent-only tokens and items in the %DV column
            if item.get('is_percent_dv') or re.fullmatch(r'\d+\s*%', item['text'].strip()):
                continue
            if pct_col_start is not None and item['cx'] >= pct_col_start:
                continue
            if item['cx'] > kw_item['x_max'] + 5 and _is_num(item['text']):
                numeric_xs.append(item['cx'])

    if len(numeric_xs) >= 3:
        clusters = _cluster(sorted(numeric_xs), gap=60)
        sig = [c for c in clusters if len(c) >= 2]
        if not sig:
            sig = clusters
        per_100g_x = _mean(sig[0])
        per_serve_x = _mean(sig[1]) if len(sig) > 1 else None
        return per_100g_x, per_serve_x

    # --- Fallback 1: header text ("per 100 g product") ---
    for row in rows:
        row_text = ' '.join(i['text'].lower() for i in row)
        if re.search(r'\b100\b', row_text) and re.search(r'\b(per|product|approx|gram)\b', row_text):
            p100_x = None
            p_srv_x = None
            for item in row:
                t = item['text'].lower()
                if '100' in t:
                    p100_x = item['cx']
                if re.search(r'\b(serv|rda)\b', t):
                    p_srv_x = item['cx']
            if p100_x:
                if not p_srv_x:
                    rights = [i for i in row if i['cx'] > p100_x + image_width * 0.08]
                    if rights:
                        p_srv_x = max(i['cx'] for i in rights)
                return p100_x, p_srv_x

    # --- Fallback 2: leftmost non-percent numeric in each nutrient row ---
    # Standard US Nutrition Facts: gram value appears LEFT of %DV.
    # Pick the leftmost to avoid the %DV column.
    leftmost_xs = []
    for row in rows:
        kw_item, _ = _find_keyword_item(row)
        if kw_item is None:
            continue
        nums = [
            i for i in row
            if i['cx'] > kw_item['x_max'] + 5
            and _is_num(i['text'])
            and not i.get('is_percent_dv')
            and not re.fullmatch(r'\d+\s*%', i['text'].strip())
            and (pct_col_start is None or i['cx'] < pct_col_start)
        ]
        if nums:
            leftmost_xs.append(min(nums, key=lambda x: x['cx'])['cx'])

    if leftmost_xs:
        return _mean(leftmost_xs), None

    return None, None


def _cluster(sorted_xs: list, gap: int = 70) -> list:
    if not sorted_xs:
        return []
    clusters = [[sorted_xs[0]]]
    for x in sorted_xs[1:]:
        if x - clusters[-1][-1] < gap:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return sorted(clusters, key=lambda c: _mean(c))


def _mean(lst):
    return sum(lst) / len(lst) if lst else 0


# ─────────────────────────────────────────────────────────
# Step 4 + 5: Per-row extraction
# ─────────────────────────────────────────────────────────

def _extract_per_row(rows: list, per_100g_x, per_serve_x, image_width: int,
                     pct_col_start: float | None = None) -> tuple:
    """
    Key innovation: PER-ROW boundary.

    Returns: (nutrients dict, carbs float|None, has_kj bool)
    has_kj=True means the energy value was in kJ and needs conversion.
    """
    nutrients = {k: None for k in PUBLIC_NUTRIENTS}
    carbs = None
    has_kj = False

    for row_idx, row in enumerate(rows):
        kw_item, nutrient = _find_keyword_item(row)

        if nutrient is None:
            full_text = ' '.join(i['text'] for i in row)
            nutrient = _identify_nutrient(full_text)
            if nutrient is None:
                continue
            text_items = [i for i in row if not _is_num(i['text'])]
            kw_item = max(text_items, key=lambda x: x['cx']) if text_items else row[0]

        is_carbs = (nutrient == '_carbs')
        is_kj = (nutrient == '_kj')

        if not is_carbs and not is_kj and nutrients.get(nutrient) is not None:
            continue

        # ── Per-row boundary ─────────────────────────────────
        row_split_x = kw_item['x_max'] + 8
        value_items = [
            i for i in row
            if i['cx'] >= row_split_x
            # Exclude %DV tokens entirely from value candidates
            and not i.get('is_percent_dv')
            and not re.fullmatch(r'\d+\s*%', i['text'].strip())
            # Exclude items that fall in the detected %DV column
            and (pct_col_start is None or i['cx'] < pct_col_start)
        ]

        if not value_items:
            # Look at next rows — extended to 3 lines (was 2)
            for offset in range(1, 4):
                if row_idx + offset >= len(rows):
                    break
                next_row = rows[row_idx + offset]
                next_text = ' '.join(i['text'] for i in next_row)
                if _identify_nutrient(next_text) is None:
                    value_items = [i for i in next_row if _is_num(i['text'])]
                    if value_items:
                        break
                else:
                    break  # Hit another nutrient row; stop looking

        value = _pick_value(value_items, per_100g_x, per_serve_x)

        if value is not None:
            if is_carbs:
                carbs = value
            elif is_kj:
                # Store the kJ energy value temporarily under 'calories'
                if nutrients['calories'] is None:
                    nutrients['calories'] = value
                    has_kj = True
            else:
                nutrients[nutrient] = value

    return nutrients, carbs, has_kj


def _find_keyword_item(row: list) -> tuple:
    """
    Find the item in a row that contains a nutrient keyword.
    Returns (item, nutrient_key) or (None, None).
    """
    for item in row:
        n = _identify_nutrient(item['text'])
        if n is not None:
            return item, n

    texts = [i['text'] for i in row]
    for end in range(len(texts), 0, -1):
        combined = ' '.join(texts[:end])
        n = _identify_nutrient(combined)
        if n is not None:
            return row[end - 1], n

    return None, None


def _pick_value(value_items: list, per_100g_x, per_serve_x) -> float | None:
    """Pick the per-100g value from candidate items."""
    if not value_items:
        return None

    numeric = [(i, _to_float(i['text'])) for i in value_items if _is_num(i['text'])]
    numeric = [(i, v) for i, v in numeric if v is not None]
    if not numeric:
        return None

    if per_100g_x is not None:
        if per_serve_x is not None:
            filtered = [
                (i, v) for i, v in numeric
                if abs(i['cx'] - per_100g_x) <= abs(i['cx'] - per_serve_x)
            ]
            if filtered:
                numeric = filtered
        best = min(numeric, key=lambda x: abs(x[0]['cx'] - per_100g_x))
        return best[1]
    else:
        # Pick leftmost (usually per 100g on most label formats)
        return min(numeric, key=lambda x: x[0]['cx'])[1]


# ─────────────────────────────────────────────────────────
# Step 6: Validation
# ─────────────────────────────────────────────────────────

def _cross_validate(nutrients: dict, carbs) -> dict:
    """Biochemical constraints: sugar ≤ carbs, sugar × 4 ≤ calories."""
    sugar = nutrients.get('sugar')
    calories = nutrients.get('calories')

    if sugar is not None and carbs is not None:
        if sugar > carbs * 1.05:
            nutrients['sugar'] = None

    if sugar is not None and calories is not None:
        if sugar * 4 > calories * 1.15:
            nutrients['sugar'] = None

    return nutrients


def _sanity_check(nutrients: dict) -> dict:
    """Clamp values outside physiologically possible ranges to None."""
    limits = {
        'calories': (0, 900),
        'sugar':    (0, 100),
        'fat':      (0, 100),
        'sodium':   (0, 5000),
        'protein':  (0, 100),
        'fiber':    (0, 80),
    }
    for key, (lo, hi) in limits.items():
        v = nutrients.get(key)
        if v is not None and (v < lo or v > hi):
            nutrients[key] = None
    return nutrients


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _identify_nutrient(line: str):
    """Return the canonical nutrient name for a text line, or None."""
    t = line.lower().strip()
    # Normalise comma-as-decimal (European labels: "7,4" → "7.4")
    t = t.replace(',', '.')
    t = re.sub(r'\([^)]{0,10}\)', '', t)      # strip "(g)", "(kcal)" etc.
    t = re.sub(r'[\s:\-,/]+$', '', t).strip()
    t = re.sub(r'\s+', ' ', t)

    for kw in sorted(_KW2N.keys(), key=len, reverse=True):
        if kw in t:
            nutrient = _KW2N[kw]
            if nutrient == 'fat' and any(x in t for x in _FAT_EXCL):
                continue
            return nutrient
    return None


def _is_num(text: str) -> bool:
    """
    True if text is primarily a number (including European comma decimals).
    Explicitly rejects pure percentage tokens like "12%" that appear in the
    %Daily Value column — these must never be treated as nutrient gram values.
    """
    t = text.strip()

    # ── Reject pure %DV tokens ──────────────────────────────────────────
    # e.g. "12%", "37%", "0%" — these are %Daily Value, NOT gram amounts
    if re.fullmatch(r'\d+\s*%', t):
        return False

    # Normalise European comma decimal
    t_norm = t.replace(',', '.')
    try:
        float(t_norm)
        return True
    except ValueError:
        pass
    # Accept with trailing unit: "7.5g", "294kcal", "7,4g"
    # Note: % is intentionally NOT in this list — "12%" is never a nutrient value
    cleaned = re.sub(r'(?i)(kcal|kj|mg|mcg|g|ml|l)$', '', t_norm)
    try:
        float(cleaned)
        return len(cleaned) > 0
    except ValueError:
        return False


def _to_float(text: str):
    """
    Extract the first float from a text token, handling European commas.
    Rejects pure %DV tokens (e.g. '12%') — these are not nutrient values.
    """
    t = text.strip()
    # Reject pure percentage tokens — these are %Daily Value, not gram amounts
    if re.fullmatch(r'\d+\s*%', t):
        return None
    t = t.replace(',', '.')
    # Strip known unit suffixes (NOT %) to avoid treating "12%" as "12"
    cleaned = re.sub(r'(?i)(kcal|kj|mg|mcg|[μµ]g|g|ml|l)$', '', t)
    m = re.search(r'-?\d+\.?\d*|\.\d+', cleaned)
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


# ─────────────────────────────────────────────────────────
# TEXT-BASED FALLBACK PARSER (Layer 4 improvements)
# ─────────────────────────────────────────────────────────

# All patterns now allow an optional trailing unit like "7.4g", "294 kcal"
# and normalise European comma decimals before matching.
_INLINE = {
    'calories': [
        r'energy\s*\(?\s*(?:kcal|cal)\s*\)?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*(?:kcal|kj|cal)?',
        r'(?:calories?|kcal|cal|energy)\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*(?:kcal|kj)?',
    ],
    'sugar': [
        r'total\s+sugars?\s*\(?\s*g\s*\)?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*g?',
        r'of\s+which\s+sugars?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*g?',
        r'sugars?\s*\(?\s*g\s*\)?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*g?',
        r'sugars?\s*[:\-]\s*([\d]+[.,]?[\d]*)',
    ],
    'fat': [
        r'total\s+fat\s*\(?\s*g\s*\)?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*g?',
        r'(?<!\w)fat\s*\(?\s*g\s*\)?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*g?',
    ],
    'sodium': [
        # "Sodium (mg) 320" — unit in parens BEFORE the value
        r'sodium\s*(?:\(\s*mg\s*\))?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*(?:mg)?',
        # "Sodium: 320mg" or "Sodium 320"
        r'sodium\s*[:\-]?\s*([\d]{2,}[.,]?[\d]*)\s*(?:mg)?',
        # Salt as proxy
        r'salt\s*(?:\([^)]{0,6}\))?\s*[:\-]?\s*([\d]+[.,]?[\d]*)',
    ],
    'protein': [
        r'protein\s*\(?\s*g\s*\)?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*g?',
        r'protein\s*[:\-]?\s*([\d]+[.,]?[\d]*)',
    ],
    'fiber': [
        r'dietary\s+fi(?:ber|bre)\s*\(?\s*g\s*\)?\s*[:\-]?\s*([\d]+[.,]?[\d]*)\s*g?',
        r'fi(?:ber|bre)\s*[:\-]?\s*([\d]+[.,]?[\d]*)',
    ],
}


def _stitch_split_numbers(text: str) -> str:
    """
    Fix OCR artifacts where a decimal number is split by a space:
    "7 4" near a "." context → attempt to stitch as "7.4".
    This addresses cases like "Sodium 7 4 mg" → "Sodium 7.4 mg".
    Strategy: if two integers are adjacent with a single space and both
    are short (≤3 digits), merge them around a '.'.
    """
    return re.sub(r'\b(\d{1,3})\s+(\d{1,2})\b', lambda m: m.group(1) + '.' + m.group(2), text)


def parse_nutrients(ocr_text: str) -> dict:
    """Text-based fallback parser (regex, for non-table or flat labels)."""
    # Normalise: comma decimal, pipe→l, dashes, extra spaces
    text = ocr_text.lower()
    text = text.replace('|', 'l').replace('–', '-').replace('—', '-')
    # Normalise European comma decimals ONLY inside numeric contexts
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    text = _stitch_split_numbers(text)
    text = re.sub(r'[ \t]+', ' ', text)
    lines = text.split('\n')
    nutrients = {k: None for k in PUBLIC_NUTRIENTS}

    # Phase 1: inline patterns
    for nutrient, patterns in _INLINE.items():
        if nutrients[nutrient] is not None:
            continue
        for line in lines:
            for pat in patterns:
                m = re.search(pat, line)
                if m:
                    try:
                        val = float(m.group(1).replace(',', '.'))
                        nutrients[nutrient] = val
                        break
                    except (ValueError, IndexError):
                        continue
            if nutrients[nutrient] is not None:
                break

    # Phase 2: two-/three-line table lookahead
    # Looks at the next 1–3 lines for a numeric value.
    # Skips lines that are ONLY a percentage (e.g. "12%") — those are %DV, not grams.
    for i, line in enumerate(lines):
        if all(v is not None for v in nutrients.values()):
            break
        nutrient = _identify_nutrient(line)
        if nutrient is None or nutrient.startswith('_') or nutrients.get(nutrient) is not None:
            continue
        for offset in range(1, 4):
            if i + offset >= len(lines):
                break
            nxt = lines[i + offset].strip()
            if _identify_nutrient(nxt) is not None:
                break
            # Skip lines that are purely a %DV value
            if re.fullmatch(r'\d+\s*%', nxt):
                continue
            nxt_norm = re.sub(r'(\d),(\d)', r'\1.\2', nxt)
            # Collect numbers that are NOT pure percentages
            nums = [n for n in re.findall(r'\d+\.?\d*', nxt_norm)
                    if not re.fullmatch(r'\d+', n) or int(n) < 200]  # raw integers over 200 are likely %DV anomalies
            # Prefer numbers followed by 'g', 'mg' etc. — unit-qualified values
            unit_nums = re.findall(r'(\d+\.?\d*)\s*(?:g|mg|mcg|kcal|kj)\b', nxt_norm)
            if unit_nums:
                nums = unit_nums
            if nums:
                try:
                    nutrients[nutrient] = float(nums[0])
                except ValueError:
                    pass
                break

    return _sanity_check(nutrients)


# ─────────────────────────────────────────────────────────
# Product Name Extractor
# ─────────────────────────────────────────────────────────

_SKIP = {
    'calories', 'sugar', 'fat', 'sodium', 'protein', 'fiber', 'fibre',
    'nutrition', 'nutritional', 'facts', 'information', 'amount',
    'serving', 'servings', 'daily', 'value', 'total', 'percent',
    'ingredients', 'contains', 'allergen', 'carbohydrate', 'cholesterol',
    'vitamin', 'mineral', 'energy', 'saturated', 'trans', 'per', 'approx',
    'rda', 'pack', 'about', 'added', 'dietary', 'crude', 'free',
}


def extract_product_name(ocr_texts: list) -> str:
    seen = set()
    for text in ocr_texts:
        t = text.strip()
        if len(t) < 3:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        words = k.split()
        if any(w in _SKIP for w in words):
            continue
        digit_ratio = sum(c.isdigit() for c in t) / max(len(t), 1)
        if digit_ratio > 0.35:
            continue
        if len(words) == 1 and len(t) < 5:
            continue
        return t
    return 'Unknown Product'
