"""Run configuration loaded from the input/ folder (no world settings in code).

input/config.json — selects the world and run settings:
    { "world": "map" | "grid", "seed": <int>, "start_hour": <0-23>,
      "tick_hz": <int>, "sim_min_per_sec": <float> }
input/map.json    — real-map world spec: OSM area (name, center, radius_m,
    cache_file), agent counts (n_cars, n_people) and speeds
    (car_speed_mps, person_speed_mps as [min, max])
input/grid.json   — grid test world spec: buildings, roads, lamps, signals,
    agent counts and speeds (same fields as map.json minus the OSM area)

Edit the files and restart the server to apply.
"""
import json
from pathlib import Path

INPUT_DIR = Path(__file__).resolve().parent.parent / "input"
WORLD_MODES = ("map", "grid")


def _read(name):
    path = INPUT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"missing input file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_config():
    cfg = _read("config.json")
    world = cfg.get("world")
    if world not in WORLD_MODES:
        raise ValueError(
            f'input/config.json: "world" must be one of {list(WORLD_MODES)}, got {world!r}')
    return cfg


def load_world_spec(mode):
    """World spec for a mode: input/map.json or input/grid.json."""
    return _read(f"{mode}.json")
