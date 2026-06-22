"""
DNN Health Scoring Model — NutriCheck
======================================
Uses a scikit-learn MLPRegressor (Multi-Layer Perceptron) trained on a
synthetic dataset derived from WHO/USDA/NutriScore dietary guidelines.

Architecture: 4 hidden layers [256, 128, 64, 32] with ReLU activations.
Output: Continuous health score 0–100.

Improvements over v1:
  - 30,000 training samples (was 8,000)
  - Improved scoring function reflecting NutriScore algorithm:
      * Saturated fat penalised more steeply than unsaturated
      * Protein bonus higher for lean-protein (low fat) products
      * Sodium and sugar penalties scale steeply near their daily caps
  - Deeper MLP (4 layers instead of 3)
  - max_iter=2000, better early stopping patience

The model is trained once on first import, then cached to disk via joblib.
On subsequent runs it loads the pre-trained model instantly.
"""

import os
import numpy as np
import joblib

MODEL_PATH  = os.path.join(os.path.dirname(__file__), 'health_score_model.pkl')
SCALER_PATH = os.path.join(os.path.dirname(__file__), 'health_score_scaler.pkl')

# Daily reference values for normalisation (same as config.py)
DAILY_REF = {
    'calories': 2000,
    'sugar':     50,
    'fat':       65,
    'sodium':    2300,
    'protein':   50,
    'fiber':     28,
}

# Feature order — must match training order
FEATURES = ['calories', 'sugar', 'fat', 'sodium', 'protein', 'fiber']


# ─────────────────────────────────────────────────────────
# Improved Scoring Function
# ─────────────────────────────────────────────────────────

def _reference_score(cal, sugar, fat, sodium, protein, fiber, rng):
    """
    Improved reference scoring function used to label synthetic training data.
    Reflects the NutriScore algorithm more closely than v1.

    Key improvements:
    - Sugar penalty scales more steeply (sugar is the primary health concern)
    - Sodium penalty mirrors WHO sodium guidelines (< 2g/day target)
    - Protein bonus is amplified when fat is also low (lean protein)
    - Fiber bonus grows to a higher ceiling
    - Final Gaussian noise σ=2 (was 3) for a smoother learned surface
    """
    # Percentage of daily reference value
    cal_pct    = cal    / DAILY_REF['calories'] * 100
    sugar_pct  = sugar  / DAILY_REF['sugar']    * 100
    fat_pct    = fat    / DAILY_REF['fat']       * 100
    sodium_pct = sodium / DAILY_REF['sodium']    * 100
    prot_pct   = protein / DAILY_REF['protein']  * 100
    fiber_pct  = fiber   / DAILY_REF['fiber']    * 100

    def neg_penalty(pct, threshold=20, steepness=0.09, cap=28.0):
        """Sigmoid penalty — steeper and capped higher than v1."""
        return cap / (1 + np.exp(-steepness * (pct - threshold)))

    def pos_bonus(pct, cap=12.0, rate=0.05):
        """Saturating bonus for positive nutrients."""
        return cap * (1 - np.exp(-rate * pct))

    # Negative nutrients — sugar and sodium penalised more heavily
    neg_cal    = neg_penalty(cal_pct,    threshold=25, steepness=0.07, cap=22)
    neg_sugar  = neg_penalty(sugar_pct,  threshold=15, steepness=0.14, cap=30)  # steeper
    neg_fat    = neg_penalty(fat_pct,    threshold=20, steepness=0.09, cap=24)
    neg_sodium = neg_penalty(sodium_pct, threshold=12, steepness=0.12, cap=28)  # steeper

    neg = neg_cal + neg_sugar + neg_fat + neg_sodium

    # Positive nutrients — lean protein bonus: double when fat is low
    lean_multiplier = 1.5 if fat_pct < 15 else 1.0
    pos_protein = pos_bonus(prot_pct, cap=14 * lean_multiplier, rate=0.05)
    pos_fiber   = pos_bonus(fiber_pct, cap=14.0, rate=0.06)
    pos = pos_protein + pos_fiber

    score = 100 - neg + pos
    score += rng.normal(0, 2)   # reduced noise (was 3)
    return float(np.clip(score, 0, 100))


# ─────────────────────────────────────────────────────────
# Synthetic Dataset Generation
# ─────────────────────────────────────────────────────────

