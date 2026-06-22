"""
NutriCheck — DNN Health Score Model Training & Evaluation
Run this standalone to retrain the model and see detailed accuracy metrics.
"""
import os
import sys
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.dnn_scorer import _generate_training_data, FEATURES, MODEL_PATH, SCALER_PATH, _reference_score


def _verdict(score):
    if score >= 70: return "Healthy Choice"
    if score >= 40: return "Consume in Moderation"
    return "Limit Consumption"


def train_and_evaluate():
    print("=" * 62)
    print("  NutriCheck — Health Score DNN Training & Evaluation  ")
    print("=" * 62)

    print("\n[1/4] Generating 30,000 training samples…")
    X, y = _generate_training_data(n_samples=30000)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f"      Train: {X_train.shape[0]} samples  |  Test: {X_test.shape[0]} samples")

    print("\n[2/4] Scaling features…")
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_test_sc  = scaler.transform(X_test)

    print("\n[3/4] Training MLPRegressor (256→128→64→32, up to 2000 iterations)…")
    print("      This may take 30–90 seconds on CPU.")
    from sklearn.neural_network import MLPRegressor
    import joblib

    model = MLPRegressor(
        hidden_layer_sizes=(256, 128, 64, 32),
        activation='relu',
        solver='adam',
        alpha=1e-4,
        batch_size=512,
        learning_rate='adaptive',
        max_iter=2000,
        random_state=42,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=30,
    )
    model.fit(X_train_sc, y_train)

    # Persist
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    print(f"      Done in {model.n_iter_} iterations. Model saved.")

    print("\n[4/4] Evaluating on held-out test set…")
    y_pred = model.predict(X_test_sc)
    mae   = mean_absolute_error(y_test, y_pred)
    r2    = r2_score(y_test, y_pred)
    within5 = np.mean(np.abs(y_pred - y_test) <= 5) * 100
    within10 = np.mean(np.abs(y_pred - y_test) <= 10) * 100

    print(f"\n  Mean Absolute Error : {mae:.2f} points (out of 100)")
    print(f"  R² Score            : {r2:.4f}  (1.0 = perfect)")
    print(f"  Within ±5 pts       : {within5:.1f}%")
    print(f"  Within ±10 pts      : {within10:.1f}%")

    # Per-class accuracy
    true_verdicts = [_verdict(s) for s in y_test]
    pred_verdicts = [_verdict(s) for s in y_pred]
    correct = sum(t == p for t, p in zip(true_verdicts, pred_verdicts))
    print(f"  Verdict Accuracy    : {correct / len(true_verdicts) * 100:.1f}%  "
          f"(Healthy/Moderate/Limit classification)")

    print("\n" + "─" * 62)
    print("  Real-World Food Reference Tests")
    print("─" * 62)

    # Features: [calories, sugar, fat, sodium, protein, fiber]
    foods = [
        ("Apple (medium)",               [95,   19,  0.3,    2,   0.5,  4.4]),
        ("Oatmeal (1 cup cooked)",        [158,   1,  3.2,  115,   6.0,  4.0]),
        ("Grilled Chicken Breast (100g)", [165,   0,  3.6,   74,  31.0,  0.0]),
        ("Lentil Soup (1 cup)",           [230,   5,  0.8,  470,  18.0,  8.0]),
        ("Whole Milk (240ml)",            [149,  12,  8.0,  105,   8.0,  0.0]),
        ("White Bread (2 slices)",        [160,   2,  2.0,  290,   5.0,  1.4]),
        ("Potato Chips (30g bag)",        [152,   0, 10.0,  148,   2.0,  1.0]),
        ("Coca-Cola (330ml)",             [139,  35,  0.0,   10,   0.0,  0.0]),
        ("Chocolate Bar (50g)",           [267,  28, 15.0,   40,   3.5,  1.7]),
        ("Instant Noodles (1 pack)",      [380,   4, 15.0, 1200,   7.0,  1.0]),
        ("Cheeseburger (fast food)",      [510,   9, 25.0,  955,  28.0,  2.0]),
        ("Fried Chicken Strips (100g)",   [280,   1, 17.0,  630,  18.0,  0.5]),
        ("Greek Yoghurt (170g, plain)",   [100,   7,  0.7,   65,  17.0,  0.0]),
        ("Salmon Fillet (100g)",          [208,   0, 13.0,   59,  20.0,  0.0]),
        ("Spinach Salad (100g)",          [ 23,   0.4, 0.4,  79,   2.9,  2.2]),
    ]

    print(f"\n  {'Food':<35} {'Score':>6}  {'Verdict'}")
    print(f"  {'─'*35} {'─'*6}  {'─'*22}")
    for name, vals in foods:
        vec = np.array([vals], dtype=np.float32)
        vec_sc = scaler.transform(vec)
        score = float(np.clip(model.predict(vec_sc)[0], 0, 100))
        print(f"  {name:<35} {score:>5.1f}   {_verdict(score)}")

    print("\n[SUCCESS] Model persisted. App will use the new model on next startup.")


if __name__ == '__main__':
    train_and_evaluate()
