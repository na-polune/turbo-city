"""Before/after retrofit scenario comparison — analytical "what-if" recompute.

A *scenario* is a set of city-wide *measures* (parameter multipliers / setpoint
deltas) applied to the energy model. For each building we replay a full 24 h day
under the baseline Params and again under the retrofitted Params, integrate the
load into daily energy, and diff the two. There is no second live simulation, no
agents and no live weather — the result is deterministic and reflects only the
retrofit, which is exactly what a "before vs. after" consultant deliverable needs.

Weather basis: the deterministic synthetic outdoor-temperature profile
(energy.outdoor_temp_c) with unit cloud/wind multipliers, so the comparison is
reproducible and independent of the live clock or fetched weather.
"""
import math
from dataclasses import replace

from . import energy
from .constants import SAMPLE_MIN, HISTORY_LEN

DT_H = SAMPLE_MIN / 60.0          # hours represented by one sample step
DAYS_PER_YEAR = 365.0

# City-wide multiplier measures: key -> (human label, Params field it scales).
# A factor < 1 improves loss/consumption fields (U-values, lighting, appliances);
# a factor > 1 improves capacity fields (COP, PV area). 1.0 is a no-op.
MULTIPLIER_MEASURES = {
    "u_wall":      ("Wall insulation",          "u_wall"),
    "u_roof":      ("Roof insulation",          "u_roof"),
    "u_win":       ("Glazing (window U-value)", "u_win"),
    "g_win":       ("Glazing solar control",    "g_win"),
    "win_wall":    ("Window-to-wall ratio",     "win_wall"),
    "lpd":         ("LED lighting",             "lpd"),
    "e_density":   ("Efficient appliances",     "e_density"),
    "pv_fraction": ("Rooftop PV area",          "pv_fraction"),
}
# "cop" is special — one factor scales both heating and cooling COP.
# Setpoint setback measures are °C deltas added to a setpoint (negative t_heat_delta
# lowers heating demand; positive t_cool_delta lowers cooling demand).
SETPOINT_MEASURES = {
    "t_heat_delta": "t_heat",
    "t_cool_delta": "t_cool",
}

MAX_FACTOR = 10.0
MAX_DELTA_C = 10.0

# Metrics summed across buildings into city totals (peak excluded: a sum of
# per-building peaks is not the coincident city peak — kept per-building only).
_TOTAL_METRICS = ("energy_kwh", "hvac_kwh", "elec_kwh", "light_kwh",
                  "co2_kg", "pv_kwh", "net_kwh")
_ROW_METRICS = ("energy_kwh", "co2_kg", "pv_kwh", "eui_kwh_m2_yr")


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_measures(measures):
    """Validate + normalise a raw measures dict; raise ValueError on bad input."""
    if not isinstance(measures, dict):
        raise ValueError("measures must be an object")
    out = {}
    for key, v in measures.items():
        if key in MULTIPLIER_MEASURES or key == "cop":
            if not (_is_num(v) and 0 < v <= MAX_FACTOR):
                raise ValueError(f"measure {key!r} must be a factor in (0, {MAX_FACTOR:g}]")
            out[key] = float(v)
        elif key in SETPOINT_MEASURES:
            if not (_is_num(v) and -MAX_DELTA_C <= v <= MAX_DELTA_C):
                raise ValueError(f"measure {key!r} must be a °C delta in "
                                 f"[-{MAX_DELTA_C:g}, {MAX_DELTA_C:g}]")
            out[key] = float(v)
        else:
            raise ValueError(f"unknown measure {key!r}")
    return out


def apply_measures(params, measures):
    """Return a new Params with the (already validated) measures applied.

    No-op measures (factor 1.0 / delta 0.0) still produce an identical Params,
    so passing an empty or all-default dict yields the baseline unchanged.
    """
    fields = {}
    for key, (_, field) in MULTIPLIER_MEASURES.items():
        if key in measures:
            fields[field] = getattr(params, field) * measures[key]
    if "cop" in measures:
        fields["cop_heat"] = params.cop_heat * measures["cop"]
        fields["cop_cool"] = params.cop_cool * measures["cop"]
    for key, field in SETPOINT_MEASURES.items():
        if key in measures:
            fields[field] = getattr(params, field) + measures[key]
    return replace(params, **fields) if fields else params


