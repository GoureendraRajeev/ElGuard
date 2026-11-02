"""Download recent daily weather from Open-Meteo and turn it into monthly values for every district.

Use this for the months that IMD's yearly files do not cover yet (for example 2026 up to the latest complete month).
Open-Meteo is free and needs no key. Its data is ERA5 reanalysis, a different source from IMD, so the
website labels these years with their source.

Run from the project root (the elguard folder), after download_districts.py:
    python pipeline/download_recent.py
    python pipeline/download_recent.py --start 2026-01-01 --end 2026-10-20
    python pipeline/download_recent.py --batch 3 --pause 30        (even gentler, if you still get "429 Too Many Requests")

Open-Meteo limits how many requests one user can make per minute, hour and day, and a request for many places over many
days counts as many requests. So this script asks for only a few districts at a time, waits between requests, waits and
tries again when the server says "429 Too Many Requests", and saves every answer in data/raw/open_meteo, so a second
run does not download the same thing again.

Writes data/processed/climate_recent.csv  (state, district, date, rain_mm, tmax_c, tmin_c)
Only complete months are kept with values (rain = monthly total, temperatures = monthly average of the daily highest and lowest).
"""
import argparse
import calendar
import datetime
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

URL = "https://archive-api.open-meteo.com/v1/archive"
STATES = {"kerala": "Kerala", "karnataka": "Karnataka", "tamilnadu": "Tamil Nadu"}
CACHE = Path("data/raw/open_meteo")


class ApiError(Exception):
    pass


def ring_stats(ring):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring[:-1], ring[1:]):
        f = x0 * y1 - x1 * y0
        a += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(a) < 1e-12:
        return 0.0, float(np.mean([p[0] for p in ring])), float(np.mean([p[1] for p in ring]))
    return abs(a / 2), cx / (3 * a), cy / (3 * a)


def district_points():
    pts = []
    for key, state in STATES.items():
        gj = json.loads(Path(f"data/geojson/{key}.geojson").read_text(encoding="utf-8"))
        for f in gj["features"]:
            g = f["geometry"]
            rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
            _, lon, lat = max((ring_stats(r) for r in rings), key=lambda s: s[0])
            pts.append((state, f["properties"]["district"], lat, lon))
    return pts


def reason_of(text):
    try:
        return str(json.loads(text).get("reason", text))[:300]
    except Exception:
        return text[:300]


def get_json(url, sleep=time.sleep):
    """One request with a saved copy, and patient retries when the server says it is busy."""
    cache = CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")), True
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(1, 7):
        wait, reason = None, ""
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
            if isinstance(data, dict) and data.get("error"):
                raise ApiError(str(data.get("reason", "unknown error")))
            data = data if isinstance(data, list) else [data]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
            return data, False
        except urllib.error.HTTPError as e:
            reason = reason_of(e.read().decode("utf-8", errors="ignore"))
            if e.code != 429 and "limit" not in reason.lower():
                wait = 10 * attempt
            else:
                try:
                    wait = int(e.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    wait = 65 * attempt
        except ApiError as e:
            reason = str(e)
            if "limit" not in reason.lower() and "too many" not in reason.lower():
                raise
            wait = 65 * attempt
        except Exception as e:                 # network problems
            reason, wait = str(e), 10 * attempt
        low = reason.lower()
        if "daily" in low:
            raise SystemExit("Open-Meteo's DAILY limit is used up. Run the same command again tomorrow: "
                             "everything already downloaded is saved and will not be asked for again.")
        if "hourly" in low:
            wait = max(wait, 300)
        if attempt == 6:
            raise SystemExit(f"Still failing after 6 tries: {reason}\nWait a while and run the same command again. "
                             "Batches that already worked are saved.")
        print(f"    server says: {reason[:120] or 'busy'}. Waiting {wait} seconds, then trying again ({attempt}/5)")
        sleep(wait)


def monthly(daily):
    df = pd.DataFrame({"time": pd.to_datetime(daily["time"]), "tmax": daily["temperature_2m_max"],
                       "tmin": daily["temperature_2m_min"], "rain": daily["precipitation_sum"]})
    df["date"] = df["time"].dt.to_period("M").dt.to_timestamp()
    g = df.groupby("date")
    out = g.agg(tmax_c=("tmax", "mean"), tmin_c=("tmin", "mean"), rain_mm=("rain", "sum"),
                n_max=("tmax", "count"), n_min=("tmin", "count"), n_rain=("rain", "count"))
    days = np.array([calendar.monthrange(d.year, d.month)[1] for d in out.index])
    out.loc[out["n_max"].values != days, "tmax_c"] = np.nan
    out.loc[out["n_min"].values != days, "tmin_c"] = np.nan
    out.loc[out["n_rain"].values != days, "rain_mm"] = np.nan
    return out[["rain_mm", "tmax_c", "tmin_c"]].reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01",
                    help="first day (default 2026-01-01, because IMD already covers the years before)")
    ap.add_argument("--end", default=(datetime.date.today() - datetime.timedelta(days=6)).isoformat(),
                    help="last day to download (default: 6 days ago, because the newest days are not ready yet)")
    ap.add_argument("--batch", type=int, default=5, help="districts per request (default 5)")
    ap.add_argument("--pause", type=int, default=15, help="seconds to wait between requests (default 15)")
    args = ap.parse_args()

    pts = district_points()
    n_batches = -(-len(pts) // args.batch)
    print(f"{len(pts)} districts in {n_batches} requests, {args.start} to {args.end}, {args.pause} seconds between requests")
    rows = []
    for b, i in enumerate(range(0, len(pts), args.batch), start=1):
        batch = pts[i:i + args.batch]
        params = {"latitude": ",".join(f"{p[2]:.3f}" for p in batch), "longitude": ",".join(f"{p[3]:.3f}" for p in batch),
                  "start_date": args.start, "end_date": args.end, "timezone": "Asia/Kolkata",
                  "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"}
        data, cached = get_json(URL + "?" + urllib.parse.urlencode(params))
        print(f"  request {b} of {n_batches}: districts {i + 1} to {i + len(batch)}" + (" (already saved)" if cached else ""))
        for p, res in zip(batch, data):
            m = monthly(res["daily"])
            m.insert(0, "district", p[1])
            m.insert(0, "state", p[0])
            rows.append(m)
        if not cached and b < n_batches:
            time.sleep(args.pause)
    df = pd.concat(rows, ignore_index=True)
    df[["rain_mm", "tmax_c", "tmin_c"]] = df[["rain_mm", "tmax_c", "tmin_c"]].round(2)
    out = Path("data/processed/climate_recent.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    done = df.dropna(subset=["tmax_c"])
    print(f"\nSaved {len(df)} district-months to {out}")
    print(f"Complete months: {done['date'].min():%Y-%m} to {done['date'].max():%Y-%m}")
    print(df[df["district"] == df["district"].iloc[0]].tail(4).to_string(index=False))


if __name__ == "__main__":
    main()
