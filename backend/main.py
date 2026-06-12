"""FastAPI app: simulation tick loop + JSON API + static frontend."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .simulation import Simulation

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


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
