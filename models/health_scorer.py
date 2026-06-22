"""
Health Scorer — NutriCheck
===========================
Uses a trained DNN (MLPRegressor) model to calculate health scores.
Falls back to the original rule-based approach if the model is unavailable.
"""

from config import DAILY_REFERENCE, SCORE_HEALTHY, SCORE_MODERATE


def calculate_health_score(nutrients: dict) -> dict:
    """
    Calculate a health score for a food product using a DNN model.

    The DNN (Multi-Layer Perceptron, 3 hidden layers 128→64→32) is trained on
    a synthetic dataset derived from WHO/USDA dietary guidelines.
    Falls back to rule-based scoring if the model fails to load.

    Args:
        nutrients: dict with keys calories, sugar, fat, sodium, protein, fiber

    Returns:
        dict with health_score, verdict, explanation, recommendation, breakdown
    """
    # Extract values, default to 0 if missing
    cal     = float(nutrients.get('calories') or 0)
    sugar   = float(nutrients.get('sugar')    or 0)
    fat     = float(nutrients.get('fat')      or 0)
    sodium  = float(nutrients.get('sodium')   or 0)
    protein = float(nutrients.get('protein')  or 0)
    fiber   = float(nutrients.get('fiber')    or 0)

    # Try DNN scoring first -------------------------------------------
    score = None
    try:
        from models.dnn_scorer import predict_health_score
        score = predict_health_score({
            'calories': cal, 'sugar': sugar, 'fat': fat,
            'sodium': sodium, 'protein': protein, 'fiber': fiber,
        })
    except Exception as e:
        print(f"[NutriCheck] DNN scorer unavailable, falling back to rules. Reason: {e}")

    if score is None:
        # Rule-based fallback
        score = _rule_based_score(cal, sugar, fat, sodium, protein, fiber)

    score = round(score)

    # Compute breakdown (for explanation generation) ------------------
    cal_pct    = (cal    / DAILY_REFERENCE['calories']) * 100
    sugar_pct  = (sugar  / DAILY_REFERENCE['sugar'])    * 100
    fat_pct    = (fat    / DAILY_REFERENCE['fat'])       * 100
    sodium_pct = (sodium / DAILY_REFERENCE['sodium'])    * 100
    prot_pct   = (protein / DAILY_REFERENCE['protein'])  * 100
    fiber_pct  = (fiber   / DAILY_REFERENCE['fiber'])    * 100

    neg_cal    = _scale_negative(cal_pct)
    neg_sugar  = _scale_negative(sugar_pct)
    neg_fat    = _scale_negative(fat_pct)
    neg_sodium = _scale_negative(sodium_pct)
    pos_prot   = _scale_positive(prot_pct)
    pos_fiber  = _scale_positive(fiber_pct)

    total_negative = neg_cal + neg_sugar + neg_fat + neg_sodium
    total_positive = pos_prot + pos_fiber

    # Verdict ---------------------------------------------------------
    if score >= SCORE_HEALTHY:
        verdict = 'Healthy Choice'
    elif score >= SCORE_MODERATE:
        verdict = 'Consume in Moderation'
    else:
        verdict = 'Limit Consumption'

    explanation = _generate_explanation(
        nutrients,
        {'calories': neg_cal, 'sugar': neg_sugar, 'fat': neg_fat, 'sodium': neg_sodium},
        {'protein': pos_prot, 'fiber': pos_fiber},
    )
    recommendation = _generate_recommendation(verdict, nutrients)

    return {
        'health_score': score,
        'verdict': verdict,
        'explanation': explanation,
        'recommendation': recommendation,
        'breakdown': {
            'negative': {
                'calories': neg_cal,
                'sugar': neg_sugar,
                'fat': neg_fat,
                'sodium': neg_sodium,
                'total': total_negative,
            },
            'positive': {
                'protein': pos_prot,
                'fiber': pos_fiber,
                'total': total_positive,
            },
        },
    }


# ─────────────────────────────────────────────────────────
# Helper Scales (used for breakdown + fallback)
# ─────────────────────────────────────────────────────────

