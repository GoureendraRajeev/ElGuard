"""Download IMD gridded daily rainfall and temperature using imdlib.

Run from the project root (the elguard folder):
    python pipeline/download_imd.py --start 2020 --end 2024      (small test)
    python pipeline/download_imd.py --start 1985 --end 2024      (full data)

Files are saved in data/raw/imd/rain, data/raw/imd/tmax and data/raw/imd/tmin.
"""
import argparse
from pathlib import Path

import imdlib as imd

OUT = Path("data/raw/imd")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2020)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--vars", nargs="+", default=["rain", "tmax", "tmin"])
    args = ap.parse_args()

    for var in args.vars:
        folder = OUT / var
        folder.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {var} for {args.start}-{args.end} ...")
        imd.get_data(var, args.start, args.end, fn_format="yearwise", file_dir=str(folder))

        # quick check: open what was downloaded and show its size
        data = imd.open_data(var, args.start, args.end, "yearwise", str(folder))
        ds = data.get_xarray()
        print(ds)
        print()


if __name__ == "__main__":
    main()
