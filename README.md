# City Energy Analysis — real-map isometric simulation

An isometric city scene built from **real OpenStreetMap data** (Cambridge UK, ~250 m
around Market Square) where **all simulation runs in a Python backend** and the browser
is render-only. Real building footprints, real streets; cars and people random-walk the
actual street network; clicking any entity fetches its analysis from the backend.

- `backend/osm_world.py` — Overpass API fetch (cached in `backend/data/`) and
  OSM → world conversion: building polygons (type/floors from tags), road polylines,
  street graphs for cars and pedestrians, street lamps, parks/water.
- `backend/simulation.py` — simulation core: sim clock (1 s real = 1 min sim), per-building
  energy model (occupancy-curve based, 24 h history), graph random-walk cars and people.
- `backend/main.py` — FastAPI app: background tick loop (10 Hz) + JSON API + static serving.
- `frontend/` — canvas renderer: extruded footprint prisms, pan/zoom camera, 10 Hz state
  polling, click → `/api/building|car|person/{id}` → popup chart.
- `index.html` (repo root) — original personal-web demo, kept as the design reference.

## Run

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

First start downloads the OSM data once (needs internet) and caches it; after that it
runs offline. Open http://localhost:8000 — drag to pan, scroll to zoom. Click a building
(e.g. The Guildhall, Senate House), a car or a person: the popup data comes from a
backend API call (visible in the browser Network tab).

To change the area, edit `CENTER` / `RADIUS_M` in `backend/osm_world.py` and delete the
cache file in `backend/data/`.

## API

| Route | Returns |
|---|---|
| `GET /api/world` | static layout: building polygons, roads, lamps, parks (fetched once) |
| `GET /api/state` | dynamic snapshot: clock, car/person positions + headings, total load |
| `GET /api/building/{id}` | 24 h energy history + current kW + occupancy |
| `GET /api/car/{id}` | speed history (last 60 s) + distance |
| `GET /api/person/{id}` | steps/hour history (24 h) + distance |

## Current simplifications

- Traffic signals are rendered with cycling lights but cars don't stop at them yet.
- Agents random-walk (no destination routing); energy model is illustrative, not calibrated.
