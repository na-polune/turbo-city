"""FastAPI app: simulation tick loop + JSON API + static frontend."""
import asyncio
import csv
import io
import json as _json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import heatmap, scenario
from .simulation import Simulation

INPUT_DIR = Path(__file__).resolve().parent.parent / "input"

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

sim = Simulation()    # world choice + settings come from input/config.json


async def run_simulation():
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        # Paused (sim_min_per_sec == 0): idle without advancing the world, so a
        # paused tab costs ~nothing instead of running physics 10x/second.
        if sim.sim_min_per_sec <= 0:
            await asyncio.sleep(0.2)
            last = loop.time()   # don't accumulate a huge dt while paused
            continue
        await asyncio.sleep(sim.tick_interval)   # tick rate from input/config.json
        now = loop.time()
        sim.tick(min(now - last, 1.0))   # cap dt if the loop stalls
        last = now


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_simulation())
    yield
    task.cancel()


app = FastAPI(title="City Energy Analysis", lifespan=lifespan)


@app.middleware("http")
async def revalidate_static(request, call_next):
    """Force the browser to revalidate static assets every load.

    The frontend is unbundled native ES modules with no version hashing, so a
    stale cached module (e.g. an old one missing a newly-added export) silently
    breaks `import` resolution for the whole app. `no-cache` keeps the cache but
    requires an ETag revalidation each load — cheap (304s) and skew-proof.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache"
    return response


def or_404(detail):
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown entity id")
    return detail


@app.get("/api/world")
async def world():
    return sim.world()


@app.get("/api/state")
async def state():
    return sim.state()


@app.post("/api/edit")
async def edit(op: dict):
    """Apply one edit command (see Simulation.apply_edit); bumps world_rev."""
    try:
        return sim.apply_edit(op)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/building/{building_id}")
async def building(building_id: int):
    return or_404(sim.building_detail(building_id))


@app.get("/api/car/{car_id}")
async def car(car_id: int):
    return or_404(sim.car_detail(car_id))


@app.get("/api/person/{person_id}")
async def person(person_id: int):
    return or_404(sim.person_detail(person_id))


@app.get("/api/export/buildings.csv")
async def export_buildings_csv():
    """Current per-building EUI / CO₂ / PV snapshot as a downloadable CSV."""
    rows = sim.building_table()
    cols = ["id", "name", "type", "floors", "area_m2", "load_kw", "hvac_kw",
            "elec_kw", "light_kw", "eui_w_m2", "co2_kg_h", "pv_kw", "t_in_c", "occupancy"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", sim.world_data["name"]).strip("-").lower() or "city"
    m = int(sim.clock_min % 1440)
    fname = f"eui_{slug}_{m // 60:02d}{m % 60:02d}.csv"
    # utf-8-sig prepends a BOM so Excel reads non-ASCII building names correctly
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/scenario")
async def scenario_compare(body: dict):
    """Before/after retrofit comparison (city-wide or targeted measures).

    Stateless analytical recompute over a deterministic design day — does not
    touch or pause the live simulation. Body: {"measures": {"u_wall": 0.5,
    "lpd": 0.5, "cop": 1.5, ...}, "target": {"types": ["res"]}, "tariff": 0.28}.
    See scenario.MULTIPLIER_MEASURES; target/tariff are optional.
    """
    try:
        return scenario.compare(sim.buildings, body.get("measures") or {},
                                body.get("target"), body.get("tariff"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/export/scenario.csv")
async def export_scenario_csv(body: dict):
    """Per-building before/after/delta retrofit comparison as a downloadable CSV."""
    try:
        result = scenario.compare(sim.buildings, body.get("measures") or {},
                                  body.get("target"), body.get("tariff"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cols = ["id", "name", "type", "floors", "area_m2", "in_scope",
            "baseline_energy_kwh_day", "retrofit_energy_kwh_day", "delta_pct",
            "baseline_co2_kg_day", "retrofit_co2_kg_day",
            "baseline_pv_kwh_day", "retrofit_pv_kwh_day",
            "baseline_eui_kwh_m2_yr", "retrofit_eui_kwh_m2_yr"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in result["buildings"]:
        b, a = r["baseline"], r["retrofit"]
        w.writerow([r["id"], r["name"], r["type"], r["floors"], r["area_m2"], r["in_scope"],
                    b["energy_kwh"], a["energy_kwh"], r["delta_pct"],
                    b["co2_kg"], a["co2_kg"], b["pv_kwh"], a["pv_kwh"],
                    b["eui_kwh_m2_yr"], a["eui_kwh_m2_yr"]])
    slug = re.sub(r"[^A-Za-z0-9]+", "-", sim.world_data["name"]).strip("-").lower() or "city"
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="retrofit_{slug}.csv"'})


@app.post("/api/heatmap")
async def heatmap_analysis():
    """Overheating heat-map: each building's peak free-floating indoor temperature
    over today's weather (no active cooling), with wind-driven natural ventilation.

    Stateless and triggered (never on the live clock). Runs off the event loop
    because it fetches the weather forecast and replays a design day per building.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, heatmap.compute, sim.buildings, sim.lat, sim.lon)


@app.post("/api/load_city")
async def load_city(body: dict):
    """Write new input/map.json and reinitialise the simulation for any lat/lon."""
    lat = body.get("lat")
    lon = body.get("lon")
    radius_m = body.get("radius_m", 250)
    name = body.get("name") or ""

    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if not (num(lat) and -90 <= lat <= 90):
        raise HTTPException(status_code=400, detail="lat must be a number in -90..90")
    if not (num(lon) and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="lon must be a number in -180..180")
    if not (num(radius_m) and 50 <= radius_m <= 2000):
        raise HTTPException(status_code=400, detail="radius_m must be a number in 50..2000")

    name = str(name)[:60].strip() or f"{lat:.4f}, {lon:.4f}"
    cache_file = f"city_{lat:.4f}_{lon:.4f}.json".replace("-", "m")

    spec = {
        "name": name,
        "center": [round(lat, 6), round(lon, 6)],
        "radius_m": int(radius_m),
        "cache_file": cache_file,
        "n_cars": 8,
        "n_people": 15,
        "car_speed_mps": [6.0, 9.0],
        "person_speed_mps": [1.1, 1.7],
    }
    (INPUT_DIR / "map.json").write_text(_json.dumps(spec, indent=2), encoding="utf-8")

    # Ensure config.json uses map mode
    cfg_path = INPUT_DIR / "config.json"
    cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("world") != "map":
        cfg["world"] = "map"
        cfg_path.write_text(_json.dumps(cfg, indent=2), encoding="utf-8")

    # Build the new simulation in a thread so the Overpass fetch doesn't block the event loop
    loop = asyncio.get_running_loop()
    try:
        new_sim = await loop.run_in_executor(None, Simulation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"World build failed: {e}")

    global sim
    sim = new_sim
    return {"ok": True, "name": name, "world_rev": sim.world_rev}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