def _rule_based_score(cal, sugar, fat, sodium, protein, fiber) -> float:
    """Original rule-based fallback scorer."""
    cal_pct    = (cal    / DAILY_REFERENCE['calories']) * 100
    sugar_pct  = (sugar  / DAILY_REFERENCE['sugar'])    * 100
    fat_pct    = (fat    / DAILY_REFERENCE['fat'])       * 100
    sodium_pct = (sodium / DAILY_REFERENCE['sodium'])    * 100
    prot_pct   = (protein / DAILY_REFERENCE['protein'])  * 100
    fiber_pct  = (fiber   / DAILY_REFERENCE['fiber'])    * 100

    neg = (_scale_negative(cal_pct) + _scale_negative(sugar_pct) +
           _scale_negative(fat_pct) + _scale_negative(sodium_pct))
    pos = _scale_positive(prot_pct) + _scale_positive(fiber_pct)
    return max(0.0, min(100.0, 100 - neg + pos))


def _scale_negative(pct: float) -> float:
    if pct <= 5:   return 0
    if pct <= 15:  return 2
    if pct <= 25:  return 4
    if pct <= 40:  return 6
    if pct <= 60:  return 8
    return 10


def _scale_positive(pct: float) -> float:
    if pct >= 30: return 7.5
    if pct >= 20: return 5.0
    if pct >= 10: return 3.0
    if pct >= 5:  return 1.5
    return 0.0


def _generate_explanation(nutrients, neg_scores, pos_scores) -> str:
    parts = []
    for nutrient, score in sorted(neg_scores.items(), key=lambda x: x[1], reverse=True):
        if score >= 6:
            val  = nutrients.get(nutrient, 0) or 0
            unit = 'mg' if nutrient == 'sodium' else ('kcal' if nutrient == 'calories' else 'g')
            pct  = round((val / DAILY_REFERENCE[nutrient]) * 100)
            parts.append(f"High {nutrient} ({val}{unit}, {pct}% of daily value) negatively impacts the health score.")
        elif score >= 4:
            val  = nutrients.get(nutrient, 0) or 0
            unit = 'mg' if nutrient == 'sodium' else ('kcal' if nutrient == 'calories' else 'g')
            parts.append(f"Moderate {nutrient} level ({val}{unit}) contributes to a lower score.")
    for nutrient, score in pos_scores.items():
        if score >= 5:
            val = nutrients.get(nutrient, 0) or 0
            parts.append(f"Good {nutrient} content ({val}g) positively contributes to the score.")
    return ' '.join(parts) or "Nutrient levels are within acceptable ranges."


def _generate_recommendation(verdict, nutrients) -> str:
    recs = []
    if verdict == 'Healthy Choice':
        recs.append("This product has a balanced nutritional profile and can be part of a healthy diet.")
    elif verdict == 'Consume in Moderation':
        recs.append("This product is acceptable in moderate quantities as part of a balanced diet.")
    else:
        recs.append("This product should be consumed sparingly due to its nutritional profile.")

    sugar   = nutrients.get('sugar')   or 0
    sodium  = nutrients.get('sodium')  or 0
    fat     = nutrients.get('fat')     or 0
    protein = nutrients.get('protein') or 0
    fiber   = nutrients.get('fiber')   or 0

    if sugar   > DAILY_REFERENCE['sugar']   * 0.25: recs.append("Consider lower-sugar alternatives to reduce added sugar intake.")
    if sodium  > DAILY_REFERENCE['sodium']  * 0.25: recs.append("High sodium content — watch your total daily sodium intake.")
    if fat     > DAILY_REFERENCE['fat']     * 0.25: recs.append("Significant fat content — balance with lower-fat meals.")
    if protein < DAILY_REFERENCE['protein'] * 0.05: recs.append("Low in protein — pair with protein-rich foods.")
    if fiber   < DAILY_REFERENCE['fiber']   * 0.05: recs.append("Low in fiber — consider adding whole grains, fruits, or vegetables.")
    return ' '.join(recs)

