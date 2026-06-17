"""Building energy model: HVAC + electrical + lighting with 1C thermal lag.

Inspired by CEA (City Energy Analyst, ETH Zurich) and ISO 13790 / SIA 2044:
  - Thermal HVAC: simplified 1C RC node (UA envelope loss, thermal mass Cm_Af,
    solar gain through windows, internal gains from occupants + equipment)
  - Electrical: appliance power density × total floor area × occupancy schedule
  - Lighting: lighting power density × floor area × occupancy × daylight factor

Constants are sourced from CEA databases and SIA/ISO standards where noted.
All functions are pure (no state); Building in simulation.py owns T_in.
"""
import math

# ---- floor geometry (H_F from CEA demand/constants.py) ----
FLOOR_HEIGHT = 3.0   # m per floor
B_F = 0.7            # ground-floor transmittance reduction factor (SIA 380/1)

# ---- envelope U-values [W/m²K] per building type ----
# Sourced from CEA envelope database (typical European building stock)
U_WALL = {'res': 0.5,  'office': 0.4,  'shop': 0.6}
U_ROOF = {'res': 0.3,  'office': 0.25, 'shop': 0.35}
U_WIN  = {'res': 2.0,  'office': 1.8,  'shop': 2.5}
U_BASE = 0.5          # ground slab [W/m²K]

# ---- window-to-wall ratio [-] ----
WIN_WALL = {'res': 0.25, 'office': 0.40, 'shop': 0.35}

# ---- solar heat gain coefficient of glazing [-] (G_win in CEA) ----
G_WIN = {'res': 0.55, 'office': 0.50, 'shop': 0.60}

# ---- peak clear-sky solar irradiance [W/m²] (simplified, isotropic) ----
SOLAR_PEAK_W_M2 = 500.0

# ---- thermal mass [J/K per m² of footprint area] (Cm_Af in CEA) ----
# Heavy concrete construction: ~165 000; light construction: ~80 000
Cm_Af = {'res': 165_000, 'office': 165_000, 'shop': 100_000}

# ---- HVAC comfort setpoints [°C] per building type ----
T_HEAT = {'res': 20.0, 'office': 21.0, 'shop': 19.0}
T_COOL = {'res': 26.0, 'office': 24.0, 'shop': 25.0}

# ---- system COP (coefficient of performance) ----
COP_HEAT = 3.0   # heat pump heating
COP_COOL = 3.0   # chiller cooling

# ---- appliance power density [W/m² of total floor area] (Ea_Wm2 in CEA) ----
E_DENSITY = {'res': 4.0, 'office': 12.0, 'shop': 8.0}

# ---- lighting power density [W/m² of total floor area] (El_Wm2 in CEA) ----
LPD = {'res': 6.0, 'office': 12.0, 'shop': 20.0}

# ---- fraction of electrical load that becomes internal heat gain ----
ELEC_TO_HEAT = 0.9

# ---- synthetic outdoor temperature profile ----
T_AVG_C = 12.0   # annual mean [°C]
T_AMP_C =  6.0   # daily amplitude [°C]

BUILDING_TYPES = tuple(U_WALL)   # valid type strings: 'office', 'res', 'shop'


def outdoor_temp_c(clock_min):
    """Synthetic daily outdoor temperature: minimum at 5 am, maximum at 3 pm."""
    hour = (clock_min % 1440) / 60.0
    return T_AVG_C - T_AMP_C * math.cos(2 * math.pi * (hour - 15) / 24)


def envelope_UA(area_m2, floors, btype):
    """Total envelope UA [W/K]: walls + windows + roof + ground slab.

    Envelope area is estimated from a square footprint (perimeter = 4√area).
    Matches CEA's BuildingRCModel.calc_prop_rc_model() breakdown by surface type.
    """
    h_total    = floors * FLOOR_HEIGHT
    perimeter  = 4.0 * math.sqrt(area_m2)
    wall_gross = perimeter * h_total
    win_area   = wall_gross * WIN_WALL[btype]
    wall_net   = wall_gross - win_area
    return (U_WALL[btype] * wall_net
          + U_WIN[btype]  * win_area
          + U_ROOF[btype] * area_m2
          + U_BASE        * area_m2 * B_F)


