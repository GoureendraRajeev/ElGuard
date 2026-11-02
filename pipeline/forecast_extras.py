"""Forecasts for the other columns of the table: El Nino index, Indian Ocean Dipole index, and rainfall.

Run from the project root (the elguard folder):
    python pipeline/forecast_extras.py
    python pipeline/forecast_extras.py --until 2027-12

EL NINO INDEX AND INDIAN OCEAN DIPOLE (our own statistical forecast)
  For every lead time (1 month, 2 months, ...) a small regression predicts the index from its latest value, its change over
  the last 3 months and the season of the target month. Each lead is tested with leave-one-year-out and compared with two
  simple methods (keep the latest value, or use the normal for that month). The range is the 10%-90% range of the past errors.
  These ocean indices are hard to forecast far ahead, so the range gets wide at long leads. That is shown, not hidden.

RAINFALL (typical value, NOT a forecast)
  Our tests found no useful skill for forecasting rainfall. So for rainfall we show what is typical for each district and
  month: the average of past years, with the 10%-90% range of past years. The script also prints how large the real
  month-to-month variation is.

Reads : data/processed/oni_monthly.csv, dmi_monthly.csv, climate_monthly.csv
Writes: data/processed/forecast_indices.csv, data/processed/rain_typical.csv, models/forecast_extras_metrics.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneGroupOut

ap = argparse.ArgumentParser()
ap.add_argument("--until", default="2027-12", help="last month to forecast, as YYYY-MM")
UNTIL = pd.Timestamp(ap.parse_args().until + "-01")
P = Path("data/processed")


def design(x, d3, month):
    ang = 2 * np.pi * np.asarray(month) / 12
    sn, cs = np.sin(ang), np.cos(ang)
    return np.column_stack([x, d3, sn, cs, np.asarray(x) * sn, np.asarray(x) * cs])


def forecast_index(series, name):
    s = series.dropna()
    s = s[s.index >= "1950-01-01"].asfreq("MS")
    origin = s.dropna().index.max()
    n_leads = (UNTIL.year - origin.year) * 12 + UNTIL.month - origin.month
    base = pd.DataFrame({"x": s, "d3": s - s.shift(3)})
    now = base.loc[origin]
    rows, stats = [], []
    for h in range(1, n_leads + 1):
        d = base.assign(y=s.shift(-h)).dropna()
        tm = (d.index + pd.DateOffset(months=h)).month.values
        X, y, groups = design(d["x"], d["d3"], tm), d["y"].values, d.index.year.values
        pred, clim = np.zeros(len(d)), np.zeros(len(d))
        for tr, te in LeaveOneGroupOut().split(X, y, groups):
            pred[te] = Ridge(alpha=1.0).fit(X[tr], y[tr]).predict(X[te])
            cm = pd.Series(y[tr]).groupby(tm[tr]).mean()
            clim[te] = pd.Series(tm[te]).map(cm).values
        err = y - pred
        q10, q90 = np.quantile(err, [0.10, 0.90])
        stats.append({"lead": h, "model": float(np.sqrt((err ** 2).mean())),
                      "keep latest": float(np.sqrt(((y - d["x"].values) ** 2).mean())),
                      "normal for the month": float(np.sqrt(((y - clim) ** 2).mean()))})
        f = Ridge(alpha=1.0).fit(X, y).predict(design([now["x"]], [now["d3"]], [(origin + pd.DateOffset(months=h)).month]))[0]
        rows.append({"month": origin + pd.DateOffset(months=h), name: f, f"{name}_low": f + q10, f"{name}_high": f + q90})
    return origin, pd.DataFrame(rows), pd.DataFrame(stats)


out, metrics = None, {}
for name, file in (("oni", "oni_monthly.csv"), ("dmi", "dmi_monthly.csv")):
    if not (P / file).exists():
        print(f"{file} not found, skipping {name}")
        continue
    ser = pd.read_csv(P / file, parse_dates=["date"]).set_index("date")[name]
    origin, fc, st = forecast_index(ser, name)
    print(f"\n{name.upper()}: latest value {ser.dropna().iloc[-1]:+.2f} in {origin:%Y-%m}. Typical error (RMSE) of each method at some lead times:")
    show = st[st["lead"].isin([1, 2, 3, 4, 6, 9, 12, 16, 19])].set_index("lead").round(2)
    print(show.to_string())
    out = fc if out is None else out.merge(fc, on="month", how="outer")
    metrics[name] = st.round(4).to_dict(orient="records")
if out is not None:
    out = out.sort_values("month").round(3)
    out.to_csv(P / "forecast_indices.csv", index=False)
    print("\nForecast of the indices (value and 10%-90% range):")
    print(out.assign(month=out["month"].dt.strftime("%Y-%m")).to_string(index=False))

# ---- rainfall: typical values ------------------------------------------------------------------------------------------
clim = pd.read_csv(P / "climate_monthly.csv", parse_dates=["date"])
clim["month"] = clim["date"].dt.month
g = clim.groupby(["state", "district", "month"])["rain_mm"]
typ = g.agg(mean="mean", p10=lambda s: s.quantile(0.10), p90=lambda s: s.quantile(0.90)).reset_index().round(1)
typ.to_csv(P / "rain_typical.csv", index=False)
rows = []
for m in range(1, 13):
    a = clim[clim["month"] == m].pivot_table(index=["state", "district"], columns=clim["date"].dt.year, values="rain_mm").values
    n = a.shape[1]
    pred = (a.sum(axis=1, keepdims=True) - a) / (n - 1)               # average of the other years
    rows.append({"month": m, "average (mm)": np.nanmean(a), "typical error (mm)": float(np.sqrt(np.nanmean((a - pred) ** 2)))})
rv = pd.DataFrame(rows)
rv["error as % of average"] = rv["typical error (mm)"] / rv["average (mm)"] * 100
print("\nRainfall: using the average of past years for a month, the typical miss (leave-one-year-out), averaged over all districts:")
print(rv.round(1).to_string(index=False))
print("A large percentage means that month's rainfall changes a lot from year to year, so the average is only a rough guide.")

Path("models").mkdir(exist_ok=True)
metrics["rain"] = rv.round(3).to_dict(orient="records")
Path("models/forecast_extras_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
print("\nSaved data/processed/forecast_indices.csv, data/processed/rain_typical.csv and models/forecast_extras_metrics.json")
