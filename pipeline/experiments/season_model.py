"""Step 6b: seasonal risk model (one prediction per district per rain season).

Run from the project root (the elguard folder), after aggregate.py:
    python pipeline/season_model.py

Why seasonal: single-month rainfall in one district is very noisy, but El Nino affects the
TOTAL rain of the main season (Jun-Sep for Kerala and Karnataka, Oct-Dec for Tamil Nadu).

Reads : data/processed/climate_monthly.csv, data/processed/oni_monthly.csv, config/*.json
Writes: data/processed/season_table.csv, models/season_model.joblib, models/season_metrics.json
Test  : leave-one-year-out (each year is predicted by a model that never saw that year).
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ORDER = ["Low", "Medium", "High"]
EL_NINO_YEARS = [2009, 2015, 2023]
HIGH_Q, MED_Q = 0.20, 0.40            # driest 20% of seasons = High, next 20% = Medium
FEATURES = ["oni_lag2", "oni_lag3", "oni_lag4", "oni_lag6", "oni_avg", "oni_trend",
            "rain_pre3", "tmax_pre3", "state_id"]

climate = pd.read_csv("data/processed/climate_monthly.csv", parse_dates=["date"])
oni = pd.read_csv("data/processed/oni_monthly.csv", parse_dates=["date"]).set_index("date")["oni"]

season, state_id = {}, {}
for i, p in enumerate(sorted(Path("config").glob("*.json"))):
    cfg = json.loads(p.read_text(encoding="utf-8"))
    season[cfg["state"]] = cfg["season_months"]
    state_id[cfg["state"]] = i

# ---- one row per district per year -------------------------------------------------
rows = []
for (state, district), g in climate.groupby(["state", "district"]):
    g = g.set_index("date")
    months = season[state]
    start = min(months)
    for year in sorted(g.index.year.unique()):
        season_dates = [pd.Timestamp(year, m, 1) for m in months]
        t0 = pd.Timestamp(year, start, 1)
        pre_dates = [t0 - pd.DateOffset(months=k) for k in (1, 2, 3)]
        if not all(d in g.index for d in season_dates + pre_dates):
            continue
        lags = {k: oni.get(t0 - pd.DateOffset(months=k), np.nan) for k in (2, 3, 4, 5, 6)}
        rows.append({
            "state": state, "district": district, "year": year,
            "season_rain": g.loc[season_dates, "rain_mm"].sum(),
            "oni_lag2": lags[2], "oni_lag3": lags[3], "oni_lag4": lags[4], "oni_lag6": lags[6],
            "oni_avg": np.mean([lags[2], lags[3], lags[4]]),
            "oni_trend": lags[2] - lags[5],
            "rain_pre3": g.loc[pre_dates, "rain_mm"].sum(),
            "tmax_pre3": g.loc[pre_dates, "tmax_c"].mean(),
            "state_id": state_id[state],
        })
df = pd.DataFrame(rows).dropna(subset=FEATURES)

# label: compare each season with the same district's other seasons
q = df.groupby("district")["season_rain"]
df["q_high"], df["q_med"] = q.transform(lambda s: s.quantile(HIGH_Q)), q.transform(lambda s: s.quantile(MED_Q))
df["risk"] = np.where(df.season_rain <= df.q_high, "High",
                      np.where(df.season_rain <= df.q_med, "Medium", "Low"))
df["y"] = df["risk"].map({c: i for i, c in enumerate(ORDER)})
Path("data/processed").mkdir(parents=True, exist_ok=True)
df.drop(columns=["q_high", "q_med", "y"]).to_csv("data/processed/season_table.csv", index=False)

print(f"Season table: {len(df)} rows, {df.district.nunique()} districts, years {df.year.min()}-{df.year.max()}")
print("Risk labels (%):", (df.risk.value_counts(normalize=True) * 100).reindex(ORDER).round(1).to_dict())
print("\nShare of High by ENSO state at season start (oni_avg):")
bins = pd.cut(df["oni_avg"], [-9, -0.5, 0.5, 9], labels=["La Nina", "Neutral", "El Nino"])
print((df.groupby(bins, observed=True)["risk"].apply(lambda s: (s == "High").mean() * 100)).round(1).to_string())

# ---- leave-one-year-out testing --------------------------------------------------------
X, y, groups = df[FEATURES], df["y"], df["year"]
models = {
    "Random Forest": lambda: RandomForestClassifier(n_estimators=300, max_depth=5, min_samples_leaf=10,
                                                    class_weight="balanced", random_state=42, n_jobs=-1),
    "Logistic Regression": lambda: make_pipeline(StandardScaler(),
                                                  LogisticRegression(class_weight="balanced", max_iter=1000)),
}


def score(y_true, y_pred):
    rep = classification_report(y_true, y_pred, labels=[0, 1, 2], target_names=ORDER,
                                output_dict=True, zero_division=0)
    return {"accuracy": accuracy_score(y_true, y_pred),
            "balanced_accuracy": balanced_accuracy_score(y_true, y_pred),
            "macro_f1": f1_score(y_true, y_pred, average="macro"),
            "high_precision": rep["High"]["precision"], "high_recall": rep["High"]["recall"]}


oof = {name: np.zeros(len(df), dtype=int) for name in models}
for tr, te in LeaveOneGroupOut().split(X, y, groups):
    for name, make in models.items():
        m = make().fit(X.iloc[tr], y.iloc[tr])
        oof[name][te] = m.predict(X.iloc[te])

preds = {"Baseline (always Low)": np.zeros(len(df), dtype=int),
         "Simple rule (El Nino -> High)": np.where(df["oni_avg"] >= 0.5, 2, 0)}
preds.update(oof)
results = {n: score(y, p) for n, p in preds.items()}
print(f"\nResults (every year tested on a model that never saw it), High is {(y == 2).mean():.1%} of rows:")
print(pd.DataFrame(results).T.round(3).to_string())

best_name = max(models, key=lambda n: results[n]["balanced_accuracy"])
best_pred = oof[best_name]
print(f"\nBest model (highest balanced accuracy): {best_name}")
print("\nConfusion matrix (rows = true, columns = predicted):")
print(pd.DataFrame(confusion_matrix(y, best_pred, labels=[0, 1, 2]),
                   index=[f"true {c}" for c in ORDER], columns=[f"pred {c}" for c in ORDER]).to_string())

print("\nEl Nino test years:")
per_year = {}
for yr in EL_NINO_YEARS:
    mask = (df.year == yr).values
    if not mask.any():
        continue
    true_high = int((y[mask] == 2).sum())
    caught = int(((best_pred[mask] == 2) & (y[mask] == 2)).sum())
    pred_high = int((best_pred[mask] == 2).sum())
    per_year[yr] = {"true_high": true_high, "caught": caught, "predicted_high": pred_high,
                    "districts": int(mask.sum())}
    print(f"  {yr}: {true_high} of {int(mask.sum())} districts were High; model caught {caught}, predicted High for {pred_high}")

# ---- final model on all years ---------------------------------------------------------------
final = models[best_name]().fit(X, y)
if best_name == "Random Forest":
    print("\nMost useful features:")
    print(pd.Series(final.feature_importances_, index=FEATURES).sort_values(ascending=False).round(3).to_string())
Path("models").mkdir(exist_ok=True)
joblib.dump({"model": final, "name": best_name, "features": FEATURES, "classes": ORDER, "level": "season"},
            "models/season_model.joblib")
Path("models/season_metrics.json").write_text(json.dumps(
    {"best": best_name, "results": results, "el_nino_years": per_year}, indent=2), encoding="utf-8")
print("\nSaved models/season_model.joblib and models/season_metrics.json")
