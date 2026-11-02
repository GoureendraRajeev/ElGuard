"""Prepare all the data the website needs.

Run from the project root (the elguard folder), after the forecasts have been made:
    python pipeline/export_site_data.py

Reads
  data/processed/climate_monthly.csv      actual monthly data (IMD)
  data/processed/climate_recent.csv       newer months from Open-Meteo (optional)
  data/processed/oni_monthly.csv, dmi_monthly.csv   El Nino and Indian Ocean Dipole index values
  data/processed/forecast_2027.csv        your own monthly forecast (from forecast_2027.py)
  data/processed/forecast_2026.csv        your own forecast for the rest of 2026 (optional)
  data/processed/forecast_indices.csv     forecast of the El Nino and IOD indices (from forecast_extras.py, optional)
  data/processed/rain_typical.csv         typical rainfall of each district and month (from forecast_extras.py, optional)
Writes
  site/data/site_data.json      forecasts, El Nino chart data, index values by year
  site/data/climate.json        actual monthly values of every district and year
  site/data/geojson/*.geojson   the district maps
"""
import datetime
import json
import shutil
from pathlib import Path

import pandas as pd

SLUG = {"Kerala": "kerala", "Karnataka": "karnataka", "Tamil Nadu": "tamilnadu"}
P = Path("data/processed")


def num(v, digits):
    return None if pd.isna(v) else round(float(v), digits)


climate = pd.read_csv(P / "climate_monthly.csv", parse_dates=["date"])
oni = pd.read_csv(P / "oni_monthly.csv", parse_dates=["date"]).dropna(subset=["oni"])
dmi = pd.read_csv(P / "dmi_monthly.csv", parse_dates=["date"]).dropna(subset=["dmi"]) if (P / "dmi_monthly.csv").exists() else None

# ---- actual monthly data -------------------------------------------------------------------------------
last_imd_year = int(climate["date"].dt.year.max())
if (P / "climate_recent.csv").exists():                         # months IMD does not cover yet (Open-Meteo)
    recent = pd.read_csv(P / "climate_recent.csv", parse_dates=["date"])
    recent = recent[recent["date"].dt.year > last_imd_year]
    cols = ["state", "district", "date", "rain_mm", "tmax_c", "tmin_c"]
    climate = pd.concat([climate[cols], recent[cols]], ignore_index=True)
climate["year"], climate["month"] = climate["date"].dt.year, climate["date"].dt.month
years = sorted(int(y) for y in climate["year"].unique())
yi = {y: i for i, y in enumerate(years)}
sources = {str(y): "IMD" if y <= last_imd_year else "Open-Meteo" for y in years}
data = {}
for (state, district), g in climate.groupby(["state", "district"]):
    arr = {k: [[None] * 12 for _ in years] for k in ("rain", "tmax", "tmin")}
    for r in g.itertuples():
        i, m = yi[r.year], r.month - 1
        arr["rain"][i][m], arr["tmax"][i][m], arr["tmin"][i][m] = num(r.rain_mm, 1), num(r.tmax_c, 2), num(r.tmin_c, 2)
    data[f"{SLUG[state]}|{district}"] = arr


def by_year(df, col, digits):
    out = {}
    for y in years:
        vals = [None] * 12
        for r in df[df["date"].dt.year == y].itertuples():
            vals[r.date.month - 1] = num(getattr(r, col), digits)
        out[str(y)] = vals
    return out


# ---- your own forecast ----------------------------------------------------------------------------------
frames = [pd.read_csv(f) for f in (P / "forecast_2026.csv", P / "forecast_2027.csv") if f.exists()]
if not frames:
    raise SystemExit("No forecast found. Run: python pipeline/forecast_2027.py")
fc = pd.concat(frames, ignore_index=True).drop_duplicates(["state", "district", "month"], keep="last")
fcast = {}
for r in fc.itertuples():
    fcast.setdefault((r.state, r.district), {})[r.month] = [num(v, 2) for v in (
        r.high_expected, r.high_low, r.high_high, r.low_expected, r.low_low, r.low_high)]

# ---- El Nino and IOD forecasts, typical rainfall (from forecast_extras.py) -----------------------------------------
index_fc, rain_typ = {}, {}
if (P / "forecast_indices.csv").exists():
    fi = pd.read_csv(P / "forecast_indices.csv", parse_dates=["month"])
    for r in fi.itertuples():
        index_fc[f"{r.month:%Y-%m}"] = [num(getattr(r, c, None), 2) for c in ("oni", "oni_low", "oni_high", "dmi", "dmi_low", "dmi_high")]
if (P / "rain_typical.csv").exists():
    for r in pd.read_csv(P / "rain_typical.csv").itertuples():
        rain_typ.setdefault((r.state, r.district), [None] * 12)[int(r.month) - 1] = [num(r.mean, 1), num(r.p10, 1), num(r.p90, 1)]

latest = oni.iloc[-1]
states = {}
for state, slug in SLUG.items():
    names = sorted(k.split("|")[1] for k in data if k.startswith(slug + "|"))
    states[slug] = {"name": state, "districts": [
        {"name": d, "forecast": fcast.get((state, d), {}), "rain_typical": rain_typ.get((state, d))} for d in names]}

site = {
    "generated": datetime.date.today().isoformat(),
    "forecast_note": (f"Forecasts use the El Nino index known up to {latest['date']:%B %Y} ({latest['oni']:+.2f}). "
                      "They are provisional and change when new data arrives."),
    "oni": {"latest": round(float(latest["oni"]), 2), "latest_date": f"{latest['date']:%Y-%m}",
            "phase": str(latest.get("phase", "")),
            "series": [{"date": f"{d:%Y-%m}", "oni": round(float(v), 2)} for d, v in zip(oni["date"].tail(36), oni["oni"].tail(36))]},
    "years": years,
    "index_forecast": index_fc,
    "indices": {"oni": by_year(oni, "oni", 2), "dmi": by_year(dmi, "dmi", 2) if dmi is not None else None},
    "states": states,
}
out = Path("site/data")
(out / "geojson").mkdir(parents=True, exist_ok=True)
(out / "site_data.json").write_text(json.dumps(site, separators=(",", ":")), encoding="utf-8")
(out / "climate.json").write_text(json.dumps({"years": years, "sources": sources, "data": data}, separators=(",", ":")), encoding="utf-8")
for key in SLUG.values():
    src = Path(f"data/geojson/{key}.geojson")
    if src.exists():
        shutil.copy(src, out / "geojson" / f"{key}.geojson")

n_fc = sum(1 for s in states.values() for d in s["districts"] if d["forecast"])
print(f"Saved site/data/site_data.json and climate.json ({(out / 'climate.json').stat().st_size / 1024:.0f} KB)")
print(f"Districts: {len(data)}   Actual years: {years[0]}-{years[-1]}   (IMD up to {last_imd_year}, Open-Meteo after that)")
months = sorted({m for v in fcast.values() for m in v})
print(f"Your forecast: {n_fc} districts, months {months[0]} to {months[-1]}")
print(f"El Nino / IOD forecast months: {len(index_fc)}   Typical rainfall: {len(rain_typ)} districts")
print(f"Latest El Nino index: {site['oni']['latest']} ({site['oni']['latest_date']})   IOD data: {'yes' if dmi is not None else 'no'}")