def evaluate_building(b, params):
    """Replay 24 h under `params`; return this building's daily energy summary.

    Two passes: pass 1 settles indoor temperature from the setpoint midpoint,
    pass 2 is the measured day. Baseline and retrofit get identical treatment,
    so the diff is apples-to-apples regardless of absolute thermal settling.
    """
    T_in = 0.5 * (params.t_heat + params.t_cool)
    t = {"energy_kwh": 0.0, "hvac_kwh": 0.0, "elec_kwh": 0.0,
         "light_kwh": 0.0, "co2_kg": 0.0, "pv_kwh": 0.0}
    peak_kw = 0.0
    for measured in (False, True):
        for i in range(HISTORY_LEN):
            m = i * SAMPLE_MIN
            h = (m % 1440) / 60.0
            T_out = energy.outdoor_temp_c(m)
            occ = b.occupancy(h)
            T_in = energy.step_T_in(
                T_in, T_out, b.area_m2, b.floors, b.type, occ, h, SAMPLE_MIN * 60,
                orientation_factor=b._ori_factor(h), params=params)
            if not measured:
                continue
            load, hv, el, li = energy.total_load_kw(
                T_in, b.area_m2, b.floors, b.type, occ, h, params=params)
            day_factor = max(0.0, math.sin(math.pi * (h - 6) / 12)) if 6 <= h <= 18 else 0.0
            pv = energy.pv_gen_kw(b.area_m2, day_factor, params.pv_fraction, params.pv_efficiency)
            t["energy_kwh"] += load * DT_H
            t["hvac_kwh"]   += hv * DT_H
            t["elec_kwh"]   += el * DT_H
            t["light_kwh"]  += li * DT_H
            t["co2_kg"]     += energy.co2_kg_h(load) * DT_H
            t["pv_kwh"]     += pv * DT_H
            peak_kw = max(peak_kw, load)
    t["net_kwh"] = t["energy_kwh"] - t["pv_kwh"]
    t["peak_kw"] = peak_kw
    t["eui_kwh_m2_yr"] = t["energy_kwh"] * DAYS_PER_YEAR / max(1.0, b.area_m2 * b.floors)
    return t


def _aggregate(rows):
    """Sum per-building metrics into city totals + floor-area-weighted EUI."""
    out = {k: 0.0 for k in _TOTAL_METRICS}
    floor_area = 0.0
    for b, r in rows:
        for k in _TOTAL_METRICS:
            out[k] += r[k]
        floor_area += max(1.0, b.area_m2 * b.floors)
    out["eui_kwh_m2_yr"] = out["energy_kwh"] * DAYS_PER_YEAR / max(1.0, floor_area)
    return out


def _diff(base, retro):
    """Per-metric absolute and % change (retrofit − baseline)."""
    return {k: {"abs": round(retro[k] - base[k], 1),
                "pct": round((retro[k] - base[k]) / base[k] * 100.0, 1) if base[k] else 0.0}
            for k in base}


def _building_row(b, base, retro):
    return {
        "id": b.id, "name": b.name, "type": b.type,
        "area_m2": b.area_m2, "floors": b.floors,
        "baseline": {k: round(base[k], 1) for k in _ROW_METRICS},
        "retrofit": {k: round(retro[k], 1) for k in _ROW_METRICS},
        "delta_pct": (round((retro["energy_kwh"] - base["energy_kwh"]) /
                            base["energy_kwh"] * 100.0, 1) if base["energy_kwh"] else 0.0),
    }


def compare(buildings, measures):
    """Baseline vs retrofit city comparison for the given measures.

    Stateless: reads building geometry / type / occupancy but never mutates the
    simulation. Returns city totals for both cases, their delta, and per-building
    rows (rows feed a future table / CSV export; the MVP UI shows city totals).
    """
    measures = validate_measures(measures)
    base_rows, retro_rows = [], []
    for b in buildings:
        bp = energy.base_params(b.type)
        rp = apply_measures(bp, measures)
        base_rows.append((b, evaluate_building(b, bp)))
        retro_rows.append((b, evaluate_building(b, rp)))

    base_tot = _aggregate(base_rows)
    retro_tot = _aggregate(retro_rows)
    return {
        "measures": measures,
        "n_buildings": len(buildings),
        "baseline": {k: round(v, 1) for k, v in base_tot.items()},
        "retrofit": {k: round(v, 1) for k, v in retro_tot.items()},
        "delta": _diff(base_tot, retro_tot),
        "buildings": [_building_row(b, base, retro)
                      for (b, base), (_, retro) in zip(base_rows, retro_rows)],
    }
