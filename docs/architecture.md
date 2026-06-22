# Architecture & Data Flow

*One Python process owns the physics; the browser is a render-only client that polls 10 times a second.*

turbo-city is a small city-energy simulator with a deliberately lopsided split of
responsibility. **All state and all physics live in a single Python process.** The
browser never simulates anything — it fetches a static layout once, then polls a
JSON snapshot of moving state at 10 Hz and draws it. Every user action (add a car,
bulldoze a building, jump to a time of day) is a POST that the server applies to its
own authoritative state.

This document explains that server-authoritative design, lists the JSON API
surface, and traces the two loops that make the thing tick: the server's
simulation loop and the browser's poll/render/edit cycle.

See also: [Energy Model](energy-model.md) · [Simulation Core](simulation.md) · [Retrofit Scenarios](retrofit-scenarios.md)

---

## The big picture

```mermaid
flowchart LR
  subgraph Browser["Browser — render only"]
    R["render loop<br/>(requestAnimationFrame)"]
    P["pollState()<br/>every 100 ms"]
    S["appState<br/>world / cur / prev"]
    E["user edits<br/>(toolbar, sliders)"]
  end
  subgraph Server["Python — authoritative"]
    L["asyncio tick loop<br/>10 Hz"]
    SIM["Simulation<br/>(in-memory state)"]
    API["FastAPI routes"]
  end
  L -->|sim.tick(dt)| SIM
  P -->|GET /api/state| API
  API -->|JSON snapshot| S
  S --> R
  E -->|POST /api/edit| API
  API -->|apply_edit| SIM
  API -.->|GET /api/world<br/>on world_rev change| S
```

Two facts define the whole architecture:

1. **The server is authoritative.** `backend/simulation.py` holds the only copy of
   the world — buildings, cars, people, roads, the clock, the weather. The browser
   has no physics; it cannot predict, only display.
2. **The browser is a thin renderer.** `frontend/js/` is unbundled native ES modules
   served as static files. It fetches, interpolates, and paints. State changes go
   back to the server and return on the next poll.

---

## Server side: the asyncio tick loop

The app is a FastAPI server (`backend/main.py`). At startup, a `lifespan`
context manager spawns one long-lived background task, `run_simulation()`:

```python
async def run_simulation():
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        await asyncio.sleep(sim.tick_interval)   # ~0.1 s at TICK_HZ = 10
        now = loop.time()
        sim.tick(min(now - last, 1.0))           # cap dt if the loop stalls
        last = now
```

The loop sleeps `tick_interval = 1 / tick_hz` seconds (default **10 Hz**, from
`input/config.json` → `TICK_HZ` in `backend/constants.py`), then advances the
simulation by the real elapsed wall-clock time `dt`. The `min(..., 1.0)` clamp
prevents a single large jump if the event loop ever stalls (e.g. a slow Overpass
fetch on another request).

`Simulation.tick(dt)` (`backend/simulation.py`) does the per-step work:

- Advance the sim clock: `clock_min += dt * sim_min_per_sec` (default 1 real
  second = 1 sim minute, so a full day plays in 24 real minutes).
- Step the weather, then move every car and person along the street graph.
- Step each building's thermal RC node and recompute its load (see
  [Energy Model](energy-model.md)).
- On a `SAMPLE_MIN` (10 sim-minute) boundary, push a sample into every building's
  load history ring and rotate each person's pedometer bucket.
- Every `CAR_SPD_DT` (0.5 real seconds), sample each car's speed into its ring
  buffer.

