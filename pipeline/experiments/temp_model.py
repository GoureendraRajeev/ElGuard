"""Temperature model: expected March-May average maximum temperature (deg C) for every district.

Run from the project root (the elguard folder), after heat_model.py:
    python pipeline/temp_model.py

How it works
  1. Each district has its own warming trend (a straight line through its March-May temperatures).
  2. A small regression (Ridge) learns how much hotter or cooler than that trend a year turns out,
     using only information known by the end of February: the El Nino index of Nov, Dec and Jan,
     how warm Jan-Feb already was, and Jan-Feb rainfall.
  3. Expected temperature = trend + that adjustment.
Test: leave-one-year-out (each year is predicted without the model having seen that year).

Reads : data/processed/heat_table.csv
Writes: models/temp_model.joblib and models/temp_metrics.json
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

table = pd.read_csv("data/processed/heat_table.csv").sort_values(["district", "year"]).reset_index(drop=True)
CANDIDATES = {
    "Ridge, 7 inputs": ["oni_nov", "oni_dec", "oni_jan", "oni_winter", "oni_change", "tmax_jf_anom", "rain_jf"],
    "Ridge, 2 inputs (winter El Nino + warm Jan-Feb)": ["oni_winter", "tmax_jf_anom"],
}
years = sorted(table["year"].unique())


def fit_trends(df):
    return {d: np.polyfit(g["year"].values.astype(float), g["tmax_marmay"].values, 1)
            for d, g in df.groupby("district")}


def trend_at(df, trends):
    return np.array([np.polyval(trends[d], y) for d, y in zip(df["district"], df["year"])])


def make_model():
    return make_pipeline(StandardScaler(), Ridge(alpha=10))


def loyo(features):
    """Predictions for every row, each year predicted by a model that never saw it."""
    pred, trend_only, mean_only = np.zeros(len(table)), np.zeros(len(table)), np.zeros(len(table))
    for y in years:
        te = (table["year"] == y).values
        train, test = table[~te], table[te]
        trends = fit_trends(train)
        tr_trend, te_trend = trend_at(train, trends), trend_at(test, trends)
        trend_only[te] = te_trend
        mean_only[te] = test["district"].map(train.groupby("district")["tmax_marmay"].mean()).values
        if features:
            m = make_model().fit(train[features], train["tmax_marmay"].values - tr_trend)
            pred[te] = te_trend + m.predict(test[features])
        else:
            pred[te] = te_trend
    return pred, trend_only, mean_only


def metrics(actual, pred, mask):
    e = (actual - pred)[mask]
    return {"MAE": float(np.abs(e).mean()), "RMSE": float(np.sqrt((e ** 2).mean()))}


actual = table["tmax_marmay"].values
last_year = table.groupby("district")["tmax_marmay"].shift(1).values
valid = ~np.isnan(last_year)                     # compare all methods on the same rows (not the first year)
el_nino = (table["oni_winter"] >= 0.5).values

runs = {}
for name, feats in CANDIDATES.items():
    runs[name], trend_only, mean_only = loyo(feats)
baselines = {"District average (no trend)": mean_only, "Trend only (no El Nino)": trend_only,
             "Same as last year": np.nan_to_num(last_year)}

rows = {}
for name, p in {**baselines, **runs}.items():
    rows[name] = {"MAE": metrics(actual, p, valid)["MAE"], "RMSE": metrics(actual, p, valid)["RMSE"],
                  "RMSE in El Nino winters": metrics(actual, p, valid & el_nino)["RMSE"],
                  "RMSE in other winters": metrics(actual, p, valid & ~el_nino)["RMSE"]}
res = pd.DataFrame(rows).T
base_mse = res.loc["Trend only (no El Nino)", "RMSE"] ** 2
res["skill vs trend"] = 1 - res["RMSE"] ** 2 / base_mse
print("Errors in deg C when predicting March-May average maximum temperature (smaller is better).")
print("skill vs trend: 0 = no better than the trend alone, 1 = perfect.\n")
print(res.round(3).to_string())

best = min(runs, key=lambda n: res.loc[n, "RMSE"])
better = res.loc[best, "RMSE"] < res.loc["Trend only (no El Nino)", "RMSE"]
print(f"\nBest model: {best}")
print("It beats the trend-only baseline." if better else
      "WARNING: it does not beat the trend-only baseline, so the El Nino inputs add nothing here.")

# typical errors for the forecast range (80% of past errors fall between low and high)
err = actual - runs[best]
q = {s: [float(np.quantile(err[(table["state"] == s).values], 0.10)),
         float(np.quantile(err[(table["state"] == s).values], 0.90))] for s in table["state"].unique()}
print("\nRange added to the expected temperature (deg C), from past errors (10% and 90%):")
for s, (lo, hi) in q.items():
    print(f"  {s}: {lo:+.2f} to {hi:+.2f}")

# final model on all years
trends = fit_trends(table)
feats = CANDIDATES[best]
final = make_model().fit(table[feats], actual - trend_at(table, trends))
print("\nEffect of each input on the adjustment (standardised coefficients):")
print(pd.Series(final[-1].coef_, index=feats).round(3).to_string())

Path("models").mkdir(exist_ok=True)
joblib.dump({"name": best, "features": feats, "model": final, "trends": {d: list(map(float, t)) for d, t in trends.items()},
             "error_range": q}, "models/temp_model.joblib")
Path("models/temp_metrics.json").write_text(json.dumps(
    {"best": best, "results": res.round(4).to_dict(orient="index"), "error_range": q}, indent=2), encoding="utf-8")
print("\nSaved models/temp_model.joblib and models/temp_metrics.json")
