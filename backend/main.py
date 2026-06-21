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

from . import scenario
from .simulation import Simulation

INPUT_DIR = Path(__file__).resolve().parent.parent / "input"

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

sim = Simulation()    # world choice + settings come from input/config.json


async def run_simulation():
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
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
    """Before/after retrofit comparison (city-wide measure multipliers).

    Stateless analytical recompute over a deterministic design day — does not
    touch or pause the live simulation. Body: {"measures": {"u_wall": 0.5,
    "lpd": 0.5, "cop": 1.5, ...}}; see scenario.MULTIPLIER_MEASURES.
    """
    measures = body.get("measures") or {}
    try:
        return scenario.compare(sim.buildings, measures)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