def solar_gain_W(area_m2, floors, btype, hour, solar_mult=1.0):
    """Simplified solar gain through windows [W].

    Uses an isotropic clear-sky irradiance profile and a mean façade exposure
    factor of 0.25 (average of four orientations at 45° incidence).
    Analogous to CEA's calc_I_sol() in sensible_loads.py.
    solar_mult (0–1) scales for cloud cover from the weather model.
    """
    wall_gross = 4.0 * math.sqrt(area_m2) * floors * FLOOR_HEIGHT
    win_area   = wall_gross * WIN_WALL[btype]
    I_sol = max(0.0, math.sin(math.pi * (hour - 6) / 12)) * SOLAR_PEAK_W_M2
    return win_area * G_WIN[btype] * I_sol * 0.25 * solar_mult


def internal_gain_W(area_m2, floors, btype, occ):
    """Internal heat gains from equipment + people [W].

    Fraction ELEC_TO_HEAT of electrical appliance load stays in the zone as
    heat — consistent with CEA's sensible internal gains (Qs, Qgain_sen).
    """
    return area_m2 * floors * E_DENSITY[btype] * occ * ELEC_TO_HEAT


def step_T_in(T_in, T_out, area_m2, floors, btype, occ, hour, sim_dt_s,
              solar_mult=1.0, ua_mult=1.0):
    """Advance indoor air temperature by sim_dt_s simulation-seconds.

    1C RC node: C·dT/dt = Q_gain - UA·(T_in - T_out)
    Euler integration; stable for sim_dt_s << Cm/UA (~20 h for heavy buildings).
    Mirrors the single-zone ISO 13790 / SIA 2044 5R1C model reduced to 1C.
    solar_mult scales solar gain (clouds); ua_mult scales envelope loss (rain/wind).
    """
    UA     = envelope_UA(area_m2, floors, btype) * ua_mult
    Cm     = Cm_Af[btype] * area_m2
    Q_gain = solar_gain_W(area_m2, floors, btype, hour, solar_mult) + internal_gain_W(area_m2, floors, btype, occ)
    Q_loss = UA * (T_in - T_out)
    return T_in + (Q_gain - Q_loss) / Cm * sim_dt_s


def hvac_kw(T_in, area_m2, floors, btype, ua_mult=1.0):
    """HVAC power [kW] to restore the comfort setpoint.

    Proportional to the UA-weighted temperature deviation from setpoint,
    divided by system COP — consistent with CEA's calc_Qhs_Qcs_sys_max() logic.
    Heating when T_in < T_HEAT, cooling when T_in > T_COOL, idle in between.
    ua_mult scales envelope conductance (e.g. higher in rain/wind).
    """
    UA = envelope_UA(area_m2, floors, btype) * ua_mult
    if T_in < T_HEAT[btype]:
        return UA * (T_HEAT[btype] - T_in) / (1000.0 * COP_HEAT)
    if T_in > T_COOL[btype]:
        return UA * (T_in - T_COOL[btype]) / (1000.0 * COP_COOL)
    return 0.0


def electrical_kw(area_m2, floors, btype, occ):
    """Appliance electrical load [kW].

    Power density × total floor area × occupancy fraction.
    Equivalent to CEA's calc_Eal_Epro(): Ea_Wm2 × Af × schedule.
    """
    return area_m2 * floors * E_DENSITY[btype] * occ / 1000.0


def lighting_kw(area_m2, floors, btype, occ, hour):
    """Lighting load [kW] reduced by daylight availability.

    Daylight factor peaks at solar noon (hour=12) and drops to zero outside
    6–18 h, cutting lighting demand by up to 80% — analogous to how CEA's
    El_schedule encodes lower lighting use during daylight hours.
    """
    if 6.0 <= hour <= 18.0:
        daylight = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))
    else:
        daylight = 0.0
    return area_m2 * floors * LPD[btype] * occ * (1.0 - 0.8 * daylight) / 1000.0


def total_load_kw(T_in, area_m2, floors, btype, occ, hour, ua_mult=1.0):
    """Total building load [kW] and component breakdown.

    Returns (total, hvac, electrical, lighting). Minimum 0.5 kW so buildings
    never read zero on the dashboard.
    """
    h = hvac_kw(T_in, area_m2, floors, btype, ua_mult)
    e = electrical_kw(area_m2, floors, btype, occ)
    l = lighting_kw(area_m2, floors, btype, occ, hour)
    total = max(0.5, h + e + l)
    return total, h, e, l
