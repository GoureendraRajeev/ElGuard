"""Step 6c: heat risk model (one prediction per district per year for March-May).

Run from the project root (the elguard folder), after aggregate.py:
    python pipeline/heat_model.py

Question: using only information known by the END of February, can we tell whether the
coming March-May will be unusually hot in a district?

Heat label (per district): average maximum temperature of March-May, compared with the
district's own warming trend.  High = hottest 20% of years, Medium = next 20%, Low = the rest.
Inputs: El Nino index of Nov, Dec and Jan, how warm Jan-Feb already was, Jan-Feb rainfall, state.
Test: leave-one-year-out (each year is predicted by a model that never saw that year).

Reads : data/processed/climate_monthly.csv, data/processed/oni_monthly.csv, config/*.json
Writes: data/processed/heat_table.csv, models/heat_model.joblib, models/heat_metrics.json
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, classification_report,
                             confusion_matrix, f1_score, roc_auc_score)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ORDER = ["Low", "Medium", "High"]
HIGH_Q, MED_Q = 0.80, 0.60
FEATURES = ["oni_nov", "oni_dec", "oni_jan", "oni_winter", "oni_change",
            "tmax_jf_anom", "rain_jf", "state_id"]

climate = pd.read_csv("data/processed/climate_monthly.csv", parse_dates=["date"])
oni = pd.read_csv("data/processed/oni_monthly.csv", parse_dates=["date"]).set_index("date")["oni"]
climate["month"] = climate["date"].dt.month
climate["tmax_anom"] = climate["tmax_c"] - climate.groupby(["district", "month"])["tmax_c"].transform("mean")

state_id = {}
for i, p in enumerate(sorted(Path("config").glob("*.json"))):
    state_id[json.loads(p.read_text(encoding="utf-8"))["state"]] = i

T = pd.Timestamp
rows = []
for (state, district), g in climate.groupby(["state", "district"]):
    g = g.set_index("date")
    for year in sorted(g.index.year.unique()):
        mar_may = [T(year, m, 1) for m in (3, 4, 5)]
        jf = [T(year, m, 1) for m in (1, 2)]
        if not all(d in g.index for d in mar_may + jf):
            continue
        o = [oni.get(T(year - 1, 11, 1), np.nan), oni.get(T(year - 1, 12, 1), np.nan), oni.get(T(year, 1, 1), np.nan)]
        rows.append({"state": state, "district": district, "year": year,
                     "tmax_marmay": g.loc[mar_may, "tmax_c"].mean(),
                     "oni_nov": o[0], "oni_dec": o[1], "oni_jan": o[2],
                     "oni_winter": np.mean(o), "oni_change": o[2] - o[0],
                     "tmax_jf_anom": g.loc[jf, "tmax_anom"].mean(),
                     "rain_jf": g.loc[jf, "rain_mm"].sum(),
                     "state_id": state_id[state]})
df = pd.DataFrame(rows).dropna(subset=FEATURES).reset_index(drop=True)

# heat compared with each district's own warming trend
df["heat_resid"] = np.nan
for _, idx in df.groupby("district").groups.items():
    x, v = df.loc[idx, "year"].values.astype(float), df.loc[idx, "tmax_marmay"].values
    df.loc[idx, "heat_resid"] = v - np.polyval(np.polyfit(x, v, 1), x)
r = df.groupby("district")["heat_resid"]
df["risk"] = np.where(df["heat_resid"] >= r.transform(lambda s: s.quantile(HIGH_Q)), "High",
                      np.where(df["heat_resid"] >= r.transform(lambda s: s.quantile(MED_Q)), "Medium", "Low"))
df["y"] = df["risk"].map({c: i for i, c in enumerate(ORDER)})
Path("data/processed").mkdir(parents=True, exist_ok=True)
df.drop(columns="y").to_csv("data/processed/heat_table.csv", index=False)

print(f"Heat table: {len(df)} rows, {df.district.nunique()} districts, years {df.year.min()}-{df.year.max()}")
print("Risk labels (%):", (df.risk.value_counts(normalize=True) * 100).reindex(ORDER).round(1).to_dict())

df["winter_enso"] = pd.cut(df["oni_winter"], [-9, -0.5, 0.5, 9], labels=["La Nina", "Neutral", "El Nino"])
print("\nShare of High heat (%) by the El Nino state of the winter:")
tab = df.groupby(["state", "winter_enso"], observed=True)["risk"].apply(lambda s: (s == "High").mean() * 100)
print(tab.unstack().round(1).to_string())
print("All states:", df.groupby("winter_enso", observed=True)["risk"].apply(lambda s: round((s == "High").mean() * 100, 1)).to_dict())

# ---- leave-one-year-out testing --------------------------------------------------------
X, y, groups = df[FEATURES], df["y"], df["year"]
models = {
    "Random Forest": lambda: RandomForestClassifier(n_estimators=300, max_depth=4, min_samples_leaf=10,
                                                    class_weight="balanced", random_state=42, n_jobs=-1),
    "Logistic Regression": lambda: make_pipeline(StandardScaler(),
                                                  LogisticRegression(class_weight="balanced", max_iter=1000)),
}
proba = {n: np.zeros((len(df), 3)) for n in models}
for tr, te in LeaveOneGroupOut().split(X, y, groups):
    for name, make in models.items():
        proba[name][te] = make().fit(X.iloc[tr], y.iloc[tr]).predict_proba(X.iloc[te])


def score(y_true, y_pred, auc):
    rep = classification_report(y_true, y_pred, labels=[0, 1, 2], target_names=ORDER,
                                output_dict=True, zero_division=0)
    return {"accuracy": accuracy_score(y_true, y_pred),
            "balanced_accuracy": balanced_accuracy_score(y_true, y_pred),
            "macro_f1": f1_score(y_true, y_pred, average="macro"),
            "high_precision": rep["High"]["precision"], "high_recall": rep["High"]["recall"],
            "auc_high": auc}


warm_jf = df["tmax_jf_anom"] >= df.groupby("district")["tmax_jf_anom"].transform(lambda s: s.quantile(HIGH_Q))
results = {
    "Baseline (always Low)": score(y, np.zeros(len(df), dtype=int), 0.5),
    "Rule: El Nino winter -> High": score(y, np.where(df["oni_winter"] >= 0.5, 2, 0),
                                          roc_auc_score(y == 2, df["oni_winter"])),
    "Rule: warm Jan-Feb -> High": score(y, np.where(warm_jf, 2, 0),
                                        roc_auc_score(y == 2, df["tmax_jf_anom"])),
}
for n in models:
    results[n] = score(y, proba[n].argmax(axis=1), roc_auc_score(y == 2, proba[n][:, 2]))
print(f"\nResults (every year tested on a model that never saw it). High is {(y == 2).mean():.1%} of rows.")
print("auc_high: 0.5 = no skill, 1.0 = perfect.")
print(pd.DataFrame(results).T.round(3).to_string())

best_name = max(models, key=lambda n: results[n]["auc_high"])
best_pred = proba[best_name].argmax(axis=1)
print(f"\nBest model (highest auc_high): {best_name}")
print("\nConfusion matrix (rows = true, columns = predicted):")
print(pd.DataFrame(confusion_matrix(y, best_pred, labels=[0, 1, 2]),
                   index=[f"true {c}" for c in ORDER], columns=[f"pred {c}" for c in ORDER]).to_string())

print("\nYears with an El Nino winter (winter index 0.5 or more):")
yr = (df.assign(actual_high=(y == 2), pred_high=(best_pred == 2), p_high=proba[best_name][:, 2])
        .groupby("year").agg(winter_oni=("oni_winter", "first"), actual_high_pct=("actual_high", "mean"),
                             predicted_high_pct=("pred_high", "mean"), avg_p_high=("p_high", "mean")))
yr = yr[yr["winter_oni"] >= 0.5]
yr[["actual_high_pct", "predicted_high_pct"]] *= 100
print(yr.round(2).to_string())

# ---- final model on all years -----------------------------------------------------------
final = models[best_name]().fit(X, y)
if best_name == "Random Forest":
    print("\nMost useful features:")
    print(pd.Series(final.feature_importances_, index=FEATURES).sort_values(ascending=False).round(3).to_string())
else:
    print("\nStrength of each input (standardised coefficient for High):")
    print(pd.Series(final[-1].coef_[2], index=FEATURES).round(2).sort_values(key=abs, ascending=False).to_string())
Path("models").mkdir(exist_ok=True)
joblib.dump({"model": final, "name": best_name, "features": FEATURES, "classes": ORDER, "level": "heat"},
            "models/heat_model.joblib")
Path("models/heat_metrics.json").write_text(json.dumps({"best": best_name, "results": results}, indent=2),
                                            encoding="utf-8")
print("\nSaved models/heat_model.joblib and models/heat_metrics.json")
