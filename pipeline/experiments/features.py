"""Step 5: build the training table (features + risk labels).

Run from the project root (the elguard folder), after aggregate.py:
    python pipeline/features.py

Reads : data/processed/climate_monthly.csv, data/processed/oni_monthly.csv, config/*.json
Writes: data/processed/training_table.csv and data/processed/features.json

Risk label (version 2): each month's rainfall is compared with the rainfall of the SAME
district in the SAME calendar month in the training years.
    High   = rainfall in the driest 20% of those years
    Medium = rainfall in the next 20%
    Low    = the rest
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

TEST_YEARS = [2009, 2015, 2023]   # El Nino years kept aside for testing
MIN_NORMAL_MM = 20                # months with less normal rain than this are not labelled
HIGH_Q, MED_Q = 0.20, 0.40        # driest 20% = High, next 20% = Medium
ORDER = ["Low", "Medium", "High"]

climate = pd.read_csv("data/processed/climate_monthly.csv", parse_dates=["date"])
oni = pd.read_csv("data/processed/oni_monthly.csv", parse_dates=["date"]).sort_values("date")

# El Nino index from 1 to 6 months earlier
for k in range(1, 7):
    oni[f"oni_lag{k}"] = oni["oni"].shift(k)
df = climate.merge(oni, on="date", how="left")

df["year"] = df["date"].dt.year
df["month"] = df["date"].dt.month

# is the month inside the state's main rain season (from the config files)?
season = {}
for p in Path("config").glob("*.json"):
    cfg = json.loads(p.read_text(encoding="utf-8"))
    season[cfg["state"]] = cfg["season_months"]
df["in_season"] = [int(m in season.get(s, [])) for s, m in zip(df["state"], df["month"])]

# past weather of the same district
df = df.sort_values(["district", "date"]).reset_index(drop=True)
g = df.groupby("district")
gaps = g["date"].diff().dropna().dt.days
assert gaps.between(28, 31).all(), "some months are missing, check climate_monthly.csv"
for k in (1, 2, 3):
    df[f"rain_lag{k}"] = g["rain_mm"].shift(k)
df["tmax_lag1"] = g["tmax_c"].shift(1)
df["tmin_lag1"] = g["tmin_c"].shift(1)

# normal rainfall and the dry-year limits for each district and month, from the training years only
train = df[~df["year"].isin(TEST_YEARS)]
grp = train.groupby(["district", "month"])["rain_mm"]
limits = pd.DataFrame({"normal_mm": grp.mean(),
                       "q_high": grp.quantile(HIGH_Q),
                       "q_med": grp.quantile(MED_Q)}).reset_index()
df = df.merge(limits, on=["district", "month"], how="left")

# risk label
enough = df["normal_mm"] >= MIN_NORMAL_MM
df["deficit_pct"] = np.where(enough, (df["normal_mm"] - df["rain_mm"]) / df["normal_mm"] * 100, np.nan)
df["risk"] = np.where(df["rain_mm"] <= df["q_high"], "High",
                      np.where(df["rain_mm"] <= df["q_med"], "Medium", "Low"))
df.loc[~enough, "risk"] = np.nan
df["is_test"] = df["year"].isin(TEST_YEARS).astype(int)

# the model sees only information from BEFORE the month it predicts
FEATURES = ([f"oni_lag{k}" for k in range(1, 7)] +
            [f"rain_lag{k}" for k in (1, 2, 3)] + ["tmax_lag1", "tmin_lag1", "month"])
table = df.dropna(subset=FEATURES + ["risk"]).copy()

keep = ["state", "district", "date", "year", "month", "in_season", "is_test",
        "rain_mm", "normal_mm", "deficit_pct", "risk", "oni", "phase"] + \
       [f for f in FEATURES if f != "month"]
Path("data/processed").mkdir(parents=True, exist_ok=True)
table[keep].to_csv("data/processed/training_table.csv", index=False)
Path("data/processed/features.json").write_text(json.dumps(FEATURES), encoding="utf-8")

print(f"Saved {len(table)} labelled rows ({table.district.nunique()} districts) to data/processed/training_table.csv")
print("Rows per state:", table.groupby("state").size().to_dict())
print("\nRisk labels, all rows (%):")
print((table["risk"].value_counts(normalize=True) * 100).reindex(ORDER).round(1).to_string())
print("\nRisk labels in the test years (%):")
print((table[table.is_test == 1]["risk"].value_counts(normalize=True) * 100).reindex(ORDER).round(1).to_string())
print("\nShare of each risk label by El Nino phase (%):")
print((pd.crosstab(table["phase"], table["risk"], normalize="index") * 100)[ORDER].round(1).to_string())