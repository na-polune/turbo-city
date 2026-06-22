# City Energy Analysis — real-map isometric simulation

An isometric city scene built from **real OpenStreetMap data** (Cambridge UK, ~250 m
around Market Square) where **all simulation runs in a Python backend** and the browser
is render-only. Real building footprints, real streets; cars and people random-walk the
actual street network; clicking any entity fetches its analysis from the backend.

Energy model based on the **ISO 13790** single-zone 1C RC thermal method — per-building
thermal node, occupancy schedules from SIA 2044, envelope U-values, solar gain,
CO₂ emissions, and rooftop PV generation.

---

## Project structure

```
turbo-city/
├── input/                    # All run configuration (no world facts hard-coded)
│   ├── config.json           # world, seed, start_hour, tick_hz, sim_min_per_sec
│   ├── map.json              # Real-map spec: center lat/lon, radius, cache file, agent counts
│   └── grid.json             # Grid test scene: buildings, roads, lamps, signals, agent counts
├── backend/
│   ├── config.py             # Loads and validates input/ files
│   ├── osm_world.py          # Overpass API fetch → OSM → world (cached)
│   ├── grid_world.py         # Hand-made grid world from input/grid.json
│   ├── simulation.py         # Sim core: clock, 1C RC thermal, occupancy, energy history
│   ├── energy.py             # CEA-inspired energy model (HVAC, electrical, lighting, PV, CO₂)
│   ├── constants.py          # Occupancy schedules, defaults, agent flavour data
│   ├── weather.py            # Open-Meteo API weather (real temperature + state machine)
│   └── main.py               # FastAPI app: tick loop + JSON API + static serving
└── frontend/
    ├── index.html            # Single HTML page — no build step required
    ├── css/
    │   └── main.css          # All styles (extracted from index.html for reuse)
    └── js/                   # Native ES modules — browser loads directly, no npm/bundler
        ├── app.js            # Entry point: imports all modules, runs boot sequence
        ├── config.js         # Shared constants (HW, HH, PALETTES, TYPE_LABEL, …)
        ├── math.js           # Pure functions (lerp, clamp, isoX/Y, shade, euiColor, …)
        ├── state.js          # Shared mutable appState + frameState() interpolation
        ├── camera.js         # cam object, viewport, resize, fitCamera, screenToWorld, zoomAt
        ├── api.js            # fetchWorld, pollState, sendEdit, sendSpeed, sendSeek
        ├── world-prep.js     # prepareWorld(), isoPath(), ground layers (Path2D)
        ├── render.js         # requestAnimationFrame render loop + all draw functions
        ├── input.js          # Pointer events, pan/zoom, road/building drag, hit test, click
        └── ui/
            ├── hud.js        # updateHUD(s) — clock, stats, backend badge, time slider sync
            ├── toolbar.js    # setTool(), building type selector, EUI overlay toggle
            ├── popup.js      # openDetail(), closePopup(), refreshDetail(), renderChart()
            ├── time-controls.js  # Play/pause, speed buttons, time slider drag
            └── toast.js      # flashToast(msg) — dismissable hint messages
```

---

## Run

