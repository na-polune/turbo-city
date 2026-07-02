"""Building energy model: HVAC + electrical + lighting with 1C thermal lag.

Inspired by CEA (City Energy Analyst, ETH Zurich) and ISO 13790 / SIA 2044:
  - Thermal HVAC: simplified 1C RC node (UA envelope loss, thermal mass Cm_Af,
    solar gain through windows, internal gains from occupants + equipment)
  - Electrical: appliance power density × total floor area × occupancy schedule
  - Lighting: lighting power density × floor area × occupancy × daylight factor

Constants are sourced from CEA databases and SIA/ISO standards where noted.
All functions are pure (no state); Building in simulation.py owns T_in.

Per-building parameters (U-values, COP, lighting/appliance density, setpoints, PV)
are resolved into a frozen ``Params`` set via ``base_params(btype)``. Every model
function takes an optional ``params`` override; when omitted it falls back to the
type-keyed module constants, so the live simulation path is unchanged. Retrofit
scenarios (see backend/scenario.py) pass a modified Params to recompute "after".
"""
import math
from dataclasses import dataclass
from functools import lru_cache

from .config import load_locale

_LOCALE = load_locale()

# ---- floor geometry (H_F from CEA demand/constants.py) ----
FLOOR_HEIGHT = 3.0   # m per floor
B_F = 0.7            # ground-floor transmittance reduction factor (SIA 380/1)

# ---- envelope U-values [W/m²K] per building type ----
# Sourced from CEA envelope database (typical European building stock)
# hospital/school: modern insulation; industrial: poorly insulated shed
U_WALL = {'res': 0.5,  'office': 0.4,  'shop': 0.6,  'hospital': 0.4,  'school': 0.45, 'industrial': 0.7}
U_ROOF = {'res': 0.3,  'office': 0.25, 'shop': 0.35, 'hospital': 0.25, 'school': 0.28, 'industrial': 0.45}
U_WIN  = {'res': 2.0,  'office': 1.8,  'shop': 2.5,  'hospital': 1.8,  'school': 2.0,  'industrial': 2.8}
U_BASE = 0.5          # ground slab [W/m²K]

# ---- window-to-wall ratio [-] ----
WIN_WALL = {'res': 0.25, 'office': 0.40, 'shop': 0.35, 'hospital': 0.30, 'school': 0.30, 'industrial': 0.15}

# ---- combined ventilation + infiltration air-change rate [1/h] ----
# Whole-building outdoor-air rate (mechanical/natural ventilation + envelope
# leakage, no heat recovery), representative of CEA/ASHRAE 62.1 stock values.
# hospital: high hygiene air-change requirement; shop/school: door traffic.
ACH = {'res': 0.5, 'office': 0.7, 'shop': 0.9, 'hospital': 1.2, 'school': 1.0, 'industrial': 0.8}

# volumetric heat capacity of air [Wh/m³K] (1.2 kg/m³ × 1005 J/kgK ÷ 3600)
RHO_CP_AIR_WH_M3K = 0.34

# ---- solar heat gain coefficient of glazing [-] (G_win in CEA) ----
G_WIN = {'res': 0.55, 'office': 0.50, 'shop': 0.60, 'hospital': 0.50, 'school': 0.55, 'industrial': 0.55}

# ---- peak clear-sky solar irradiance [W/m²] (simplified, isotropic) ----
SOLAR_PEAK_W_M2 = 500.0

# ---- thermal mass [J/K per m² of footprint area] (Cm_Af in CEA) ----
# Heavy concrete construction: ~165 000; light construction: ~80 000
Cm_Af = {'res': 165_000, 'office': 165_000, 'shop': 100_000, 'hospital': 165_000, 'school': 165_000, 'industrial': 80_000}

# ---- HVAC comfort setpoints [°C] per building type ----
# CEA USE_TYPES.csv: hospital Ths=22/Tcs=26, school Ths=21/Tcs=26, industrial Ths=18/Tcs=30
T_HEAT = {'res': 20.0, 'office': 21.0, 'shop': 19.0, 'hospital': 22.0, 'school': 21.0, 'industrial': 18.0}
T_COOL = {'res': 26.0, 'office': 24.0, 'shop': 25.0, 'hospital': 26.0, 'school': 26.0, 'industrial': 30.0}

# ---- system COP (coefficient of performance) ----
COP_HEAT = 3.0   # heat pump heating
COP_COOL = 3.0   # chiller cooling

