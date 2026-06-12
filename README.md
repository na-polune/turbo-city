# City Energy Analysis — real-map isometric simulation

An isometric city scene built from **real OpenStreetMap data** (Cambridge UK, ~250 m
around Market Square) where **all simulation runs in a Python backend** and the browser
is render-only. Real building footprints, real streets; cars and people random-walk the
actual street network; clicking any entity fetches its analysis from the backend.

- `input/` — all run inputs live here; no world facts or run settings are hard-coded:
  - `config.json` — which world to run (`"world": "map"` or `"grid"`), seed, start hour,
    tick rate, sim time scale.
  - `map.json` — real-map spec: area name, center lat/lon, radius, cache file, agent
    counts and speeds.
  - `grid.json` — grid test scene spec: buildings, roads, lamps, signals, agent counts
    and speeds (ships as the minimal test scene: 1 building, 1 road, 1 lamp, 1 car, 1 person).
- `backend/config.py` — loads and validates the `input/` files.
- `backend/osm_world.py` — Overpass API fetch (cached in `backend/data/`) and
  OSM → world conversion: building polygons (type/floors from tags), road polylines,
  street graphs for cars and pedestrians, street lamps, parks/water.
- `backend/grid_world.py` — builds the hand-made grid world from `input/grid.json`
  (same data shape as the OSM world, so simulation and renderer are unchanged).
- `backend/simulation.py` — simulation core: sim clock (time scale, tick rate and agent
  speeds all from `input/`), per-building energy model (occupancy-curve based, 24 h
  history), graph random-walk cars and people.
- `backend/main.py` — FastAPI app: background tick loop (rate from `input/config.json`)
  + JSON API + static serving.
- `frontend/` — render-only canvas: extruded footprint prisms, pan/zoom camera, polls
  `/api/state`, draws whatever `/api/world` returns; click → `/api/building|car|person/{id}`
  → popup chart. No world data is baked into the frontend.
- `index.html` (repo root) — original personal-web demo, kept as the design reference.

## Run

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Then open http://localhost:8000 — drag to pan, scroll to zoom. Click a building, a car
or a person: the popup data comes from a backend API call (visible in the Network tab).
The world is chosen entirely by `input/config.json`; with `--reload`, editing any
`input/*.json` restarts the server automatically.

### Minimal working example A — grid test scene (offline, no internet)

This is the smallest world: one building, one road, one lamp, one car, one person.
It needs no network — the geometry comes straight from `input/grid.json`.

`input/config.json`:

```json
{
  "world": "grid",
  "seed": 20260612,
  "start_hour": 9,
  "tick_hz": 10,
  "sim_min_per_sec": 1.0
}
```

`input/grid.json` (the whole scene — edit coordinates/counts/speeds to taste):

```json
{
  "name": "Grid City · Test Block",
  "radius_m": 100,
  "n_cars": 1,
  "n_people": 1,
  "car_speed_mps": [6.0, 9.0],
  "person_speed_mps": [1.1, 1.7],
  "buildings": [
    { "name": "Test Block A", "type": "office", "floors": 4,
      "polygon": [[-12, -38], [12, -38], [12, -14], [-12, -14]] }
  ],
  "roads": [
    { "name": "Main Street", "class": "residential",
      "points": [[-80, 0], [-40, 0], [0, 0], [40, 0], [80, 0]] }
  ],
  "lamps": [[0, 5.0]],
  "signals": []
}
```

Run `uvicorn backend.main:app --reload` and open the page — you should see exactly one
building, one car driving the road, one walker and one lamp, with the HUD reading
Buildings 1 / Vehicles 1 / People 1.

Coordinates are meters (`x` east, `y` south); buildings need a polygon of ≥3 points,
roads a polyline of ≥2 points, and `class` must be one of the road classes in
`backend/osm_world.py` (`residential`, `primary`, `footway`, …). Points on different
roads that share the same coordinate are merged into one graph node, so roads connect.

### Minimal working example B — real Cambridge map (needs internet once)

Switch `"world"` to `"map"` in `input/config.json`; everything else about the area lives
in `input/map.json`:

```json
{
  "name": "Cambridge · Market Square",
  "center": [52.2055, 0.1187],
  "radius_m": 250,
  "cache_file": "cambridge_market_square.json",
  "n_cars": 8,
  "n_people": 15,
  "car_speed_mps": [6.0, 9.0],
  "person_speed_mps": [1.1, 1.7]
}
```

The first start downloads the OSM area once via the Overpass API and caches it to
`backend/data/<cache_file>`; after that it runs offline. Click The Guildhall, Senate
House, a car or a person to query the backend. To use a **different area**, change
`center` / `radius_m` and give `cache_file` a new name (or delete the old cache file).

## API

| Route | Returns |
|---|---|
| `GET /api/world` | static layout: building polygons, roads, lamps, parks; includes `world_rev` |
| `GET /api/state` | dynamic snapshot: clock, car/person positions + headings, total load, `world_rev` |
| `POST /api/edit` | apply an edit command, e.g. `{"op": "set_floors", "id": 0, "floors": 5}`; bumps `world_rev` |
| `GET /api/building/{id}` | 24 h energy history + current kW + occupancy |
| `GET /api/car/{id}` | speed history (last 60 s) + distance |
| `GET /api/person/{id}` | steps/hour history (24 h) + distance |

## Editing (work in progress, SimCity direction)

The world is editable at runtime through `POST /api/edit` commands; every accepted edit
bumps `world_rev`, and clients refetch `/api/world` when they see the revision change in
`/api/state`. Edits are in-memory for now (restart reloads `input/`).

Implemented ops:

- `set_floors` `{id, floors}` — click a building, use the − / + control in the popup;
  height, energy model and grid load update live.
- `spawn_car` / `spawn_person` `{x?, y?}` — arm **+ Car** / **+ Person** in the HUD, then
  click the map; the agent spawns on the nearest road node (omit x/y for random). Agent
  ids are stable across removals.
- `remove_car` / `remove_person` `{id}` — click a car or person, then **Remove** in the popup.
- `add_road` `{points, class?, name?}` — arm **+ Road**, then drag on the map; the segment
  snaps to a 10 m grid (drag consecutive segments from the same point to draw a polyline —
  shared endpoints merge into one graph node, so they connect). Street graphs rebuild and
  agents re-seat automatically.
- `remove_road` `{id}` — arm **Doze**, hover to see the target road, click to bulldoze.
  Removing the last drivable/walkable road is rejected while cars/people exist (the
  reason flashes in the toast).

Planned next: building placement, save/load, destination routing.

## Current simplifications

- Traffic signals are rendered with cycling lights but cars don't stop at them yet.
- Agents random-walk (no destination routing); energy model is illustrative, not calibrated.
