"""Monthly temperature forecast for every district (default: all 12 months of 2027).

Run from the project root (the elguard folder):
    python pipeline/forecast_2027.py
    python pipeline/forecast_2027.py --year 2027
    python pipeline/forecast_2027.py --year 2026      (only the months after the latest El Nino value, e.g. Sep-Dec 2026)

For each district and each month it forecasts the average daily HIGH and the average daily LOW (deg C):
  1. the district's own warming trend for that calendar month (a straight line through its past years), and
  2. an El Nino adjustment, learned from the El Nino index that is known TODAY (latest value and its change
     over the last 3 months). Because the forecast is made now, the lead time grows with the month (about 5 months
     for January and 16 months for December), so every month gets its own test and its own model.

Test: leave-one-year-out. Each year is predicted without the model having seen that year.
Rule decided in advance: the El Nino adjustment is used for a month ONLY if it lowers the squared error by at least
10% compared with the trend alone. Otherwise that month is forecast with the trend alone.
The range comes from the model's own past errors (10% to 90%).

Reads : data/processed/climate_monthly.csv (IMD data), data/processed/oni_monthly.csv
Writes: data/processed/forecast_<year>.csv and models/forecast_metrics_<year>.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ap = argparse.ArgumentParser()
ap.add_argument("--year", type=int, default=2027)
TARGET = ap.parse_args().year
MIN_SKILL = 0.10
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
VARS = {"tmax_c": "high", "tmin_c": "low"}

clim = pd.read_csv("data/processed/climate_monthly.csv", parse_dates=["date"])
oni = pd.read_csv("data/processed/oni_monthly.csv", parse_dates=["date"]).dropna(subset=["oni"]).set_index("date")["oni"]
last = oni.index.max()

# ---- arrays: district x month x year ----------------------------------------------------------
clim["year"], clim["month"] = clim["date"].dt.year, clim["date"].dt.month
dists = clim[["state", "district"]].drop_duplicates().sort_values(["state", "district"]).reset_index(drop=True)
di = {(s, d): i for i, (s, d) in enumerate(zip(dists["state"], dists["district"]))}
all_years = sorted(clim["year"].unique())
yi = {y: j for j, y in enumerate(all_years)}
arr = {v: np.full((len(dists), 12, len(all_years)), np.nan) for v in VARS}
ii = np.array([di[(s, d)] for s, d in zip(clim["state"], clim["district"])])
kk, jj = clim["month"].values - 1, np.array([yi[y] for y in clim["year"]])
for v in VARS:
    arr[v][ii, kk, jj] = clim[v].values
complete = [j for j in range(len(all_years)) if not any(np.isnan(arr[v][:, :, j]).any() for v in VARS)]
years = np.array([all_years[j] for j in complete])
for v in VARS:
    arr[v] = arr[v][:, :, complete]
D, Y = len(dists), len(years)
print(f"{D} districts, {Y} complete years ({years[0]}-{years[-1]}), El Nino index known up to {last:%Y-%m} ({oni[last]:+.2f})")

# ---- El Nino inputs for each month: index at the forecast date minus the lead time --------------------
def lead(m):
    return (TARGET - last.year) * 12 + (m - last.month)       # months between the latest El Nino value and the target month


def features(year, m):
    t = pd.Timestamp(year, m, 1) - pd.DateOffset(months=lead(m))
    return [oni[t], oni[t] - oni[t - pd.DateOffset(months=3)]]


# only months that come AFTER the latest El Nino value can be forecast without using the future
OK = [m for m in range(12) if lead(m + 1) >= 1]
if not OK:
    raise SystemExit(f"Nothing to forecast for {TARGET}: the El Nino data already reaches {last:%Y-%m}.")
print("Months forecast:", ", ".join(MONTHS[m] for m in OK), f"(lead {lead(OK[0] + 1)} to {lead(OK[-1] + 1)} months)")
X = {m: np.array([features(int(y), m + 1) for y in years]) for m in OK}              # (Y, 2) for each month
X_target = {m: np.array([features(TARGET, m + 1)]) for m in OK}                       # (1, 2)
clipped = []
for m in OK:                                      # never extrapolate beyond the strongest El Nino in the data
    lo, hi = X[m].min(axis=0), X[m].max(axis=0)
    c = np.clip(X_target[m], lo, hi)
    if not np.allclose(c, X_target[m]):
        clipped.append(MONTHS[m])
    X_target[m] = c
if clipped:
    print(f"Note: for {', '.join(clipped)} the El Nino inputs are beyond anything in the 1985-2025 data, so they are limited to the "
          "strongest past value. A record event is therefore treated as equal to the strongest one on record.")


def trend(a, mask):
    x = years[mask].astype(float)
    xm = x.mean()
    sub = a[:, :, mask]
    ym = sub.mean(axis=2, keepdims=True)
    slope = ((x - xm) * (sub - ym)).sum(axis=2) / ((x - xm) ** 2).sum()
    return slope, ym[:, :, 0] - slope * xm


def model():
    return make_pipeline(StandardScaler(), Ridge(alpha=10))


# ---- leave-one-year-out test --------------------------------------------------------------------------
pred_trend = {v: np.zeros_like(arr[v]) for v in VARS}
pred_adj = {v: np.zeros_like(arr[v]) for v in VARS}
for j in range(Y):
    train = np.arange(Y) != j
    for v in VARS:
        slope, inter = trend(arr[v], train)
        pred_trend[v][:, :, j] = inter + slope * years[j]
        resid = arr[v][:, :, train] - (inter[:, :, None] + slope[:, :, None] * years[train][None, None, :])
        for m in OK:
            Xtr = np.tile(X[m][train], (D, 1))
            adj = model().fit(Xtr, resid[:, m, :].ravel()).predict(X[m][j:j + 1])[0]
            pred_adj[v][:, m, j] = pred_trend[v][:, m, j] + adj

rows, use, err_q = [], {}, {}
for v, name in VARS.items():
    for m in OK:
        et, ea = arr[v][:, m, :] - pred_trend[v][:, m, :], arr[v][:, m, :] - pred_adj[v][:, m, :]
        mse_t, mse_a = (et ** 2).mean(), (ea ** 2).mean()
        skill = 1 - mse_a / mse_t
        use[(v, m)] = bool(skill >= MIN_SKILL)
        e = ea if use[(v, m)] else et
        err_q[(v, m)] = [float(np.quantile(e, 0.10)), float(np.quantile(e, 0.90))]
        rows.append({"month": MONTHS[m], "temperature": name, "error trend only": np.sqrt(mse_t),
                     "error with El Nino": np.sqrt(mse_a), "skill": skill,
                     "El Nino used": "yes" if use[(v, m)] else "no"})
res = pd.DataFrame(rows)
print("\nTypical error (RMSE, deg C) when forecasting each month, each year tested without the model having seen it.")
print(f"skill = how much the El Nino adjustment lowers the squared error (needs {MIN_SKILL:.0%} to be used).\n")
for name in VARS.values():
    print(res[res["temperature"] == name].drop(columns="temperature").round(3).to_string(index=False), "\n")

# ---- forecast for the target year ----------------------------------------------------------------------------
all_years_mask = np.ones(Y, dtype=bool)
out = []
for v, name in VARS.items():
    slope, inter = trend(arr[v], all_years_mask)
    base = inter + slope * TARGET
    resid = arr[v] - (inter[:, :, None] + slope[:, :, None] * years[None, None, :])
    for m in OK:
        adj = model().fit(np.tile(X[m], (D, 1)), resid[:, m, :].ravel()).predict(X_target[m])[0] if use[(v, m)] else 0.0
        lo, hi = err_q[(v, m)]
        for d in range(D):
            val = base[d, m] + adj
            out.append({"state": dists["state"][d], "district": dists["district"][d], "month": f"{TARGET}-{m + 1:02d}",
                        "variable": v, "expected": val, "low": val + lo, "high": val + hi, "adjustment": adj})
fc = pd.DataFrame(out)
wide = fc.pivot_table(index=["state", "district", "month"], columns="variable", values=["expected", "low", "high"]).reset_index()
wide.columns = ["_".join(c).strip("_") for c in wide.columns]
wide = wide.rename(columns={"expected_tmax_c": "high_expected", "low_tmax_c": "high_low", "high_tmax_c": "high_high",
                            "expected_tmin_c": "low_expected", "low_tmin_c": "low_low", "high_tmin_c": "low_high"})
wide["mean_expected"] = (wide["high_expected"] + wide["low_expected"]) / 2
Path("data/processed").mkdir(parents=True, exist_ok=True)
wide.round(2).to_csv(f"data/processed/forecast_{TARGET}.csv", index=False)
Path("models").mkdir(exist_ok=True)
Path(f"models/forecast_metrics_{TARGET}.json").write_text(json.dumps(
    {"year": TARGET, "table": res.round(4).to_dict(orient="records"), "range": {f"{k[0]}|{MONTHS[k[1]]}": v for k, v in err_q.items()}}, indent=2),
    encoding="utf-8")

print(f"Forecast for {TARGET}: average daily HIGH (deg C), average of each state's districts, with the 10%-90% range")
for state, g in wide.groupby("state"):
    line = g.groupby("month")[["high_expected", "high_low", "high_high"]].mean()
    print(f"\n{state}")
    print("  " + "  ".join(f"{MONTHS[int(m[-2:]) - 1]} {r.high_expected:.1f} ({r.high_low:.1f}-{r.high_high:.1f})" for m, r in line.iterrows()))
print(f"\nSaved data/processed/forecast_{TARGET}.csv ({len(wide)} district-months) and models/forecast_metrics_{TARGET}.json")
