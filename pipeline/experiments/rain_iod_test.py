"""Rainfall test: does adding the Indian Ocean Dipole (IOD / DMI) help?

Run from the project root (the elguard folder), after season_model.py and download_dmi.py:
    python pipeline/rain_iod_test.py

Rule decided BEFORE seeing the results:
  The IOD "helps" only if BOTH are true
    (a) the best model with the IOD beats the best model without it by at least 0.05 in auc_high, and
    (b) before the season, the IOD correlates with a state's rainfall beyond +-0.31 (more than chance for ~40 years).
  Otherwise we report that the IOD gives no clear gain.

Reads : data/processed/season_table.csv, data/processed/dmi_monthly.csv, config/*.json
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, roc_auc_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ORDER = ["Low", "Medium", "High"]
ONI_FEATURES = ["oni_lag2", "oni_lag3", "oni_lag4", "oni_lag6", "oni_avg", "oni_trend",
                "rain_pre3", "tmax_pre3", "state_id"]
IOD_FEATURES = ONI_FEATURES + ["dmi_pre1", "dmi_pre3"]
T = pd.Timestamp

df = pd.read_csv("data/processed/season_table.csv")
dmi = pd.read_csv("data/processed/dmi_monthly.csv", parse_dates=["date"]).set_index("date")["dmi"]
months = {}
for p in Path("config").glob("*.json"):
    cfg = json.loads(p.read_text(encoding="utf-8"))
    months[cfg["state"]] = cfg["season_months"]


def dmi_features(row):
    t0 = T(int(row["year"]), min(months[row["state"]]), 1)
    pre = [dmi.get(t0 - pd.DateOffset(months=k), np.nan) for k in (1, 2, 3)]
    during = [dmi.get(T(int(row["year"]), m, 1), np.nan) for m in months[row["state"]]]
    return pd.Series({"dmi_pre1": pre[0], "dmi_pre3": np.mean(pre), "dmi_during": np.mean(during)})


df = pd.concat([df, df.apply(dmi_features, axis=1)], axis=1).dropna(subset=IOD_FEATURES).reset_index(drop=True)
df["y"] = df["risk"].map({c: i for i, c in enumerate(ORDER)})
df["rain_change"] = (df["season_rain"] / df.groupby("district")["season_rain"].transform("mean") - 1) * 100
print(f"{len(df)} district-seasons, {df.district.nunique()} districts, years {df.year.min()}-{df.year.max()}\n")

# ---- Part A: one value per state and year ----------------------------------------------
yearly = df.groupby(["state", "year"]).agg(rain=("rain_change", "mean"), oni=("oni_avg", "first"),
                                           iod_before=("dmi_pre3", "first"),
                                           iod_during=("dmi_during", "first")).reset_index()
rows = []
for state, g in yearly.groupby("state"):
    rows.append({"state": state, "years": len(g),
                 "rain vs El Nino (before season)": g["rain"].corr(g["oni"]),
                 "rain vs IOD (before season)": g["rain"].corr(g["iod_before"]),
                 "rain vs IOD (during season, not usable for a warning)": g["rain"].corr(g["iod_during"])})
corr = pd.DataFrame(rows).set_index("state")
print("Part A. Correlation with each state's season rainfall (beyond +-0.31 is more than chance):")
print(corr.round(2).to_string())

# ---- Part B: district model, with and without the IOD ----------------------------------------
models = {
    "Random Forest": lambda: RandomForestClassifier(n_estimators=300, max_depth=5, min_samples_leaf=10,
                                                    class_weight="balanced", random_state=42, n_jobs=-1),
    "Logistic Regression": lambda: make_pipeline(StandardScaler(),
                                                  LogisticRegression(class_weight="balanced", max_iter=1000)),
}


def run(features):
    proba = {n: np.zeros((len(df), 3)) for n in models}
    for tr, te in LeaveOneGroupOut().split(df[features], df["y"], df["year"]):
        for n, make in models.items():
            proba[n][te] = make().fit(df.iloc[tr][features], df.iloc[tr]["y"]).predict_proba(df.iloc[te][features])
    return proba


res, store = [], {}
for label, feats in [("El Nino only", ONI_FEATURES), ("El Nino + IOD", IOD_FEATURES)]:
    proba = run(feats)
    for n in models:
        p = proba[n]
        store[(label, n)] = p
        res.append({"inputs": label, "model": n,
                    "auc_high": roc_auc_score(df["y"] == 2, p[:, 2]),
                    "balanced_accuracy": balanced_accuracy_score(df["y"], p.argmax(axis=1))})
res = pd.DataFrame(res)
print("\nPart B. District seasons, every year tested on a model that never saw it (auc 0.5 = no skill):")
print(res.round(3).to_string(index=False))

best = res.groupby("inputs")["auc_high"].max()
gain = best["El Nino + IOD"] - best["El Nino only"]
iod_corr_ok = (corr["rain vs IOD (before season)"].abs() > 0.31).any()
print(f"\nBest auc without the IOD: {best['El Nino only']:.3f}   with the IOD: {best['El Nino + IOD']:.3f}   gain: {gain:+.3f}")
print(f"Rule (a): gain of at least 0.05?  {'yes' if gain >= 0.05 else 'no'}")
print(f"Rule (b): IOD before season beyond +-0.31 for some state?  {'yes' if iod_corr_ok else 'no'}")
print("\nVerdict:", "the IOD helps." if (gain >= 0.05 and iod_corr_ok) else
      "the IOD gives no clear gain over the El Nino-only model.")
if best["El Nino + IOD"] < 0.6:
    print("Even the best model is close to chance (auc below 0.6), so rainfall was not predicted with useful skill.")

# by state, for the better IOD model
bn = res[res.inputs == "El Nino + IOD"].sort_values("auc_high").iloc[-1]["model"]
print(f"\nauc_high by state ({bn}):")
for state, g in df.groupby("state"):
    idx = g.index.values
    a0 = roc_auc_score(g["y"] == 2, store[("El Nino only", bn)][idx, 2])
    a1 = roc_auc_score(g["y"] == 2, store[("El Nino + IOD", bn)][idx, 2])
    print(f"  {state}: El Nino only {a0:.3f}, with IOD {a1:.3f}")