Because both the tick loop and every HTTP handler run on the **same asyncio event
loop** and never `await` mid-mutation, a tick can never interleave with an edit.
That is the project's entire concurrency model — no locks, no threads for the
simulation itself. (The one exception: `/api/load_city` rebuilds the world in a
thread-pool executor so the blocking OSM fetch doesn't freeze the loop.)

### Snapshots: `world()` vs `state()`

The frontend reads the world through two snapshot methods with very different
cadences:

| Method | Endpoint | Contains | How often the browser fetches it |
|---|---|---|---|
| `world()` | `GET /api/world` | **Static layout**: buildings (id, name, type, floors, polygon, center), roads, parks, water, lamps, signals, `world_rev` | Once at startup, then only when `world_rev` changes |
| `state()` | `GET /api/state` | **Moving state**: `clock_min`, totals (load, CO₂, PV), weather, per-car position/heading/speed, per-person position, per-building EUI/PV, `world_rev` | 10× per second (every 100 ms) |

The split is deliberate. The static layout is large and changes rarely, so it is
fetched once. The moving state is small and changes constantly, so it is polled
hot. Notably, **the street graphs (`car_graph`, `ped_graph`, adjacency) never
leave the server** — `world()` ships only the renderable geometry, while pathing
stays inside `Simulation`.

### `world_rev`: how static layout stays fresh

`Simulation` keeps a counter, `world_rev`, that starts at 0 and is bumped on every
successful edit (inside `apply_edit`). Both snapshots include the current value.

The browser stores the `world_rev` it last fetched `/api/world` for. On every state
poll it compares:

```js
if (appState.world && s.world_rev !== appState.world.world_rev) refreshWorld();
```

So the moment any client mutates the world, the *next* state poll for *every*
client carries a higher `world_rev`, which triggers a single `/api/world`
re-fetch. This is the only mechanism keeping the static layout in sync — there are
no push notifications or websockets. The flow is cheap because edits are rare
relative to the 10 Hz state poll.

### Edits: `apply_edit`

All mutations funnel through one method, `Simulation.apply_edit(op)`:

```python
def apply_edit(self, op):
    handler = self._EDIT_OPS.get(op.get("op"))
    if handler is None:
        raise ValueError(...)        # -> HTTP 400
    handler(self, op)
    self.world_rev += 1
    return {"ok": True, "world_rev": self.world_rev}
```

It dispatches on the `"op"` string through a table, `_EDIT_OPS`, runs the handler,
then bumps `world_rev`. Handlers validate input (raising `ValueError`, which
`/api/edit` turns into a `400`) and mutate **both** the live objects *and*
`world_data` so the next `world()` snapshot stays consistent. The supported ops:

| `op` | Effect | Key validation |
|---|---|---|
| `set_floors` | Change a building's floor count | integer in `1..MAX_FLOORS` (20) |
| `spawn_car` | Add a car (optional `{x, y}` spawn point) | `MAX_CARS` (50); needs a drivable road |
| `spawn_person` | Add a pedestrian | `MAX_PEOPLE` (100); needs a walkable road |
| `remove_car` / `remove_person` | Delete an agent by id | id must exist |
| `add_road` | Lay a polyline road of a given class | 2–100 points, known class, non-zero length |
| `remove_road` | Delete a road; rebuild graphs; re-seat agents | can't strand existing agents |
| `add_building` | Add a polygon footprint | 3–30 points, ≥ `MIN_BUILDING_M2`, no building/road overlap |
| `remove_building` | Delete a building by id | id must exist |
| `set_speed` | Set `sim_min_per_sec` (time warp) | non-negative number |
| `seek_time` | Jump the clock; re-prefill building histories | number of minutes since midnight |

Because edits run on the shared event loop, ids stay unique across removals
(`_next_*_id` counters only increment), and `add_road` / `remove_road` rebuild the
street graphs and re-home every walker onto the new geometry before returning.

---

## The JSON API surface

Everything the frontend touches is plain JSON over HTTP (`backend/main.py`). The
frontend (`frontend/js/api.js`) is itself served as static files from `/`.

| Method & path | Purpose | Body / params | Returns |
|---|---|---|---|
| `GET /api/world` | Static renderable layout + `world_rev` | — | `sim.world()` |
| `GET /api/state` | Hot moving-state snapshot | — | `sim.state()` |
| `POST /api/edit` | Apply one edit op (bumps `world_rev`) | `{ "op": ..., ... }` | `{ ok, world_rev }` or 400 |
| `GET /api/building/{id}` | Per-building detail + 24 h load history | path id | detail or 404 |
| `GET /api/car/{id}` | Per-car detail + speed history | path id | detail or 404 |
| `GET /api/person/{id}` | Per-person detail + step history | path id | detail or 404 |
| `GET /api/export/buildings.csv` | Current per-building EUI/CO₂/PV as CSV | — | `text/csv` download |
| `POST /api/scenario` | Before/after retrofit recompute (stateless) | `{ measures, target?, tariff? }` | comparison JSON or 400 |
| `POST /api/export/scenario.csv` | Per-building retrofit comparison as CSV | `{ measures, target?, tariff? }` | `text/csv` download |
| `POST /api/load_city` | Rewrite `input/map.json`, rebuild the world for any lat/lon | `{ lat, lon, radius_m?, name? }` | `{ ok, name, world_rev }` |
| `GET /` (+ static) | The unbundled frontend (`StaticFiles`, `html=True`) | — | HTML / JS / CSS |

A few endpoints are notably *read-only against the live sim*: `/api/scenario` and
`/api/export/scenario.csv` run a deterministic design-day recompute over
`sim.buildings` **without touching or pausing** the running simulation (see
[Retrofit Scenarios](retrofit-scenarios.md)). The CSV exporters serialize a current
snapshot and stream it back as an attachment (`utf-8-sig` BOM so Excel reads
non-ASCII names correctly).

---

## Browser side: poll, interpolate, render

The frontend has **no build step**. `index.html` loads one entry module —
`<script type="module" src="js/app.js">` — and the browser resolves the
`import` graph natively at runtime. `app.js` wires up input, the toolbar, popups,
time controls, the city loader, export and scenario panels, then:

```js
fetchWorld().then(() => { fitCamera(); pollState(); startRenderLoop(); });
```

### The poll loop

`pollState()` (`frontend/js/api.js`) is a self-rescheduling loop, not a timer
interval:

```js
export async function pollState() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    s.recvT = performance.now();
    appState.prev = appState.cur || s;     // keep last two snapshots
    appState.cur = s;
    /* build euiMap; mark backend live; refetch world if world_rev changed */
  } catch {
    setBackend(false);                     // show "backend unreachable"
  } finally {
    setTimeout(pollState, POLL_MS);        // POLL_MS = 100  ->  ~10 Hz
  }
}
```

It always reschedules in `finally`, so a transient network error just flips the
"backend unreachable" badge and the loop keeps trying. `POLL_MS = 100`
(`frontend/js/config.js`) gives the 10 Hz cadence — matching the server tick rate.

### Interpolation between snapshots

The render loop runs on `requestAnimationFrame` (typically 60 fps), far faster than
the 10 Hz poll. To avoid choppy motion, `frameState()` (`frontend/js/state.js`)
keeps the last two snapshots (`prev`, `cur`) and **linearly interpolates** agent
positions by wall-clock time between them:

$$
t = \mathrm{clamp}\!\left(\frac{\text{now} - \text{cur.recvT}}{\max(1,\ \text{cur.recvT} - \text{prev.recvT})},\ 0,\ 1.5\right)
$$

$$
x = x_{\text{prev}} + (x_{\text{cur}} - x_{\text{prev}})\, t
$$

Each car/person is matched by id across the two frames; positions are lerped, while
scalar totals (load, CO₂, PV, weather) are taken straight from `cur`. The `1.5`
clamp lets motion extrapolate slightly if a poll is late, then holds. The browser
is still purely a renderer here — interpolation is cosmetic smoothing, not
simulation.

### The edit cycle

User actions call `sendEdit(op)` (or the convenience `sendSpeed` / `sendSeek`),
which POSTs to `/api/edit`. On a rejection the server's 400 detail is surfaced as a
toast; on success nothing special happens client-side — the edit bumped
`world_rev`, so the next poll detects the change and refetches `/api/world`. The
browser never optimistically mutates its own copy of the world.

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant B as Browser (api.js)
    participant A as FastAPI (main.py)
    participant S as Simulation (state)
    par Server tick loop (10 Hz)
        loop every tick_interval
            A->>S: sim.tick(dt)
            Note over S: move agents, step thermal,<br/>sample history
        end
    and Browser poll loop (10 Hz)
        loop every POLL_MS (100 ms)
            B->>A: GET /api/state
            A->>S: sim.state()
            S-->>B: snapshot {cars, people, totals, world_rev}
            Note over B: store prev/cur,<br/>interpolate, render @ rAF
            alt world_rev changed
                B->>A: GET /api/world
                A-->>B: static layout
            end
        end
    end
    U->>B: add car / set floors / seek
    B->>A: POST /api/edit {op}
    A->>S: apply_edit(op); world_rev++
    S-->>B: {ok, world_rev}
    Note over B: next poll sees new world_rev → refetch /api/world
```

### No-cache revalidation middleware

Because the frontend is unbundled with **no version hashing**, a stale cached
module is a real hazard: an old `.js` that's missing a newly-added export silently
breaks `import` resolution for the whole app. `backend/main.py` guards against this
with a one-line middleware:

```python
@app.middleware("http")
async def revalidate_static(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache"
    return response
```

`no-cache` does **not** mean "don't cache" — it means "cache, but revalidate with
the server every load." The browser keeps the file but sends a conditional request;
unchanged files come back as a cheap `304 Not Modified`. The result: no build step,
no cache-busting query strings, and no risk of a half-stale module graph.

---

## Single-process, in-memory state — and its tradeoffs

There is exactly one `Simulation` instance, `sim`, held as a module global in
`backend/main.py`. All state is in Python memory. This is the model's defining
simplification, and it cuts both ways.

**What it buys you**

- **Trivial concurrency.** Tick and edits share one event loop and never yield
  mid-mutation, so there are no locks, no races, and no transaction layer.
- **Zero infrastructure.** No database, no cache, no message bus. `python -m
  uvicorn` and you have a running city.
- **One source of truth.** Every client sees the same authoritative state on the
  next poll; `world_rev` keeps static layout coherent across browsers.

**What it costs you**

- **No persistence.** State lives only in RAM. Restart the server and the world
  resets to the configured start. Edits, spawned agents, and the clock are all
  ephemeral — the only durable artifacts are the input specs and exported CSVs.
- **No horizontal scaling.** A second process would be a second, independent
  world. Multiple browsers can connect, but they share *one* simulation; there is
  no per-session or per-user isolation. One person's bulldozer affects everyone.
- **Global swap on city change.** `/api/load_city` rebuilds and replaces the
  global `sim` wholesale (`global sim; sim = new_sim`). Any client mid-interaction
  is silently moved to the new world on its next poll.
- **Polling overhead.** Every client re-fetches the full moving-state snapshot 10×
  a second even when nothing it cares about changed. Fine for one machine and a
  few hundred agents (the spawn limits cap cars at 50, people at 100, buildings at
  500); it would not scale to many concurrent users or huge worlds.

For its goal — a single-user, single-machine teaching and exploration tool where
the Python energy model is the star — this is the right amount of architecture. The
server owns the truth, the browser draws it, and a four-character `world_rev`
counter keeps the two in sync.

## Assumptions & limitations

- **Single authoritative process; no multi-tenancy.** All connected browsers share
  one mutable world. There is no concept of a session, user, or private sandbox.
- **In-memory only; no durability.** A restart loses all runtime state. There is no
  save/load of a running world (only `input/*.json` specs and CSV exports).
- **Polling, not push.** Updates propagate at the 100 ms poll cadence; there is no
  websocket or server-sent-events channel. Worst-case latency for seeing another
  client's edit is one poll interval plus a `/api/world` round trip.
- **Client interpolation is cosmetic.** `frameState()` smooths motion but does not
  predict physics; if the backend is unreachable, agents simply stop advancing.
- **No build/bundling.** The frontend relies on native ES module resolution and the
  `no-cache` middleware. This keeps the toolchain at zero but means every module is
  a separate request and there is no minification or tree-shaking.
- **`world_rev` is a monotonic counter, not a hash.** It detects *that* the layout
  changed, not *what* changed — so any edit triggers a full `/api/world` re-fetch,
  not a delta.