```bash
python -m venv venv && venv\Scripts\activate && python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Then open **http://localhost:8000** — drag to pan, scroll to zoom.

> **No build step.** The frontend is plain HTML + CSS + native ES modules.
> The browser resolves all `import` statements directly; nothing needs to be compiled or bundled.

The world is chosen entirely by `input/config.json`; with `--reload`, editing any
`input/*.json` restarts the server automatically.

---

## Building types

Six types supported, each with its own CEA-sourced occupancy schedule, envelope
U-values, appliance/lighting power density, and HVAC setpoints:

| Type | Icon | Key characteristics |
|---|---|---|
| `res` | 🏠 | Residential — evening peak occupancy, moderate loads |
| `office` | 🏢 | Office — business hours, high appliance density |
| `shop` | 🛍 | Shop — retail hours, high lighting load |
| `hospital` | 🏥 | Hospital — 24/7 baseline occupancy (0.43), dual peaks at 09:00 and 14:00 |
| `school` | 🏫 | School — empty at night, full day 09–15 h |
| `industrial` | 🏭 | Industrial — shift pattern, highest appliance load (26.5 W/m²) |

---

## Energy model

Each building runs a **1C RC thermal node** (ISO 13790 / SIA 2044 single-zone model):

```
C · dT/dt = Q_solar + Q_internal − UA · (T_in − T_out)
```

- **UA** — envelope conductance from wall/window/roof/slab U-values and per-type window-to-wall ratio
- **Q_solar** — window solar gain weighted by façade orientation factor (per-wall-edge normal angles)
- **HVAC** — proportional to UA × temperature deviation from setpoint, divided by COP
- **Lighting** — reduced by daylight factor (peaks at noon, zero outside 06–18 h)
- **CO₂** — grid electricity × 0.233 kg/kWh (UK National Grid 2024 average)
- **PV** — roof area × 0.40 usable fraction × 18% panel efficiency × cloud-adjusted irradiance
- **Real outdoor temperature** — fetched from Open-Meteo API when running in map mode; synthetic daily profile used as fallback

---

## HUD stats

| Stat | Description |
|---|---|
| Buildings | Total building count |
| Vehicles | Cars currently in the scene |
| People | Pedestrians currently in the scene |
| Grid load | Sum of all building loads (kW or MW) |
| CO₂ | Total emissions from grid electricity (kg/h or t/h) |
| Solar PV | Total rooftop generation across all buildings (kW or MW) |

**EUI heat-map** (🌡 EUI button): toggle colour-coded rooftops — green = energy-efficient, red = high EUI. Gold glow on rooftop = building is generating significant solar PV.

---

## Minimal working example A — grid test scene (offline)

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

`input/grid.json`:

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

Run `uvicorn backend.main:app --reload` — one building, one road, one car, one walker, one lamp.

Coordinates are meters (`x` east, `y` south); shared road endpoints merge into one graph node,
so roads connect. Building `type` must be one of: `res`, `office`, `shop`, `hospital`, `school`, `industrial`.

---

## Minimal working example B — real Cambridge map (needs internet once)

Set `"world": "map"` in `input/config.json`. The first start downloads the OSM area once
via the Overpass API and caches it to `backend/data/<cache_file>`; after that it runs offline.

`input/map.json`:

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

---

## API

| Route | Returns |
|---|---|
| `GET /api/world` | Static layout: building polygons, roads, lamps, parks; includes `world_rev` |
| `GET /api/state` | Dynamic snapshot: clock, positions, total load/CO₂/PV, EUI per building, `world_rev` |
| `POST /api/edit` | Apply an edit command (see below); bumps `world_rev` |
| `GET /api/building/{id}` | 24 h energy history + current kW, CO₂, PV, indoor temp, occupancy |
| `GET /api/car/{id}` | Speed history (last 60 s) + distance |
| `GET /api/person/{id}` | Steps/hour history (24 h) + distance |
| `POST /api/scenario` | Before/after retrofit comparison (see below); stateless, does not touch the live sim |
| `GET /api/export/buildings.csv` | Current per-building EUI / CO₂ / PV snapshot as a downloadable CSV |
| `POST /api/export/scenario.csv` | Per-building before/after/delta retrofit comparison as a downloadable CSV |

---

## Editing

Every accepted edit bumps `world_rev`; the frontend refetches `/api/world` when it sees
the revision change. Edits are in-memory (restart reloads `input/`).

| Op | Args | Description |
|---|---|---|
| `set_floors` | `id, floors` | Change building height; energy model updates live |
| `spawn_car` | `x?, y?` | Arm **+ Car**, click map; spawns on nearest road node |
| `spawn_person` | `x?, y?` | Arm **+ Person**, click map |
| `remove_car` / `remove_person` | `id` | Click entity → **Remove** in popup |
| `add_road` | `points, class?, name?` | Arm **+ Road**, drag on map (10 m snap grid) |
| `add_building` | `polygon, type?, floors?, name?` | Arm **+ Bldg**, pick type, drag footprint |
| `remove_building` | `id` | **Doze** click or popup **Remove** |
| `remove_road` | `id` | Arm **Doze**, hover to preview, click to bulldoze |
| `set_speed` | `sim_min_per_sec` | Speed buttons (1× / 10× / 60× / 360×) |
| `seek_time` | `clock_min` | Time slider drag — pauses, seeks, then resumes |

---

## Scenario comparison — retrofit before vs. after

The **📊 Retrofit Scenario** panel (in the HUD) compares the whole city *before* and
*after* a retrofit, side by side. Because the energy model in `backend/energy.py` is
pure and parameterised (`Params` / `base_params(btype)`), this needs **no second live
simulation**: each building's 24 h day is replayed once under baseline parameters and
once under the retrofitted parameters, then the daily totals are diffed.

A scenario is a set of **city-wide measures** — multipliers on the energy parameters:

| Measure | Param scaled | Improving direction |
|---|---|---|
| `u_wall`, `u_roof`, `u_win` | wall / roof / window U-value | factor `< 1` (better insulation) |
| `g_win`, `win_wall` | glazing solar gain, window-to-wall ratio | factor `< 1` |
| `lpd` | lighting power density (LED) | factor `< 1` |
| `e_density` | appliance power density | factor `< 1` |
| `cop` | heating **and** cooling COP | factor `> 1` (efficient heat pump) |
| `pv_fraction` | usable roof fraction for PV | factor `> 1` (more panels) |
| `t_heat_delta`, `t_cool_delta` | setpoint setback [°C] | added to the setpoint |

A scenario can be **targeted** at a subset of buildings (`target`), and priced against
an electricity `tariff` for a simple payback:

```bash
curl -X POST localhost:8000/api/scenario -H 'Content-Type: application/json' \
  -d '{"measures": {"u_wall": 0.5, "u_win": 0.5, "lpd": 0.45, "cop": 1.6, "pv_fraction": 2.5},
       "target": {"types": ["res"]}, "tariff": 0.28}'
```

`target` is `{"types": [...]}`, `{"ids": [...]}`, or omitted (whole city). The headline
`baseline` / `retrofit` / `delta` totals cover **the selected set** (so targeting "all
residential" isn't diluted by untouched buildings), alongside:

- `profile_kw` — the 24 h city load curve for each case (drives the overlay chart)
- `cost` — indicative `capex`, `annual_savings`, `payback_years`, and `annual_co2_t_saved`
  (capex from per-measure £/m² figures in `scenario.MEASURE_COST`; **edit for a real cost book**)
- `buildings` — per-building rows with an `in_scope` flag and `delta_pct` (drives the map overlay and CSV)

The comparison runs on a **deterministic design day** (synthetic outdoor-temperature
profile, unit weather multipliers) so it is reproducible and reflects only the retrofit —
the live simulation keeps running untouched.

In the **📊 Retrofit Scenario** panel you can pick the target, drag measure sliders (or use
the Light / Deep presets), watch the headline EUI and per-day table update, see the baseline
vs. retrofit load curves overlaid, read the capex / payback, toggle **Show savings on map**
(rooftops recoloured green→red by each building's % energy cut), and export the per-building
comparison as CSV.

---

## Adding a new UI panel

Every future panel follows the same four-step pattern:

1. Create `frontend/js/ui/<panel>.js` — import `appState` from `../state.js`, export `setup<Panel>()`
2. Add the HTML stub (`<div id="panel" class="panel">`) to `index.html`
3. Add the panel's CSS to `frontend/css/main.css`
4. Add two lines to `frontend/js/app.js`:
   ```js
   import { setupPanel } from './ui/<panel>.js';
   setupPanel();
   ```

No other file needs to change.

---

## Current simplifications

- Traffic signals are rendered with cycling lights but cars do not stop at them.
- Agents random-walk (no destination routing).
- Edits are in-memory; restart reloads `input/` and discards runtime changes.
- PV self-consumption and battery storage not yet modelled.
