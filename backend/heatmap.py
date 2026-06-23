"""Overheating heat-map — a triggered "how hot does each building get today?" pass.

Framed for the UK, where most buildings (especially homes) have NO active
cooling: on a hot day the problem is buildings *overheating* because they are
built to retain heat for winter. So instead of a cooling-demand map we compute,
for each building, the PEAK indoor air temperature it free-floats to over the day
under today's real weather — with natural ventilation (wind- and temperature-
driven window opening) as the main relief, which is exactly the lever that
matters on a hot, breezy UK afternoon.

Stateless and deterministic given the weather inputs, like backend/scenario.py:
each building replays 24 h (a settle pass + a measured pass) under the same
energy-model geometry/gain functions, but with NO HVAC restore — T_in free-
floats. Weather basis is today's live Open-Meteo hourly forecast for the loaded
city (temperature, wind, cloud); a synthetic hot day is used as an offline
fallback. The result is per-building peak indoor temperature, overheating hours,
and a 0..1 severity for the map overlay.
"""
import math

from . import energy, weather
from .constants import SAMPLE_MIN, HISTORY_LEN

DT_H = SAMPLE_MIN / 60.0

# ---- natural-ventilation model (air changes per hour) ----
RHO_CP_OVER_3600 = 1200.0 / 3600.0   # air volumetric heat capacity [J/m3K] / 3600
BASE_ACH         = 0.4               # background infiltration
WIND_ACH_PER_MS  = 0.4               # wind-driven infiltration / cross-ventilation
PURGE_BASE_ACH   = 6.0               # windows opened for relief when hot
MAX_ACH          = 12.0

# ---- overheating threshold [degC] ----
OVERHEAT_THRESHOLD = 28.0   # hours above this count as "overheating"


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _synthetic_hot_day():
    """Offline fallback: a clear, hot day peaking ~31 degC at 15:00, light breeze."""
    temp = [24.0 + 7.0 * math.cos(2 * math.pi * (h - 15) / 24) for h in range(24)]
    wind = [2.0 + 1.0 * math.sin(2 * math.pi * (h - 9) / 24) for h in range(24)]
    cloud = [10.0] * 24
    return {'temp_c': temp, 'wind_ms': wind, 'cloud_pct': cloud}


def _vent_ach(T_in, T_out, wind):
    """Effective air-change rate [1/h]: infiltration + wind, plus a purge boost
    when it's hot indoors and cooler outdoors (occupants open windows)."""
    ach = BASE_ACH + WIND_ACH_PER_MS * wind
    if T_in > 23.0 and T_out < T_in - 0.5:
        relief = min(1.0, (T_in - T_out) / 6.0)
        windiness = 0.4 + 0.6 * min(1.0, wind / 4.0)
        ach += PURGE_BASE_ACH * windiness * relief
    return min(ach, MAX_ACH)


def _evaluate(b, temp, wind, solar_mult):
    """Replay 24 h of free-floating indoor temperature for one building.

    Returns peak indoor temp [degC] and overheating hours (T_in > threshold).
    Two passes: settle from the setpoint midpoint, then measure.
    """
    p = energy.base_params(b.type)
    UA = energy.envelope_UA(b.area_m2, b.floors, b.type, p)          # constant over the day
    C = p.cm_af * b.area_m2
    volume = b.area_m2 * b.floors * energy.FLOOR_HEIGHT
    dt_s = SAMPLE_MIN * 60
    T_in = 0.5 * (p.t_heat + p.t_cool)
    peak = -1e9
    overheat_samples = 0
    for measured in (False, True):
        for i in range(HISTORY_LEN):
            h = ((i * SAMPLE_MIN) % 1440) / 60.0
            hi = int(h) % 24
            T_out = temp[hi]
            Q = (energy.solar_gain_W(b.area_m2, b.floors, b.type, h,
                                     solar_mult[hi], b._ori_factor(h), p)
                 + energy.internal_gain_W(b.area_m2, b.floors, b.type, b.occupancy(h), p))
            H_ve = _vent_ach(T_in, T_out, wind[hi]) * volume * RHO_CP_OVER_3600
            T_in += (Q - (UA + H_ve) * (T_in - T_out)) / C * dt_s
            if measured:
                if T_in > peak:
                    peak = T_in
                if T_in > OVERHEAT_THRESHOLD:
                    overheat_samples += 1
    return {
        "id": b.id, "name": b.name, "type": b.type,
        "peak_t_in_c": round(peak, 1),
        "_peak": peak,
        "overheat_hours": round(overheat_samples * DT_H, 1),
    }


def compute(buildings, lat=None, lon=None):
    """Run the overheating analysis for the current buildings under today's weather.

    Pulls today's hourly forecast for (lat, lon) when available; otherwise uses a
    synthetic hot day. Returns the weather basis, a city summary, and per-building
    rows (peak indoor temp, overheating hours, 0..1 severity for the overlay).
    """
    day = weather.fetch_design_day(lat, lon) if (lat is not None and lon is not None) else None
    source = "api" if day is not None else "synthetic"
    if day is None:
        day = _synthetic_hot_day()
    temp, wind, cloud = day['temp_c'], day['wind_ms'], day['cloud_pct']
    solar_mult = [max(0.05, 1.0 - 0.8 * (c / 100.0)) for c in cloud]

    rows = [_evaluate(b, temp, wind, solar_mult) for b in buildings]
    peaks = [r["_peak"] for r in rows]
    pmin = min(peaks) if peaks else 0.0
    pmax = max(peaks) if peaks else 1.0
    rng = max(0.1, pmax - pmin)
    # Colour is normalised across the city (coolest -> green, hottest -> red) so
    # the map stays discriminating even on a day when every building overheats;
    # the absolute peak temperatures live in peak_t_in_c and the summary.
    hottest = None
    for r in rows:
        peak = r.pop("_peak")
        r["severity"] = round(_clamp((peak - pmin) / rng, 0.0, 1.0), 3)
        if hottest is None or peak > hottest["peak_t_in_c"]:
            hottest = r

    return {
        "weather": {
            "source": source,
            "peak_outdoor_c": round(max(temp), 1),
            "min_outdoor_c": round(min(temp), 1),
            "mean_wind_ms": round(sum(wind) / len(wind), 1),
        },
        "summary": {
            "n_buildings": len(rows),
            "mean_peak_c": round(sum(peaks) / len(peaks), 1) if peaks else 0.0,
            "max_peak_c": round(pmax, 1),
            "min_peak_c": round(pmin, 1),
            "hottest_name": hottest["name"] if hottest else None,
            "n_over_28": sum(1 for v in peaks if v > OVERHEAT_THRESHOLD),
            "legend_lo_c": round(pmin, 1),
            "legend_hi_c": round(pmax, 1),
            "overheat_threshold": OVERHEAT_THRESHOLD,
        },
        "buildings": rows,
    }