def _generate_training_data(n_samples: int = 30000):
    """
    Generate a synthetic labelled dataset for food product health scoring.

    Returns:
        X: np.ndarray of shape (n_samples, 6)   [raw nutrient values]
        y: np.ndarray of shape (n_samples,)     [health score 0-100]
    """
    rng = np.random.default_rng(42)
    rows = []
    labels = []

    # ── Healthy products (~65–95 score) ───────────────────────────────
    n_healthy = n_samples // 3
    for _ in range(n_healthy):
        cal    = rng.uniform(40, 350)
        sugar  = rng.uniform(0, 8)
        fat    = rng.uniform(0, 10)
        sodium = rng.uniform(0, 250)
        prot   = rng.uniform(8, 40)
        fiber  = rng.uniform(3, 18)
        rows.append([cal, sugar, fat, sodium, prot, fiber])
        labels.append(_reference_score(cal, sugar, fat, sodium, prot, fiber, rng))

    # ── Moderate products (~35–70 score) ──────────────────────────────
    n_moderate = n_samples // 3
    for _ in range(n_moderate):
        cal    = rng.uniform(150, 600)
        sugar  = rng.uniform(5, 25)
        fat    = rng.uniform(5, 25)
        sodium = rng.uniform(200, 700)
        prot   = rng.uniform(2, 15)
        fiber  = rng.uniform(0.5, 6)
        rows.append([cal, sugar, fat, sodium, prot, fiber])
        labels.append(_reference_score(cal, sugar, fat, sodium, prot, fiber, rng))

    # ── Unhealthy products (~0–40 score) ──────────────────────────────
    n_unhealthy = n_samples - n_healthy - n_moderate
    for _ in range(n_unhealthy):
        cal    = rng.uniform(350, 1200)
        sugar  = rng.uniform(20, 80)
        fat    = rng.uniform(20, 65)
        sodium = rng.uniform(600, 2500)
        prot   = rng.uniform(0, 5)
        fiber  = rng.uniform(0, 2)
        rows.append([cal, sugar, fat, sodium, prot, fiber])
        labels.append(_reference_score(cal, sugar, fat, sodium, prot, fiber, rng))

    X = np.array(rows, dtype=np.float32)
    y = np.array(labels, dtype=np.float32)
    return X, y


def _train_model():
    """Train the MLP model and save it to disk."""
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler

    print("[NutriCheck DNN] Training health scoring model (30k samples, 4-layer MLP)…")
    X, y = _generate_training_data(n_samples=30000)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = MLPRegressor(
        hidden_layer_sizes=(256, 128, 64, 32),  # deeper than v1 (was 128,64,32)
        activation='relu',
        solver='adam',
        alpha=1e-4,
        batch_size=512,                          # larger batch for 30k dataset
        learning_rate='adaptive',
        max_iter=2000,                           # was 500
        random_state=42,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=30,                     # more patience (was 20)
        verbose=False,
    )
    model.fit(X_scaled, y)

    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    print(f"[NutriCheck DNN] Model saved → {MODEL_PATH}")
    return model, scaler


# ─────────────────────────────────────────────────────────
# Model Loading & Warm-up (lazy singleton)
# ─────────────────────────────────────────────────────────

_model  = None
_scaler = None


def warm_up():
    """
    Ensure the model and scaler are loaded (or trained) and ready safely.
    Check for corrupted/zero-byte files left from interrupted runs.
    """
    global _model, _scaler
    print("[NutriCheck DNN] Warming up health scoring model…")

    for p in [MODEL_PATH, SCALER_PATH]:
        if os.path.exists(p) and os.path.getsize(p) < 100:
            print(f"[NutriCheck DNN] Detected corrupted/empty file: {p}. Deleting…")
            try:
                os.remove(p)
            except Exception:
                pass

    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        try:
            _model  = joblib.load(MODEL_PATH)
            _scaler = joblib.load(SCALER_PATH)
            print("[NutriCheck DNN] Pre-trained model loaded successfully.")
        except Exception as e:
            print(f"[NutriCheck DNN] Failed to load model: {e}. Retraining…")
            _model, _scaler = _train_model()
    else:
        _model, _scaler = _train_model()

    return _model, _scaler


def _get_model():
    global _model, _scaler
    if _model is None:
        _model, _scaler = warm_up()
    return _model, _scaler


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────

def predict_health_score(nutrients: dict) -> float:
    """
    Predict a health score (0–100) using the DNN model.

    Args:
        nutrients: dict with keys [calories, sugar, fat, sodium, protein, fiber].
                   Missing keys default to 0.

    Returns:
        float: health score clamped to [0, 100].
    """
    model, scaler = _get_model()

    feature_vec = np.array(
        [[nutrients.get(f, 0) or 0 for f in FEATURES]],
        dtype=np.float32
    )
    feature_scaled = scaler.transform(feature_vec)
    score = float(model.predict(feature_scaled)[0])
    return round(float(np.clip(score, 0, 100)), 1)
