"""Step 4: average IMD rainfall and temperature grids inside each district.

Run from the project root (the elguard folder), after download_imd.py and download_districts.py:
    python pipeline/aggregate.py --start 2020 --end 2024

Output: data/processed/climate_monthly.csv
Columns: state, district, date, rain_mm (monthly total), tmax_c, tmin_c (monthly averages)

How it works: for each district, find the grid cells whose centre lies inside the district,
average them, then turn the daily values into monthly values. If a district is so small that
no cell centre falls inside, the nearest grid cell that has data is used instead.
"""
import argparse
import json
from pathlib import Path

import imdlib as imd
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.path import Path as MPath

STATES = ["kerala", "karnataka", "tamilnadu"]
VARS = {"rain": ("rain_mm", "sum"), "tmax": ("tmax_c", "mean"), "tmin": ("tmin_c", "mean")}


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def cell_indices(feature, lats, lons, valid):
    """Return (lat index, lon index, used_nearest) for the grid cells of one district."""
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    pts = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    inside = np.zeros(len(pts), dtype=bool)
    rings = []
    for poly in polygons(feature["geometry"]):
        ring = np.array(poly[0])[:, :2]
        rings.append(ring)
        m = MPath(ring).contains_points(pts)
        for hole in poly[1:]:
            m &= ~MPath(np.array(hole)[:, :2]).contains_points(pts)
        inside |= m
    inside &= valid.ravel()

    nearest = not inside.any()
    if nearest:
        cx, cy = np.vstack(rings).mean(axis=0)
        dist = (pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2
        dist[~valid.ravel()] = np.inf
        idx = np.array([np.argmin(dist)])
    else:
        idx = np.where(inside)[0]
    return idx // len(lons), idx % len(lons), nearest


def district_monthly(da, ilat, ilon, how):
    pts = da.isel(lat=xr.DataArray(ilat, dims="p"), lon=xr.DataArray(ilon, dims="p"))
    daily = pts.mean("p", skipna=True)
    res = daily.resample(time="MS")
    out = res.sum(skipna=False) if how == "sum" else res.mean()
    return out.to_series()


def load(var, start, end):
    folder = Path("data/raw/imd") / var
    data = imd.open_data(var, start, end, "yearwise", str(folder))
    da = data.get_xarray()[var]
    return da.where(da > -900)          # IMD uses -999 for "no data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2020)
    ap.add_argument("--end", type=int, default=2024)
    args = ap.parse_args()

    tables = []
    for var, (col, how) in VARS.items():
        if not (Path("data/raw/imd") / var).exists():
            print(f"skipping {var}: folder data/raw/imd/{var} not found")
            continue
        print(f"Reading {var} ...")
        da = load(var, args.start, args.end)
        lats, lons = da["lat"].values, da["lon"].values
        valid = da.notnull().any("time").values

        rows = []
        for key in STATES:
            gj = json.loads(Path(f"data/geojson/{key}.geojson").read_text(encoding="utf-8"))
            for feat in gj["features"]:
                ilat, ilon, nearest = cell_indices(feat, lats, lons, valid)
                series = district_monthly(da, ilat, ilon, how)
                name = feat["properties"]["district"]
                state = feat["properties"]["st_nm"]
                if nearest:
                    print(f"  {state} / {name}: no cell centre inside, used nearest cell")
                for date, value in series.items():
                    rows.append({"state": state, "district": name, "date": date, col: value})
        tables.append(pd.DataFrame(rows))

    if not tables:
        print("No data found. Run download_imd.py first.")
        return
    df = tables[0]
    for t in tables[1:]:
        df = df.merge(t, on=["state", "district", "date"], how="outer")
    df = df.sort_values(["state", "district", "date"]).reset_index(drop=True)

    out = Path("data/processed/climate_monthly.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nSaved {len(df)} rows ({df.district.nunique()} districts) to {out}")
    print(df.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
