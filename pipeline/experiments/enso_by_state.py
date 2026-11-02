"""Check how El Nino relates to season rainfall in each state separately.

Run from the project root (the elguard folder), after season_model.py:
    python pipeline/enso_by_state.py

Reads data/processed/season_table.csv
"""
import pandas as pd

df = pd.read_csv("data/processed/season_table.csv")
df["anomaly_pct"] = (df["season_rain"] / df.groupby("district")["season_rain"].transform("mean") - 1) * 100
df["enso"] = pd.cut(df["oni_avg"], [-9, -0.5, 0.5, 9], labels=["La Nina", "Neutral", "El Nino"])
df["is_high"] = df["risk"] == "High"

print("Season rainfall compared with each district's average, by ENSO state at season start:")
out = (df.groupby(["state", "enso"], observed=True)
         .agg(years=("year", "nunique"),
              mean_rain_change_pct=("anomaly_pct", "mean"),
              high_risk_pct=("is_high", lambda s: s.mean() * 100))
         .round(1))
print(out.to_string())

yearly = df.groupby(["state", "year"]).agg(rain_change=("anomaly_pct", "mean"), oni=("oni_avg", "first")).reset_index()
print("\nCorrelation between the El Nino index and state rainfall change (-1 to +1; negative = El Nino means less rain):")
for state, g in yearly.groupby("state"):
    print(f"  {state}: {g['rain_change'].corr(g['oni']):.2f}")

print("\nAverage rainfall change (%) in the three El Nino test years:")
print(yearly[yearly["year"].isin([2009, 2015, 2023])]
      .pivot(index="year", columns="state", values="rain_change").round(1).to_string())
