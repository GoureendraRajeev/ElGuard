"""Download current district boundaries (2024) for Kerala, Karnataka and Tamil Nadu.

Source: Esri India, India District Boundary 2024.
Run from the project root (the elguard folder):
    python pipeline/download_districts.py

Saves data/geojson/kerala.geojson, karnataka.geojson and tamilnadu.geojson.
Any existing file is first copied to <name>_old.geojson.
"""
import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

BASE = ("https://livingatlas.esri.in/server/rest/services/IAB2024/"
        "IAB_District_2024/MapServer/0/query")
STATES = {"kerala": ("Kerala", 14),
          "karnataka": ("Karnataka", 31),
          "tamilnadu": ("Tamil Nadu", 38)}
OUT = Path("data/geojson")


def fetch(params):
    url = BASE + "?" + urllib.parse.urlencode(params)
    return json.loads(urllib.request.urlopen(url, timeout=120).read().decode())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (state, expected) in STATES.items():
        data = fetch({
            "where": f"state='{state}'",
            "outFields": "name,state,lgd_districtname,lgd_districtcode",
            "outSR": 4326,
            "maxAllowableOffset": 0.001,   # simplify the shapes a little (about 100 m)
            "f": "geojson",
        })
        if "error" in data:
            print(f"{state}: server error: {data['error']}\n")
            continue

        feats = data.get("features", [])
        if not feats:
            # help find the right state spelling
            check = fetch({"where": "1=1", "outFields": "state",
                           "returnDistinctValues": "true",
                           "returnGeometry": "false", "f": "json"})
            states = sorted({f["attributes"]["state"] for f in check.get("features", [])})
            print(f"{state}: no districts found. State names in the service: {states}\n")
            continue

        # use the same property names as the earlier files
        for f in feats:
            p = f["properties"]
            f["properties"] = {
                "district": p.get("lgd_districtname") or p.get("name"),
                "st_nm": p.get("state"),
                "dt_code": p.get("lgd_districtcode"),
            }

        path = OUT / f"{key}.geojson"
        old = OUT / f"{key}_old.geojson"
        if path.exists() and not old.exists():
            shutil.copy(path, old)
        path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}),
                        encoding="utf-8")

        note = "OK" if len(feats) == expected else f"CHECK (plan says {expected})"
        print(f"{state}: saved {len(feats)} districts to {path}  [{note}]")
        if data.get("exceededTransferLimit"):
            print("  warning: the server may have cut the list short")
        print("  " + ", ".join(sorted(str(f["properties"]["district"]) for f in feats)) + "\n")


if __name__ == "__main__":
    main()
