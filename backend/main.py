"""FastAPI app: simulation tick loop + JSON API + static frontend."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .simulation import Simulation

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
TICK_INTERVAL = 0.1   # 10 Hz

sim = Simulation()


async def run_simulation():
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        now = loop.time()
        sim.tick(min(now - last, 1.0))   # cap dt if the loop stalls
        last = now


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_simulation())
    yield
    task.cancel()


app = FastAPI(title="City Energy Analysis", lifespan=lifespan)


def check_id(entity_id: int, count: int):
    if not 0 <= entity_id < count:
        raise HTTPException(status_code=404, detail="Unknown entity id")


@app.get("/api/world")
async def world():
    return sim.world()


@app.get("/api/state")
async def state():
    return sim.state()


@app.get("/api/building/{building_id}")
async def building(building_id: int):
    check_id(building_id, len(sim.buildings))
    return sim.building_detail(building_id)


@app.get("/api/car/{car_id}")
async def car(car_id: int):
    check_id(car_id, len(sim.cars))
    return sim.car_detail(car_id)


@app.get("/api/person/{person_id}")
async def person(person_id: int):
    check_id(person_id, len(sim.people))
    return sim.person_detail(person_id)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
