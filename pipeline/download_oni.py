"""Download the NOAA Oceanic Nino Index (ONI) and save it as a monthly CSV.

Run from the project root:
    python pipeline/download_oni.py
    python pipeline/download_oni.py --file data/raw/oni.txt   (use a saved copy)

Output: data/processed/oni_monthly.csv with columns date, oni, phase.
"""
import argparse
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
RAW = Path("data/raw/oni.txt")
OUT = Path("data/processed/oni_monthly.csv")

# Each ONI value is a 3-month average named by its season. We place it on the middle month.
CENTER_MONTH = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
                "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}


def phase(value):
    if value >= 0.5:
        return "El Nino"
    if value <= -0.5:
        return "La Nina"
    return "Neutral"


def parse(text):
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] in CENTER_MONTH:
            season, year, _total, anom = parts
            rows.append({"date": pd.Timestamp(int(year), CENTER_MONTH[season], 1),
                         "oni": float(anom)})
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df["phase"] = df["oni"].apply(phase)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="use a local copy instead of downloading")
    args = ap.parse_args()

    if args.file:
        text = Path(args.file).read_text()
    else:
        RAW.parent.mkdir(parents=True, exist_ok=True)
        text = urllib.request.urlopen(URL, timeout=30).read().decode()
        RAW.write_text(text)

    df = parse(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"Saved {len(df)} months ({df.date.min():%Y-%m} to {df.date.max():%Y-%m}) to {OUT}")
    print(df.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
