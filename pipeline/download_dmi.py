"""Download the Indian Ocean Dipole index (DMI) and save it as a monthly CSV.

Run from the project root (the elguard folder):
    python pipeline/download_dmi.py
    python pipeline/download_dmi.py --file data/raw/dmi.txt     (use a saved copy)

Output: data/processed/dmi_monthly.csv with columns date, dmi.
The first source that works is used (NOAA PSL file, then NOAA CPC web page).
"""
import argparse
import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

SOURCES = [
    ("NOAA PSL (HadISST)", "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data"),
    ("NOAA CPC (ERSSTv5)", "https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/indian/IODMI/DMI_month.html"),
]
RAW = Path("data/raw/dmi.txt")
OUT = Path("data/processed/dmi_monthly.csv")
NUM = re.compile(r"^-?\d+(\.\d+)?$")


def parse(text):
    """Find rows made of a year followed by 12 monthly values (works for the PSL file and the CPC table)."""
    text = re.sub(r"<[^>]+>", " ", text)            # remove HTML tags, if any
    tokens = text.replace("|", " ").split()
    rows, i = [], 0
    while i + 12 < len(tokens):
        t = tokens[i]
        if re.fullmatch(r"(18|19|20)\d{2}", t) and all(NUM.match(x) for x in tokens[i + 1:i + 13]):
            vals = [float(x) for x in tokens[i + 1:i + 13]]
            if all(v == -9999 or abs(v) < 5 for v in vals):
                for m, v in enumerate(vals, start=1):
                    rows.append({"date": pd.Timestamp(int(t), m, 1), "dmi": np.nan if v <= -999 else v})
                i += 13
                continue
        i += 1
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date").dropna().reset_index(drop=True)
    return df


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", errors="ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="use a local copy instead of downloading")
    args = ap.parse_args()

    df, used = None, None
    if args.file:
        df, used = parse(Path(args.file).read_text(encoding="utf-8", errors="ignore")), args.file
    else:
        for name, url in SOURCES:
            try:
                text = fetch(url)
                cand = parse(text)
                if len(cand) > 500:
                    RAW.parent.mkdir(parents=True, exist_ok=True)
                    RAW.write_text(text, encoding="utf-8")
                    df, used = cand, name
                    break
                print(f"{name}: downloaded, but could not read the table ({len(cand)} months found)")
            except Exception as e:
                print(f"{name}: failed ({e})")
    if df is None or df.empty:
        raise SystemExit("Could not get the DMI data. Save the NOAA file as data/raw/dmi.txt and run with --file data/raw/dmi.txt")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"Source: {used}")
    print(f"Saved {len(df)} months ({df.date.min():%Y-%m} to {df.date.max():%Y-%m}) to {OUT}")
    print(df.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
