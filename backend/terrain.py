"""Terrain elevation grid for the map world — fetched once, cached like OSM.

Samples a square grid of ground elevations over the loaded area (SRTM via the
Open-Elevation API — one POST for the whole grid; Open-Meteo's elevation API as
fallback, stdlib-only) and caches the result in backend/data/ next to the OSM
cache. The frontend renders it as an optional hillshaded 2.5D terrain and
lifts buildings/roads/agents to their ground height.

Purely cosmetic for now: the energy model does not read elevation. If both
APIs are unreachable on first load the world simply stays flat (returns None)
— the sim never blocks on terrain.
"""
import json
import math
import time
import urllib.parse
import urllib.request

from .osm_world import DATA_DIR

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/elevation"
GRID_N = 33          # grid is GRID_N x GRID_N samples (33x33 = 1089 points)
MARGIN = 1.15        # sample slightly beyond the world disk
_HDRS = {"User-Agent": "city-energy-analysis-demo/1.0"}


def _fetch_open_elevation(lats, lons):
    """All points in one POST — no per-request rate-limit dance."""
    body = json.dumps({"locations": [
        {"latitude": round(la, 5), "longitude": round(lo, 5)}
        for la, lo in zip(lats, lons)]}).encode()
    req = urllib.request.Request(
        OPEN_ELEVATION_URL, data=body,
        headers={**_HDRS, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return [p["elevation"] for p in json.load(r)["results"]]


def _fetch_open_meteo(lats, lons):
    """Fallback: 100 coordinates per GET, politely paced (free-tier limits)."""
    out = []
    for i in range(0, len(lats), 100):
        if i:
            time.sleep(1.0)
        q = urllib.parse.urlencode({
            "latitude": ",".join(f"{v:.5f}" for v in lats[i:i + 100]),
            "longitude": ",".join(f"{v:.5f}" for v in lons[i:i + 100]),
        })
        req = urllib.request.Request(f"{OPEN_METEO_URL}?{q}", headers=_HDRS)
        with urllib.request.urlopen(req, timeout=30) as r:
            out.extend(json.load(r)["elevation"])
    return out


def _fetch_elevations(lats, lons):
    try:
        return _fetch_open_elevation(lats, lons)
    except Exception as e:
        print(f"terrain: open-elevation failed ({e}), trying open-meteo")
        return _fetch_open_meteo(lats, lons)


def build_terrain(spec):
    """Elevation grid for a map-world spec; None when unavailable.

    Returns {"nx", "ny", "x0", "y0", "cell_m", "z": [[row-major m]], "z_min",
    "z_max"} in the world's local meter frame (x east, y south, origin at the
    area center) — the same frame as every polygon the frontend draws.
    """
    cache = DATA_DIR / f"terrain_{spec['cache_file']}"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    lat0, lon0 = spec["center"]
    r = spec["radius_m"] * MARGIN
    cell = 2.0 * r / (GRID_N - 1)
    m_per_deg_lon = 111320 * math.cos(math.radians(lat0))
    lats, lons = [], []
    for j in range(GRID_N):          # rows: y (south) from -r to +r
        y = -r + j * cell
        for i in range(GRID_N):      # cols: x (east) from -r to +r
            x = -r + i * cell
            lats.append(lat0 - y / 110540)
            lons.append(lon0 + x / m_per_deg_lon)
    try:
        elev = _fetch_elevations(lats, lons)
        if len(elev) != GRID_N * GRID_N:
            raise ValueError(f"expected {GRID_N * GRID_N} elevations, got {len(elev)}")
    except Exception as e:
        print(f"terrain: elevation fetch failed ({e}) — world stays flat")
        return None

    z = [[round(float(elev[j * GRID_N + i]), 1) for i in range(GRID_N)]
         for j in range(GRID_N)]
    terrain = {
        "nx": GRID_N, "ny": GRID_N,
        "x0": -r, "y0": -r, "cell_m": round(cell, 2),
        "z": z,
        "z_min": min(min(row) for row in z),
        "z_max": max(max(row) for row in z),
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(terrain), encoding="utf-8")
    return terrain