# ---- appliance power density [W/m² of total floor area] (Ea_Wm2 in CEA) ----
# industrial includes process loads (Ea + Epro from CEA)
E_DENSITY = {'res': 4.0, 'office': 12.0, 'shop': 8.0, 'hospital': 13.0, 'school': 4.0, 'industrial': 26.5}

# ---- lighting power density [W/m² of total floor area] (El_Wm2 in CEA) ----
LPD = {'res': 6.0, 'office': 12.0, 'shop': 20.0, 'hospital': 11.0, 'school': 14.0, 'industrial': 10.8}

# ---- fraction of electrical load that becomes internal heat gain ----
ELEC_TO_HEAT = 0.9

# ---- synthetic outdoor temperature profile ----
T_AVG_C = 12.0   # annual mean [°C]
T_AMP_C =  6.0   # daily amplitude [°C]

BUILDING_TYPES = tuple(U_WALL)

# ---- rooftop PV model (inspired by CEA pv.py) ----
PV_EFFICIENCY    = 0.18   # monocrystalline panel efficiency [-]
PV_ROOF_FRACTION = 0.40   # usable roof area fraction (excludes obstacles, shading)

# ---- CO₂ emission factor for grid electricity [kg CO₂/kWh] ----
# Default: UK National Grid 2024 average (source: DESNZ / CEA energy_carriers.py).
# Localizable via input/config.json → "locale": {"co2_grid_kg_kwh": ...}.
CO2_GRID_KG_KWH = float(_LOCALE.get("co2_grid_kg_kwh", 0.233))


@dataclass(frozen=True)
class Params:
    """Resolved energy parameters for one building (one building type's values).

    Defaults come from the type-keyed module constants via ``base_params``; a
    retrofit scenario derives a modified copy with ``dataclasses.replace``.
    Frozen so cached/shared instances can never be mutated by accident.
    """
    u_wall: float        # external wall U-value [W/m²K]
    u_roof: float        # roof U-value [W/m²K]
    u_win: float         # window U-value [W/m²K]
    win_wall: float      # window-to-wall ratio [-]
    g_win: float         # glazing solar heat gain coefficient [-]
    ach: float           # ventilation + infiltration air changes per hour [1/h]
    cm_af: float         # thermal mass [J/K per m² footprint]
    t_heat: float        # heating setpoint [°C]
    t_cool: float        # cooling setpoint [°C]
    cop_heat: float      # heating system COP [-]
    cop_cool: float      # cooling system COP [-]
    e_density: float     # appliance power density [W/m²]
    lpd: float           # lighting power density [W/m²]
    pv_fraction: float   # usable roof fraction for PV [-]
    pv_efficiency: float # PV panel efficiency [-]


@lru_cache(maxsize=None)
def base_params(btype: str) -> Params:
    """Baseline Params for a building type, built from the module constants.

    Cached: the constants never change at runtime, so each type resolves once and
    the live loop reuses one shared frozen instance (no per-call allocation).
    """
    return Params(
        u_wall=U_WALL[btype], u_roof=U_ROOF[btype], u_win=U_WIN[btype],
        win_wall=WIN_WALL[btype], g_win=G_WIN[btype], ach=ACH[btype], cm_af=Cm_Af[btype],
        t_heat=T_HEAT[btype], t_cool=T_COOL[btype],
        cop_heat=COP_HEAT, cop_cool=COP_COOL,
        e_density=E_DENSITY[btype], lpd=LPD[btype],
        pv_fraction=PV_ROOF_FRACTION, pv_efficiency=PV_EFFICIENCY,
    )


def _resolve(btype, params):
    """Pick the explicit params override, or the cached baseline for the type."""
    return base_params(btype) if params is None else params


def pv_gen_kw(area_m2: float, solar_mult: float = 1.0,
              pv_fraction: float = PV_ROOF_FRACTION,
              pv_efficiency: float = PV_EFFICIENCY) -> float:
    """Rooftop PV generation [kW].

    Flat roof approximation: usable area × panel efficiency × peak irradiance × cloud factor.
    Equivalent to CEA's PhotovoltaicPanel.calc_PV_power() simplified to a scalar.
    pv_fraction / pv_efficiency default to the module constants; a retrofit scenario
    passes a building's Params values to model added rooftop PV.
    """
    return area_m2 * pv_fraction * pv_efficiency * SOLAR_PEAK_W_M2 * solar_mult / 1000.0


