"""Run configuration loaded from the input/ folder (no world settings in code).

input/config.json — selects the world and run settings:
    { "world": "map" | "grid", "seed": <int>, "start_hour": <0-23>,
      "tick_hz": <int>, "sim_min_per_sec": <float>,
      "locale": { "co2_grid_kg_kwh": <kg/kWh>, "currency": "£",
                  "tariff_per_kwh": <price/kWh>,
                  "measure_cost_per_m2": { "<measure>": <cost/m²>, ... } } }
    The optional "locale" block localizes the economics/emissions of the model
    (grid carbon intensity, electricity price, retrofit cost book) without
    touching Python. Every key is optional; omitted keys fall back to the
    UK-flavored defaults in backend/energy.py and backend/scenario.py.
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


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_locale():
    """Validated "locale" block from input/config.json; {} when absent.

    Shape-checks only — which measure-cost keys exist is scenario knowledge, so
    backend/scenario.py validates them against its cost book. Tolerates a
    missing config.json entirely (returns {}), so pure model modules stay
    importable outside a configured run (tests, library use).
    """
    path = INPUT_DIR / "config.json"
    if not path.exists():
        return {}
    loc = json.loads(path.read_text(encoding="utf-8")).get("locale")
    if loc is None:
        return {}
    err = 'input/config.json: "locale"'
    if not isinstance(loc, dict):
        raise ValueError(f"{err} must be an object")
    known = {"co2_grid_kg_kwh", "currency", "tariff_per_kwh", "measure_cost_per_m2"}
    unknown = set(loc) - known
    if unknown:
        raise ValueError(f"{err} has unknown keys {sorted(unknown)}, expected {sorted(known)}")
    if "co2_grid_kg_kwh" in loc and not (_is_num(loc["co2_grid_kg_kwh"])
                                         and 0 <= loc["co2_grid_kg_kwh"] <= 5):
        raise ValueError(f"{err}.co2_grid_kg_kwh must be a number in 0..5 (kg CO₂/kWh)")
    if "currency" in loc and not (isinstance(loc["currency"], str)
                                  and 1 <= len(loc["currency"]) <= 4):
        raise ValueError(f"{err}.currency must be a string of 1..4 characters")
    if "tariff_per_kwh" in loc and not (_is_num(loc["tariff_per_kwh"])
                                        and 0 <= loc["tariff_per_kwh"] <= 100):
        raise ValueError(f"{err}.tariff_per_kwh must be a number in 0..100")
    costs = loc.get("measure_cost_per_m2")
    if costs is not None:
        if not (isinstance(costs, dict)
                and all(_is_num(v) and v >= 0 for v in costs.values())):
            raise ValueError(f"{err}.measure_cost_per_m2 must map measure names "
                             "to non-negative numbers")
    return loc
