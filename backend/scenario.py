"""Before/after retrofit scenario comparison — analytical "what-if" recompute.

A *scenario* is a set of city-wide *measures* (parameter multipliers / setpoint
deltas) applied to the energy model, optionally restricted to a *target* subset
of buildings (by type or id). For each building we replay a full 24 h day under
the baseline Params and again under the retrofitted Params, integrate the load
into daily energy, and diff the two. There is no second live simulation, no
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

# Indicative retrofit capex, in £ per m² of the cost basis, at *full* application
# of the measure; scaled linearly by how aggressively the measure is set. These
# are early-stage planning figures only — replace with a local cost book as needed.
# basis: 'floor' = total floor area (area × floors); 'roof' = footprint area.
MEASURE_COST = {
    "u_wall":      (60.0,  "floor"),
    "u_roof":      (25.0,  "roof"),
    "u_win":       (80.0,  "floor"),
    "g_win":       (40.0,  "floor"),
    "lpd":         (12.0,  "floor"),
    "e_density":   (20.0,  "floor"),
    "cop":         (70.0,  "floor"),
    "pv_fraction": (250.0, "roof"),
}
DEFAULT_TARIFF = 0.28   # £/kWh, indicative UK retail electricity price

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


def validate_target(target):
    """Validate a target spec; return a normalised dict or None (= whole city)."""
    if target is None:
        return None
    if not isinstance(target, dict):
        raise ValueError("target must be an object or null")
    out = {}
    if target.get("types") is not None:
        types = target["types"]
        if not (isinstance(types, list) and types
                and all(t in energy.BUILDING_TYPES for t in types)):
            raise ValueError("target.types must be a non-empty list of building types")
        out["types"] = list(dict.fromkeys(types))
    if target.get("ids") is not None:
        ids = target["ids"]
        if not (isinstance(ids, list) and ids
                and all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
            raise ValueError("target.ids must be a non-empty list of building ids")
        out["ids"] = list(dict.fromkeys(ids))
    return out or None


def _in_scope(b, target):
    if target is None:
        return True
    return (("types" in target and b.type in target["types"]) or
            ("ids" in target and b.id in target["ids"]))


def apply_measures(params, measures):
    """Return a new Params with the (already validated) measures applied.

    An empty measures dict returns the same instance unchanged, so the caller can
    cheaply detect "no retrofit for this building" via identity.
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
    Also returns ``profile_kw`` — the mean total load in each of the 24 hours.
    """
    T_in = 0.5 * (params.t_heat + params.t_cool)
    t = {"energy_kwh": 0.0, "hvac_kwh": 0.0, "elec_kwh": 0.0,
         "light_kwh": 0.0, "co2_kg": 0.0, "pv_kwh": 0.0}
    hour_sum = [0.0] * 24
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
            hour_sum[int(h)] += load
            peak_kw = max(peak_kw, load)
    t["net_kwh"] = t["energy_kwh"] - t["pv_kwh"]
    t["peak_kw"] = peak_kw
    t["eui_kwh_m2_yr"] = t["energy_kwh"] * DAYS_PER_YEAR / max(1.0, b.area_m2 * b.floors)
    samples_per_hour = HISTORY_LEN / 24.0
    t["profile_kw"] = [s / samples_per_hour for s in hour_sum]
    return t


def _aggregate(rows):
    """Sum per-building metrics into city totals + floor-area-weighted EUI."""
    out = {k: 0.0 for k in _TOTAL_METRICS}
    floor_area = 0.0
    profile = [0.0] * 24
    for b, r in rows:
        for k in _TOTAL_METRICS:
            out[k] += r[k]
        for h in range(24):
            profile[h] += r["profile_kw"][h]
        floor_area += max(1.0, b.area_m2 * b.floors)
    out["eui_kwh_m2_yr"] = out["energy_kwh"] * DAYS_PER_YEAR / max(1.0, floor_area)
    return out, profile


def _diff(base, retro):
    """Per-metric absolute and % change (retrofit − baseline)."""
    return {k: {"abs": round(retro[k] - base[k], 1),
                "pct": round((retro[k] - base[k]) / base[k] * 100.0, 1) if base[k] else 0.0}
            for k in base}


def _capex(in_scope, measures):
    """Indicative total retrofit capex [£] over the in-scope buildings."""
    capex = 0.0
    for b in in_scope:
        floor = max(1.0, b.area_m2 * b.floors)
        roof = max(1.0, b.area_m2)
        for key, (unit, basis) in MEASURE_COST.items():
            if key not in measures:
                continue
            f = measures[key]
            if key == "pv_fraction":
                intensity = energy.PV_ROOF_FRACTION * max(0.0, f - 1.0)
            elif key == "cop":
                intensity = max(0.0, f - 1.0)
            else:
                intensity = max(0.0, 1.0 - f)
            capex += unit * min(1.0, intensity) * (roof if basis == "roof" else floor)
    return capex


def _building_row(b, base, retro, in_scope):
    return {
        "id": b.id, "name": b.name, "type": b.type,
        "area_m2": b.area_m2, "floors": b.floors, "in_scope": in_scope,
        "baseline": {k: round(base[k], 1) for k in _ROW_METRICS},
        "retrofit": {k: round(retro[k], 1) for k in _ROW_METRICS},
        "delta_pct": (round((retro["energy_kwh"] - base["energy_kwh"]) /
                            base["energy_kwh"] * 100.0, 1) if base["energy_kwh"] else 0.0),
    }


def compare(buildings, measures, target=None, tariff=None):
    """Baseline vs retrofit city comparison for the given measures + target.

    Stateless: reads building geometry / type / occupancy but never mutates the
    simulation. Out-of-scope buildings keep baseline parameters in both cases, so
    the delta reflects only the targeted retrofit against the whole-city baseline.
    Returns city totals for both cases, their delta, the 24 h load profile of
    each case, an indicative cost/payback block, and per-building rows.
    """
    measures = validate_measures(measures)
    target = validate_target(target)
    tariff = DEFAULT_TARIFF if tariff is None else tariff
    if not (_is_num(tariff) and 0 <= tariff <= 100):
        raise ValueError("tariff must be a number in 0..100 (£/kWh)")
    tariff = float(tariff)

    rows, scopes = [], []          # rows: (building, base_eval, retro_eval) for all
    base_scope, retro_scope, in_scope = [], [], []   # in-scope subset for totals
    for b in buildings:
        bp = energy.base_params(b.type)
        base = evaluate_building(b, bp)
        scope = _in_scope(b, target)
        if scope:
            rp = apply_measures(bp, measures)
            retro = base if rp is bp else evaluate_building(b, rp)
            in_scope.append(b)
            base_scope.append((b, base))
            retro_scope.append((b, retro))
        else:
            retro = base
        rows.append((b, base, retro))
        scopes.append(scope)

    # Headline totals / profile cover the selected set (= whole city when target
    # is None), so a targeted comparison isn't diluted by untouched buildings.
    base_tot, base_profile = _aggregate(base_scope)
    retro_tot, retro_profile = _aggregate(retro_scope)

    capex = _capex(in_scope, measures)
    annual_kwh = (base_tot["net_kwh"] - retro_tot["net_kwh"]) * DAYS_PER_YEAR
    annual_savings = annual_kwh * tariff
    annual_co2_t = (base_tot["co2_kg"] - retro_tot["co2_kg"]) * DAYS_PER_YEAR / 1000.0
    payback = capex / annual_savings if annual_savings > 1e-6 else None

    return {
        "measures": measures,
        "target": target,
        "n_buildings": len(buildings),
        "n_in_scope": len(in_scope),
        "baseline": {k: round(v, 1) for k, v in base_tot.items()},
        "retrofit": {k: round(v, 1) for k, v in retro_tot.items()},
        "delta": _diff(base_tot, retro_tot),
        "profile_kw": {
            "baseline": [round(v, 1) for v in base_profile],
            "retrofit": [round(v, 1) for v in retro_profile],
        },
        "cost": {
            "currency": "£",
            "tariff": round(tariff, 4),
            "capex": round(capex),
            "annual_savings": round(annual_savings),
            "annual_kwh_saved": round(annual_kwh),
            "annual_co2_t_saved": round(annual_co2_t, 1),
            "payback_years": round(payback, 1) if payback is not None else None,
        },
        "buildings": [_building_row(b, base, retro, scope)
                      for (b, base, retro), scope in zip(rows, scopes)],
    }
