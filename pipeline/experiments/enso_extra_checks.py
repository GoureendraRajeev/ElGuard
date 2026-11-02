"""Extra checks on how El Nino relates to rainfall and heat in each state.

Run from the project root (the elguard folder):
    python pipeline/enso_extra_checks.py

Reads data/processed/climate_monthly.csv, data/processed/oni_monthly.csv, config/*.json
Questions decided in advance (so we do not just search for good-looking numbers):
  1. Does the El Nino index DURING the rain season relate to the season's rainfall?
  2. Does the winter (Dec-Feb) El Nino index relate to heat (Mar-May maximum temperature)?
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

climate = pd.read_csv("data/processed/climate_monthly.csv", parse_dates=["date"])
oni = pd.read_csv("data/processed/oni_monthly.csv", parse_dates=["date"]).set_index("date")["oni"]
climate["year"] = climate["date"].dt.year
climate["month"] = climate["date"].dt.month

season = {}
for p in Path("config").glob("*.json"):
    cfg = json.loads(p.read_text(encoding="utf-8"))
    season[cfg["state"]] = cfg["season_months"]


def oni_mean(year, months, shift_years=0):
    return np.nanmean([oni.get(pd.Timestamp(year + shift_years, m, 1), np.nan) for m in months])


def detrend(values):
    x = np.arange(len(values))
    return values - np.polyval(np.polyfit(x, values, 1), x)


rows = []
for state, months in season.items():
    sd = climate[climate["state"] == state]
    start = min(months)
    before = [(start - k - 1) % 12 + 1 for k in (1, 2, 3)]          # the 3 months before the season

    # rainfall: season total compared with each district's own average
    r = sd[sd["month"].isin(months)].groupby(["district", "year"])["rain_mm"].sum().reset_index()
    r["change"] = (r["rain_mm"] / r.groupby("district")["rain_mm"].transform("mean") - 1) * 100
    rain_state = r.groupby("year")["change"].mean()

    # heat: Mar-May maximum temperature compared with each district's own average for those months
    h = sd[sd["month"].isin([3, 4, 5])].copy()
    h["anom"] = h["tmax_c"] - h.groupby(["district", "month"])["tmax_c"].transform("mean")
    heat_state = h.groupby("year")["anom"].mean()
    heat_state = pd.Series(detrend(heat_state.values), index=heat_state.index)   # remove the warming trend

    years = [y for y in rain_state.index if y in heat_state.index]
    d = pd.DataFrame({
        "rain_change": rain_state.loc[years].values,
        "oni_before_season": [oni_mean(y, before) for y in years],
        "oni_during_season": [oni_mean(y, months) for y in years],
        "heat_anom": heat_state.loc[years].values,
        "oni_winter": [np.nanmean([oni.get(pd.Timestamp(y - 1, 12, 1), np.nan),
                                   oni.get(pd.Timestamp(y, 1, 1), np.nan),
                                   oni.get(pd.Timestamp(y, 2, 1), np.nan)]) for y in years],
    }, index=years)
    rows.append({
        "state": state, "years": len(d),
        "rain vs ONI before season": d["rain_change"].corr(d["oni_before_season"]),
        "rain vs ONI during season": d["rain_change"].corr(d["oni_during_season"]),
        "Mar-May heat vs winter ONI": d["heat_anom"].corr(d["oni_winter"]),
    })

print("Correlations (-1 to +1) using one value per year for each state.")
print("Negative rain correlation = El Nino goes with less rain. Positive heat correlation = El Nino goes with hotter Mar-May.\n")
print(pd.DataFrame(rows).set_index("state").round(2).to_string())
print("\nWith about 40 years, a correlation must be roughly above 0.31 (or below -0.31) to be more than chance.")
