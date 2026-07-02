"""Annual (8760 h) building-energy engine — real weather years, batch only.

The live sandbox stays on its tick loop; this module reuses the same pure 1C
model (backend/energy.py) to step every building through a full year at hourly
resolution, driven by either:

  - an EnergyPlus EPW/TMY weather file (--weather in backend/batch.py) — the
    standard format engineers already have for their climate, or
  - a synthetic year (seasonal + diurnal sinusoids) when no file is given —
    clearly labelled, for structure checks rather than absolute numbers.

Hourly forward-Euler is comfortably inside the 1C stability bound
(dt = 1 h << Cm/UA ≈ 20 h for heavy construction). The first WARMUP_H hours
are replayed once before accumulation so results don't depend on the initial
indoor temperature. The 0.5 kW dashboard floor is disabled here (min_kw=0) —
annual numbers must be unbiased.

Weather coupling:
  - T_out: straight from the file.
  - Solar: the model's clear-sky envelope is rescaled so the effective
    irradiance equals the file's global horizontal irradiance (GHI); PV runs
    on GHI directly. No diffuse/direct split — same coarseness as the live model.

Deliberately still a single deterministic schedule day repeated 365× (no
weekend/holiday schedules) and a single emission factor — documented in
docs/modeling-scope.md.
"""
import math

from . import energy

HOURS_PER_YEAR = 8760
WARMUP_H = 240          # replayed before accumulation to settle T_in
DT_S = 3600

# cumulative days at the start of each month (non-leap year)
_MONTH_START_DAY = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365]

# synthetic-year shape (defaults follow the live model's T_AVG/T_AMP)
SEASONAL_AMP_C = 8.0    # annual swing of the daily mean [±°C], coldest mid-January
SOLAR_SEASON_MIN = 0.30  # winter fraction of peak clear-sky irradiance

END_USES = ("energy", "hvac", "elec", "light", "pv")


def read_epw(path):
    """Parse an EnergyPlus EPW file -> (location_name, [(T_out °C, GHI W/m²)] × 8760).

    EPW layout: 8 header rows, then hourly rows; field 6 is dry-bulb [°C],
    field 13 is global horizontal irradiance [Wh/m² over the hour ≈ W/m²].
    Leap-year files (8784 rows) are truncated to 8760.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        header = f.readline().split(",")
        if header[0].strip().upper() != "LOCATION":
            raise ValueError(f"{path}: not an EPW file (first row must be LOCATION)")
        name = ",".join(p for p in (header[1].strip(), header[3].strip()) if p) or "EPW"
        for _ in range(7):
            f.readline()
        rows = []
        for lineno, line in enumerate(f, start=9):
            if not line.strip():
                continue
            fld = line.split(",")
            try:
                t_out, ghi = float(fld[6]), float(fld[13])
            except (IndexError, ValueError):
                raise ValueError(f"{path}:{lineno}: bad EPW data row")
            if t_out == 99.9 or not -70 <= t_out <= 70:   # EPW missing-value marker
                t_out = rows[-1][0] if rows else 10.0
            rows.append((t_out, max(0.0, ghi if ghi < 9999 else 0.0)))
    if len(rows) < HOURS_PER_YEAR:
        raise ValueError(f"{path}: {len(rows)} data rows, expected {HOURS_PER_YEAR}")
    return name, rows[:HOURS_PER_YEAR]


def synthetic_year(t_avg=energy.T_AVG_C, seasonal_amp=SEASONAL_AMP_C):
    """Synthetic (T_out, GHI) year: seasonal + diurnal sinusoids, clear-sky solar.

    Coldest daily mean in mid-January (t_avg − amp), warmest in mid-July;
    the live model's diurnal shape (min 05:00, max 15:00) rides on top.
    Irradiance is the model's clear-sky envelope scaled by a seasonal factor
    (SOLAR_SEASON_MIN in deep winter → 1.0 in late June). A structure check,
    not a climate — use an EPW file for defensible absolute numbers.
    """
    rows = []
    for day in range(365):
        t_mean = t_avg - seasonal_amp * math.cos(2 * math.pi * (day - 15) / 365)
        sun = (SOLAR_SEASON_MIN + (1.0 - SOLAR_SEASON_MIN) * 0.5
               * (1.0 - math.cos(2 * math.pi * (day - 172) / 365)))
        for h in range(24):
            t = t_mean - energy.T_AMP_C * math.cos(2 * math.pi * (h - 15) / 24)
            clear = max(0.0, math.sin(math.pi * (h - 6) / 12)) * energy.SOLAR_PEAK_W_M2
            rows.append((t, clear * sun))
    return f"synthetic year (mean {t_avg:g} °C, seasonal ±{seasonal_amp:g} °C)", rows


def run_building(b, params, weather):
    """Step one building through the weather year; return annual totals.

    Returns {energy_kwh_yr, hvac_kwh_yr, elec_kwh_yr, light_kwh_yr, pv_kwh_yr,
    net_kwh_yr, co2_kg_yr, peak_kw, eui_kwh_m2_yr, monthly_kwh[12]}.
    """
    p = params
    T_in = 0.5 * (p.t_heat + p.t_cool)
    tot = {k: 0.0 for k in END_USES}
    monthly = [0.0] * 12
    peak = 0.0
    month, month_end_h = 0, _MONTH_START_DAY[1] * 24

    for i in range(-WARMUP_H, HOURS_PER_YEAR):
        T_out, ghi = weather[i if i >= 0 else i + WARMUP_H]
        h = (i % 24 + 24) % 24
        occ = b.occupancy(h)
        clear = max(0.0, math.sin(math.pi * (h - 6) / 12)) * energy.SOLAR_PEAK_W_M2
        solar_mult = min(1.5, ghi / clear) if clear > 25.0 else 0.0
        T_in = energy.step_T_in(
            T_in, T_out, b.area_m2, b.floors, b.type, occ, h, DT_S,
            solar_mult=solar_mult, orientation_factor=b._ori_factor(h), params=p)
        if i < 0:
            continue
        load, hv, el, li = energy.total_load_kw(
            T_in, b.area_m2, b.floors, b.type, occ, h, params=p, min_kw=0.0)
        pv = energy.pv_gen_kw(b.area_m2, ghi / energy.SOLAR_PEAK_W_M2,
                              p.pv_fraction, p.pv_efficiency)
        tot["energy"] += load
        tot["hvac"] += hv
        tot["elec"] += el
        tot["light"] += li
        tot["pv"] += pv
        if i >= month_end_h:
            month += 1
            month_end_h = _MONTH_START_DAY[month + 1] * 24
        monthly[month] += load
        if load > peak:
            peak = load

    floor_m2 = max(1.0, b.area_m2 * b.floors)
    return {
        "energy_kwh_yr": tot["energy"],
        "hvac_kwh_yr": tot["hvac"],
        "elec_kwh_yr": tot["elec"],
        "light_kwh_yr": tot["light"],
        "pv_kwh_yr": tot["pv"],
        "net_kwh_yr": tot["energy"] - tot["pv"],
        "co2_kg_yr": tot["energy"] * energy.CO2_GRID_KG_KWH,
        "peak_kw": peak,
        "eui_kwh_m2_yr": tot["energy"] / floor_m2,
        "monthly_kwh": monthly,
    }