def co2_kg_h(load_kw: float) -> float:
    """Operational CO₂ emissions [kg/h] from grid electricity consumption."""
    return load_kw * CO2_GRID_KG_KWH


def outdoor_temp_c(clock_min):
    """Synthetic daily outdoor temperature: minimum at 5 am, maximum at 3 pm."""
    hour = (clock_min % 1440) / 60.0
    return T_AVG_C - T_AMP_C * math.cos(2 * math.pi * (hour - 15) / 24)


def envelope_UA(area_m2, floors, btype, params=None):
    """Total envelope UA [W/K]: walls + windows + roof + ground slab.

    Envelope area is estimated from a square footprint (perimeter = 4√area).
    Matches CEA's BuildingRCModel.calc_prop_rc_model() breakdown by surface type.
    """
    p = _resolve(btype, params)
    h_total    = floors * FLOOR_HEIGHT
    perimeter  = 4.0 * math.sqrt(area_m2)
    wall_gross = perimeter * h_total
    win_area   = wall_gross * p.win_wall
    wall_net   = wall_gross - win_area
    return (p.u_wall * wall_net
          + p.u_win  * win_area
          + p.u_roof * area_m2
          + U_BASE   * area_m2 * B_F)


def ventilation_UA(area_m2, floors, btype, params=None):
    """Ventilation + infiltration conductance [W/K]: ρ·cp·ACH·V ÷ 3600.

    A second heat-loss path alongside the envelope: outdoor air exchanged at
    `ach` air changes per hour over the building volume. No heat recovery —
    retrofitting air-tightness/MVHR is modelled by scaling `ach` down
    (the "ach" measure in backend/scenario.py).
    """
    p = _resolve(btype, params)
    volume = area_m2 * floors * FLOOR_HEIGHT
    return RHO_CP_AIR_WH_M3K * p.ach * volume


def facade_orientation_factor(polygon):
    """Compute a solar exposure factor [0–1] for a building polygon at a given hour.

    Returns a callable f(hour) -> float that gives the weighted fraction of
    solar irradiance received by the building's façades at that hour.

    Method (after CEA calc_I_sol):
    - For each wall edge, compute the outward normal angle (east=0, north=90°).
    - At solar noon the sun is due south (azimuth=180°), at 6 am due east (90°).
    - Each face receives cos(angle_face_to_sun) irradiance, clamped to ≥0.
    - Weight by wall length; normalise so an isotropic building gives 0.25.
    """
    n = len(polygon)
    if n < 3:
        return lambda _: 0.25

    # Wall normals: outward normal angle in degrees from east (CCW)
    normals = []    # (normal_deg, length)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey)
        if length < 0.1:
            continue
        # outward normal rotated 90° clockwise from edge direction (x-east, y-south coords)
        nx, ny = ey, -ex
        normal_deg = math.degrees(math.atan2(-nx, ny)) % 360  # 0=north, 90=east, 180=south
        normals.append((normal_deg, length))

    if not normals:
        return lambda _: 0.25

    total_len = sum(L for _, L in normals)

    def _factor(hour):
        # Solar azimuth: 90° (east) at 6 am, 180° (south) at noon, 270° (west) at 18
        solar_az = 90.0 + (hour - 6.0) * 10.0    # 15°/hour from east
        gain = 0.0
        for nd, L in normals:
            diff = math.radians(nd - solar_az)
            gain += max(0.0, math.cos(diff)) * L
        # Normalise: a square building with uniform orientation gives total_len/4 on average
        return gain / total_len if total_len > 0 else 0.25

    return _factor


def solar_gain_W(area_m2, floors, btype, hour, solar_mult=1.0, orientation_factor=0.25, params=None):
    """Solar gain through windows [W].

    orientation_factor: per-face weighted exposure fraction (0–1).
    Default 0.25 (isotropic) is used when no polygon is available.
    Analogous to CEA's calc_I_sol() in sensible_loads.py.
    solar_mult (0–1) scales for cloud cover from the weather model.
    """
    p = _resolve(btype, params)
    wall_gross = 4.0 * math.sqrt(area_m2) * floors * FLOOR_HEIGHT
    win_area   = wall_gross * p.win_wall
    I_sol = max(0.0, math.sin(math.pi * (hour - 6) / 12)) * SOLAR_PEAK_W_M2
    return win_area * p.g_win * I_sol * orientation_factor * solar_mult


