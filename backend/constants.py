"""Simulation constants — calibration, defaults, limits, and flavor data.

Runtime-configurable values (world, seed, tick rate, time warp) belong in
input/config.json; per-world agent speeds belong in input/{map,grid}.json.
Everything here is developer-facing: change it when the model changes, not
when running a new scenario.
"""

# ---- sampling / history ----
SAMPLE_MIN  = 10     # energy / pedometer sample every N sim minutes
HISTORY_LEN = 144    # 24 h × 6 samples/h

# ---- car telemetry ring buffer ----
CAR_SPD_LEN = 120    # samples kept (~60 s window at CAR_SPD_DT = 0.5 s)
CAR_SPD_DT  = 0.5   # real-seconds between speed samples

# ---- pedometer ----
STEPS_PER_M = 1.35   # converts meters walked to step count

# ---- runtime defaults (overridable via input/config.json) ----
TICK_HZ         = 10
SIM_MIN_PER_SEC = 1.0   # 1 real second = 1 sim minute → full day in 24 real minutes

# ---- agent speed fallbacks (overridable per world via input/{map,grid}.json) ----
CAR_SPEED_MPS    = (6.0, 9.0)   # [min, max] cruising speed, m/s
PERSON_SPEED_MPS = (1.1, 1.7)   # [min, max] walking speed, m/s

OCC = {
    'res':      [(0, 0.25), (5, 0.3),  (7, 0.55), (9, 0.35),  (12, 0.3),
                 (16, 0.45), (19, 0.9), (22, 0.7),  (24, 0.25)],
    'office':   [(0, 0.06), (6, 0.08), (8, 0.7),  (12, 0.85), (14, 0.8),
                 (17, 0.7),  (19, 0.25), (22, 0.08), (24, 0.06)],
    'shop':     [(0, 0.04), (8, 0.1),  (10, 0.65), (13, 0.8), (17, 0.85),
                 (20, 0.5),  (21.5, 0.08), (24, 0.04)],
    # CEA HOSPITAL schedule: 24/7 baseline ~0.43, peaks 9–10 and 14–15 at 1.0
    'hospital': [(0, 0.43), (7, 0.55), (9, 1.0), (12, 0.66), (14, 1.0),
                 (17, 0.55), (18, 0.43), (24, 0.43)],
    # CEA SCHOOL schedule: empty at night, 7–17 school day
    'school':   [(0, 0.0), (7, 0.4), (8, 0.6), (9, 1.0), (11, 0.8),
                 (12, 0.2), (13, 0.6), (15, 0.8), (17, 0.4), (18, 0.0), (24, 0.0)],
    # CEA INDUSTRIAL schedule: low overnight (0.2), shift 6–18 at high load
    'industrial': [(0, 0.2), (5, 0.5), (6, 0.8), (7, 1.0), (11, 0.5),
                   (12, 0.8), (14, 1.0), (18, 0.5), (22, 0.2), (24, 0.2)],
}

# ---- energy model (replaced by backend/energy.py) ----
# TILE_M2 and PEAK_COEF removed; see energy.py for the CEA-inspired model.

# ---- edit / spawn limits ----
MAX_FLOORS      = 20
MAX_CARS        = 50
MAX_PEOPLE      = 100
MAX_BUILDINGS   = 500
MIN_BUILDING_M2 = 25
DEFAULT_FLOORS  = {'res': 3, 'office': 4, 'shop': 2, 'hospital': 4, 'school': 2, 'industrial': 1}

# ---- agent flavor ----
CAR_NAMES  = ['Sedan', 'Hatchback', 'Coupe', 'Van', 'Pickup', 'Mini', 'Wagon', 'Taxi']
CAR_COLORS = ['#d4453a', '#3a6fd4', '#e8e8ea', '#23252b', '#f2c14e', '#5fa052', '#9b59b6', '#e67e22']
FIRST      = ['Wei', 'Mei', 'Jun', 'Hua', 'Xin', 'Yan', 'Ming', 'Ling', 'Chen', 'Amara',
               'Ben', 'Clara', 'Dmitri', 'Elena', 'Felix', 'Grace', 'Hugo', 'Iris', 'Maya', 'Theo']
LAST       = ['Chen', 'Wang', 'Zhang', 'Liu', 'Lin', 'Smith', 'Jones', 'Brown', 'Garcia',
               'Miller', 'Khan', 'Patel', 'Kim', 'Park', 'Sato', 'Novak', 'Silva', 'Rossi', 'Weber', 'Olsen']
SHIRTS     = ['#d4453a', '#3a6fd4', '#f2c14e', '#5fa052', '#9b59b6', '#e67e22', '#5fd4a8', '#d36a9b']
