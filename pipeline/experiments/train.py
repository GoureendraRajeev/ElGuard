"""Step 6: train and test the risk models.

Run from the project root (the elguard folder), after features.py:
    python pipeline/train.py

Reads : data/processed/training_table.csv, data/processed/features.json
Writes: models/best_model.joblib and models/metrics.json

Training uses every year except 2009, 2015 and 2023. Those three El Nino years are used only for testing.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

ORDER = ["Low", "Medium", "High"]

table = pd.read_csv("data/processed/training_table.csv", parse_dates=["date"])
FEATURES = json.loads(Path("data/processed/features.json").read_text(encoding="utf-8"))
table["y"] = table["risk"].map({c: i for i, c in enumerate(ORDER)})

train = table[table.is_test == 0]
test = table[table.is_test == 1]
Xtr, ytr = train[FEATURES], train["y"]
Xte, yte = test[FEATURES], test["y"]
print(f"Training rows: {len(train)}   Test rows (2009, 2015, 2023): {len(test)}\n")

models = {
    "Random Forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=5,
                                            class_weight="balanced", random_state=42, n_jobs=-1),
    "XGBoost": XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                             colsample_bytree=0.8, objective="multi:softprob",
                             eval_metric="mlogloss", random_state=42, n_jobs=-1),
}


def score(y_true, y_pred):
    rep = classification_report(y_true, y_pred, labels=[0, 1, 2], target_names=ORDER,
                                output_dict=True, zero_division=0)
    return {"accuracy": accuracy_score(y_true, y_pred),
            "balanced_accuracy": balanced_accuracy_score(y_true, y_pred),
            "macro_f1": f1_score(y_true, y_pred, average="macro"),
            "high_precision": rep["High"]["precision"],
            "high_recall": rep["High"]["recall"]}


results = {"Baseline (always Low)": score(yte, np.zeros(len(yte), dtype=int))}
fitted = {}
for name, model in models.items():
    if name == "XGBoost":
        model.fit(Xtr, ytr, sample_weight=compute_sample_weight("balanced", ytr))
    else:
        model.fit(Xtr, ytr)
    fitted[name] = model
    results[name] = score(yte, model.predict(Xte))

print("Results on the test years:")
print(pd.DataFrame(results).T.round(3).to_string())

best_name = max(fitted, key=lambda n: results[n]["macro_f1"])
best = fitted[best_name]
pred = best.predict(Xte)
print(f"\nBest model (highest macro F1): {best_name}")
print("\nConfusion matrix (rows = true, columns = predicted):")
print(pd.DataFrame(confusion_matrix(yte, pred, labels=[0, 1, 2]),
                   index=[f"true {c}" for c in ORDER],
                   columns=[f"pred {c}" for c in ORDER]).to_string())

print("\nBy test year:")
per_year = {}
for yr, part in test.assign(pred=pred).groupby("year"):
    s = score(part["y"], part["pred"])
    per_year[int(yr)] = s
    print(f"  {yr}: accuracy {s['accuracy']:.3f}, High recall {s['high_recall']:.3f}")

print("\nMost useful features:")
imp = pd.Series(best.feature_importances_, index=FEATURES).sort_values(ascending=False)
print(imp.head(8).round(3).to_string())

Path("models").mkdir(exist_ok=True)
joblib.dump({"model": best, "name": best_name, "features": FEATURES, "classes": ORDER},
            "models/best_model.joblib")
Path("models/metrics.json").write_text(json.dumps(
    {"best": best_name, "test_years": [2009, 2015, 2023], "results": results, "per_year": per_year},
    indent=2), encoding="utf-8")
print("\nSaved models/best_model.joblib and models/metrics.json")
