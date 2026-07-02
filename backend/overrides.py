"""Per-building parameter overrides — the calibration hook for real stock data.

A CSV (default input/overrides.csv) refines individual buildings beyond their
type archetype: measured U-values, setpoints, system COP, vintage-specific
densities — any field of energy.Params — plus an optional measured annual
consumption for model-vs-measured comparison in the annual engine.

Format: one header row, one row per building. `id` is required and must match
the building ids in buildings.csv / the /api/world payload (stable for a given
world + seed). Every other column is optional and may be left blank per row:

    id,u_wall,u_win,ach,t_heat,measured_kwh_yr
    12,1.4,4.8,,19.5,48200
    17,,,0.4,,

Blank cell = keep the type baseline for that field. Unknown columns are an
error (catches typos before they silently do nothing).
"""
import csv
import math
from dataclasses import fields, replace
from pathlib import Path

from . import energy

PARAM_FIELDS = tuple(f.name for f in fields(energy.Params))
MEASURED_COL = "measured_kwh_yr"


def load_overrides(path):
    """Parse an overrides CSV -> {building_id: {"params": {...}, "measured_kwh_yr": float|None}}."""
    path = Path(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = [c.strip() for c in (reader.fieldnames or [])]
        if "id" not in cols:
            raise ValueError(f"{path}: overrides CSV needs an 'id' column")
        unknown = set(cols) - {"id", MEASURED_COL} - set(PARAM_FIELDS)
        if unknown:
            raise ValueError(f"{path}: unknown columns {sorted(unknown)} — "
                             f"expected 'id', '{MEASURED_COL}', or Params fields "
                             f"{list(PARAM_FIELDS)}")
        out = {}
        for lineno, row in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if not row.get("id"):
                continue
            try:
                bid = int(row["id"])
            except ValueError:
                raise ValueError(f"{path}:{lineno}: id {row['id']!r} is not an integer")
            if bid in out:
                raise ValueError(f"{path}:{lineno}: duplicate id {bid}")
            params, measured = {}, None
            for col, raw in row.items():
                if col == "id" or not raw:
                    continue
                try:
                    val = float(raw)
                except ValueError:
                    raise ValueError(f"{path}:{lineno}: {col}={raw!r} is not a number")
                if not math.isfinite(val):
                    raise ValueError(f"{path}:{lineno}: {col} must be finite")
                if col == MEASURED_COL:
                    if val < 0:
                        raise ValueError(f"{path}:{lineno}: {MEASURED_COL} must be >= 0")
                    measured = val
                else:
                    params[col] = val
            out[bid] = {"params": params, "measured_kwh_yr": measured}
    return out


def params_for(b, overrides):
    """Baseline Params for a building: type archetype + any per-building overrides."""
    base = energy.base_params(b.type)
    o = overrides.get(b.id) if overrides else None
    return replace(base, **o["params"]) if o and o["params"] else base


def measured_for(b, overrides):
    """Measured annual kWh for a building, or None."""
    o = overrides.get(b.id) if overrides else None
    return o["measured_kwh_yr"] if o else None
