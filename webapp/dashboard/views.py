import json

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render

STATES = {"kerala": "Kerala", "karnataka": "Karnataka", "tamilnadu": "Tamil Nadu"}
_cache = {}


def load(filename):
    """Read a JSON file from site/data, and read it again if the file has been replaced."""
    path = settings.DATA_DIR / filename
    if not path.exists():
        raise Http404(f"{filename} not found. Run: python pipeline/export_site_data.py")
    mtime = path.stat().st_mtime
    if _cache.get(filename, (None, None))[0] != mtime:
        _cache[filename] = (mtime, json.loads(path.read_text(encoding="utf-8")))
    return _cache[filename][1]


def check_state(slug):
    if slug not in STATES:
        raise Http404("Unknown state")
    return slug


def index(request):
    return render(request, "dashboard/index.html")


def overview(request):
    d = load("site_data.json")
    return JsonResponse({
        "generated": d.get("generated", ""), "forecast_note": d.get("forecast_note", ""), "oni": d["oni"],
        "years": d["years"], "indices": d.get("indices", {"oni": {}, "dmi": None}), "index_forecast": d.get("index_forecast", {}),
        "states": [{"slug": k, "name": v} for k, v in STATES.items()],
    })


def forecast(request, state):
    return JsonResponse(load("site_data.json")["states"][check_state(state)])


def climate(request, state):
    """Actual monthly rainfall and temperatures of one district, for every year."""
    check_state(state)
    name = request.GET.get("name", "")
    c = load("climate.json")
    entry = c["data"].get(f"{state}|{name}")
    if entry is None:
        raise Http404("District not found")
    return JsonResponse({"district": name, "state": STATES[state], "years": c["years"],
                         "sources": c.get("sources", {}), **entry})


def geojson(request, state):
    check_state(state)
    path = settings.DATA_DIR / "geojson" / f"{state}.geojson"
    if not path.exists():
        raise Http404("Map file not found")
    return FileResponse(open(path, "rb"), content_type="application/json")