def internal_gain_W(area_m2, floors, btype, occ, params=None):
    """Internal heat gains from equipment + people [W].

    Fraction ELEC_TO_HEAT of electrical appliance load stays in the zone as
    heat — consistent with CEA's sensible internal gains (Qs, Qgain_sen).
    """
    p = _resolve(btype, params)
    return area_m2 * floors * p.e_density * occ * ELEC_TO_HEAT


def step_T_in(T_in, T_out, area_m2, floors, btype, occ, hour, sim_dt_s,
              solar_mult=1.0, ua_mult=1.0, orientation_factor=0.25, params=None):
    """Advance indoor air temperature by sim_dt_s simulation-seconds.

    1C RC node: C·dT/dt = Q_gain - UA·(T_in - T_out)
    Euler integration; stable for sim_dt_s << Cm/UA (~20 h for heavy buildings).
    Mirrors the single-zone ISO 13790 / SIA 2044 5R1C model reduced to 1C.
    UA is envelope + ventilation/infiltration; solar_mult scales solar gain
    (clouds); ua_mult scales both loss paths (rain/wind also drives infiltration).
    """
    p      = _resolve(btype, params)
    UA     = (envelope_UA(area_m2, floors, btype, p)
              + ventilation_UA(area_m2, floors, btype, p)) * ua_mult
    Cm     = p.cm_af * area_m2
    Q_gain = (solar_gain_W(area_m2, floors, btype, hour, solar_mult, orientation_factor, p)
              + internal_gain_W(area_m2, floors, btype, occ, p))
    Q_loss = UA * (T_in - T_out)
    return T_in + (Q_gain - Q_loss) / Cm * sim_dt_s


def hvac_kw(T_in, area_m2, floors, btype, ua_mult=1.0, params=None):
    """HVAC power [kW] to restore the comfort setpoint.

    Proportional to the UA-weighted temperature deviation from setpoint,
    divided by system COP — consistent with CEA's calc_Qhs_Qcs_sys_max() logic.
    Heating when T_in < T_HEAT, cooling when T_in > T_COOL, idle in between.
    UA is envelope + ventilation/infiltration, scaled by ua_mult (rain/wind).
    """
    p = _resolve(btype, params)
    UA = (envelope_UA(area_m2, floors, btype, p)
          + ventilation_UA(area_m2, floors, btype, p)) * ua_mult
    if T_in < p.t_heat:
        return UA * (p.t_heat - T_in) / (1000.0 * p.cop_heat)
    if T_in > p.t_cool:
        return UA * (T_in - p.t_cool) / (1000.0 * p.cop_cool)
    return 0.0


def electrical_kw(area_m2, floors, btype, occ, params=None):
    """Appliance electrical load [kW].

    Power density × total floor area × occupancy fraction.
    Equivalent to CEA's calc_Eal_Epro(): Ea_Wm2 × Af × schedule.
    """
    p = _resolve(btype, params)
    return area_m2 * floors * p.e_density * occ / 1000.0


def lighting_kw(area_m2, floors, btype, occ, hour, params=None):
    """Lighting load [kW] reduced by daylight availability.

    Daylight factor peaks at solar noon (hour=12) and drops to zero outside
    6–18 h, cutting lighting demand by up to 80% — analogous to how CEA's
    El_schedule encodes lower lighting use during daylight hours.
    """
    p = _resolve(btype, params)
    if 6.0 <= hour <= 18.0:
        daylight = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))
    else:
        daylight = 0.0
    return area_m2 * floors * p.lpd * occ * (1.0 - 0.8 * daylight) / 1000.0


def total_load_kw(T_in, area_m2, floors, btype, occ, hour, ua_mult=1.0, params=None,
                  min_kw=0.5):
    """Total building load [kW] and component breakdown.

    Returns (total, hvac, electrical, lighting). The default 0.5 kW floor keeps
    buildings from reading zero on the dashboard — a UI nicety, not physics.
    Analytical paths that need unbiased numbers (backend/annual.py) pass min_kw=0.
    """
    p = _resolve(btype, params)
    h = hvac_kw(T_in, area_m2, floors, btype, ua_mult, p)
    e = electrical_kw(area_m2, floors, btype, occ, p)
    l = lighting_kw(area_m2, floors, btype, occ, hour, p)
    total = max(min_kw, h + e + l)
    return total, h, e, l
