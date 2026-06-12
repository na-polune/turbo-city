"""City simulation core (no web code) on a street network.

Which world to load — and everything about it — comes from the input/ folder
(see backend.config): "world": "map" runs the real OSM area from input/map.json,
"world": "grid" runs the hand-made test scene from input/grid.json.
Agents random-walk the street graph (edge to edge, avoid reversing) —
same design as the original toy version, just on real geometry in meters.
"""
import math
import random

from . import config, grid_world, osm_world

WORLD_BUILDERS = {
    "map": osm_world.build_world,
    "grid": grid_world.build_world,
}

# ---- time (defaults; overridable per run via input/config.json) ----
TICK_HZ = 10              # simulation ticks per real second
SIM_MIN_PER_SEC = 1.0     # 1 real second = 1 sim minute (full day in 24 real minutes)
SAMPLE_MIN = 10           # energy / pedometer sample every N sim minutes
HISTORY_LEN = 144         # 24 h * 6 samples/h

# ---- telemetry ----
CAR_SPD_LEN = 120         # speed ring buffer
CAR_SPD_DT = 0.5          # sample every 0.5 real seconds (60 s window)
STEPS_PER_M = 1.35        # pedometer scale

# ---- agent speed defaults (overridable per world via input/{map,grid}.json) ----
CAR_SPEED_MPS = (6.0, 9.0)        # [min, max] cruising speed, m/s
PERSON_SPEED_MPS = (1.1, 1.7)     # [min, max] walking speed, m/s

CAR_NAMES = ['Sedan', 'Hatchback', 'Coupe', 'Van', 'Pickup', 'Mini', 'Wagon', 'Taxi']
CAR_COLORS = ['#d4453a', '#3a6fd4', '#e8e8ea', '#23252b', '#f2c14e', '#5fa052', '#9b59b6', '#e67e22']
FIRST = ['Wei', 'Mei', 'Jun', 'Hua', 'Xin', 'Yan', 'Ming', 'Ling', 'Chen', 'Amara',
         'Ben', 'Clara', 'Dmitri', 'Elena', 'Felix', 'Grace', 'Hugo', 'Iris', 'Maya', 'Theo']
LAST = ['Chen', 'Wang', 'Zhang', 'Liu', 'Lin', 'Smith', 'Jones', 'Brown', 'Garcia',
        'Miller', 'Khan', 'Patel', 'Kim', 'Park', 'Sato', 'Novak', 'Silva', 'Rossi', 'Weber', 'Olsen']
SHIRTS = ['#d4453a', '#3a6fd4', '#f2c14e', '#5fa052', '#9b59b6', '#e67e22', '#5fd4a8', '#d36a9b']


def piecewise(points, h):
    """Piecewise-linear curve over 24 h; points = [(hour, value), ...] sorted."""
    h = h % 24.0
    for (h0, v0), (h1, v1) in zip(points, points[1:]):
        if h0 <= h <= h1:
            t = (h - h0) / (h1 - h0)
            return v0 + (v1 - v0) * t
    return points[-1][1]


OCC = {
    'res':    [(0, 0.25), (5, 0.3), (7, 0.55), (9, 0.35), (12, 0.3), (16, 0.45),
               (19, 0.9), (22, 0.7), (24, 0.25)],
    'office': [(0, 0.06), (6, 0.08), (8, 0.7), (12, 0.85), (14, 0.8), (17, 0.7),
               (19, 0.25), (22, 0.08), (24, 0.06)],
    'shop':   [(0, 0.04), (8, 0.1), (10, 0.65), (13, 0.8), (17, 0.85), (20, 0.5),
               (21.5, 0.08), (24, 0.04)],
}
PEAK_COEF = {'res': 5, 'office': 9, 'shop': 13}
TILE_M2 = 25      # the reference model was per 5x5 m tile

# ---- edit limits ----
MAX_FLOORS = 20
MAX_CARS = 50
MAX_PEOPLE = 100


class Building:
    def __init__(self, data, rng):
        self.rng = rng
        self.id = data["id"]
        self.name = data["name"]
        self.type = data["type"]
        self.floors = data["floors"]
        self.area_m2 = data["area_m2"]
        self.center = data["center"]
        self._recompute_coeffs()
        self.noise = 0.0
        self.load_kw = 0.0
        self.history = [0.0] * HISTORY_LEN
        self.hist_idx = 0

    def _recompute_coeffs(self):
        tiles = self.area_m2 / TILE_M2
        self.base = 2 + self.floors * 1.4 * tiles
        self.peak = self.floors * PEAK_COEF[self.type] * tiles

    def set_floors(self, floors):
        self.floors = floors
        self._recompute_coeffs()    # load changes from the next tick on

    def occupancy(self, hour):
        return piecewise(OCC[self.type], hour)

    def compute_load(self, hour):
        self.noise += (self.rng.random() - 0.5) * 0.05
        self.noise = max(-0.12, min(0.12, self.noise))
        return max(0.5, (self.base + self.peak * self.occupancy(hour)) * (1 + self.noise))

    def estimate_load(self, hour):
        """Cheap per-tick estimate: occupancy curve with the last sampled noise."""
        return max(0.5, (self.base + self.peak * self.occupancy(hour)) * (1 + self.noise))

    def prefill(self, now_min):
        for i in range(HISTORY_LEN):
            m = now_min - (HISTORY_LEN - 1 - i) * SAMPLE_MIN
            self.history[i] = self.compute_load((m % 1440) / 60.0)
        self.hist_idx = 0
        self.load_kw = self.history[-1]

    def sample(self, hour):
        self.load_kw = self.compute_load(hour)
        self.history[self.hist_idx] = self.load_kw
        self.hist_idx = (self.hist_idx + 1) % HISTORY_LEN

    def history_series(self):
        return [round(self.history[(self.hist_idx + i) % HISTORY_LEN], 1)
                for i in range(HISTORY_LEN)]


class Walker:
    """Random-walk along a graph: edge (a -> b) with progress in meters."""

    def __init__(self, graph, rng, lateral=0.0, near=None):
        self.rng = rng
        self.lateral = lateral          # right-hand offset from the centerline, meters
        self._place(graph, near)

    def _place(self, graph, near=None):
        self.nodes = graph["nodes"]
        self.adj = graph["adj"]
        comp = largest_component(self.adj)
        if near is not None:            # start at the closest reachable node
            start = min(comp, key=lambda n: (self.nodes[n][0] - near[0]) ** 2 +
                                            (self.nodes[n][1] - near[1]) ** 2)
        else:
            start = self.rng.choice(comp)
        self.prev = start
        self._set_edge(start, self.rng.choice(self.adj[start]))

    def reseat(self, graph):
        """Re-home onto a rebuilt graph near the current position (road edits)."""
        self._place(graph, self.pos())

    def _neighbor_id(self, entry):
        return entry[0] if isinstance(entry, (list, tuple)) else entry

    def _set_edge(self, a, entry):
        self.a = a
        self.b = self._neighbor_id(entry)
        self.edge_meta = entry[1] if isinstance(entry, (list, tuple)) else None
        ax, ay = self.nodes[self.a]
        bx, by = self.nodes[self.b]
        self.edge_len = max(0.1, math.hypot(bx - ax, by - ay))
        self.ux, self.uy = (bx - ax) / self.edge_len, (by - ay) / self.edge_len
        self.t = 0.0

    def advance(self, dist):
        self.t += dist
        while self.t >= self.edge_len:
            self.t -= self.edge_len
            options = [e for e in self.adj[self.b] if self._neighbor_id(e) != self.a]
            if not options:
                options = self.adj[self.b]
            self.prev = self.a
            self._set_edge(self.b, self.rng.choice(options))

    def pos(self):
        ax, ay = self.nodes[self.a]
        x = ax + self.ux * self.t
        y = ay + self.uy * self.t
        # right-hand perpendicular in x-east / y-south coords
        return x - self.uy * self.lateral, y + self.ux * self.lateral

    def heading(self):
        return self.ux, self.uy


def largest_component(adj):
    """Node ids of the largest connected component (agents must not strand)."""
    seen, best = set(), []
    for start in adj:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for e in adj[n]:
                m = e[0] if isinstance(e, (list, tuple)) else e
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if len(comp) > len(best):
            best = comp
    return best


class Car(Walker):
    def __init__(self, i, graph, rng, speed_range=CAR_SPEED_MPS, near=None):
        super().__init__(graph, rng, lateral=1.5, near=near)
        self.id = i
        self.name = f"{CAR_NAMES[i % len(CAR_NAMES)]} {i + 1}"
        self.color = CAR_COLORS[i % len(CAR_COLORS)]
        lo, hi = speed_range
        self.base_speed = lo + rng.random() * (hi - lo)   # m/s
        self.speed = self.base_speed
        self.distance_m = 0.0
        self.spd = [0.0] * CAR_SPD_LEN
        self.spd_idx = 0
        self.spd_count = 0

    def move(self, dt):
        # slower on narrow streets, ease off near the end of each edge
        width = self.edge_meta or 6
        cls_factor = max(0.5, min(1.2, width / 7))
        edge_room = min(self.t, self.edge_len - self.t)
        ease = max(0.45, min(1.0, (edge_room + 4) / 12))
        self.speed = self.base_speed * cls_factor * ease
        d = self.speed * dt
        self.advance(d)
        self.distance_m += d

    def sample_speed(self):
        self.spd[self.spd_idx] = self.speed
        self.spd_idx = (self.spd_idx + 1) % CAR_SPD_LEN
        self.spd_count = min(self.spd_count + 1, CAR_SPD_LEN)

    def speed_series_kmh(self):
        n = self.spd_count
        if n < CAR_SPD_LEN:
            raw = self.spd[:n]
        else:
            raw = [self.spd[(self.spd_idx + i) % CAR_SPD_LEN] for i in range(n)]
        return [round(v * 3.6, 1) for v in raw]


class Person(Walker):
    def __init__(self, i, graph, rng, speed_range=PERSON_SPEED_MPS, near=None):
        super().__init__(graph, rng, lateral=0.8, near=near)
        self.id = i
        self.name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        self.shirt = SHIRTS[i % len(SHIRTS)]
        lo, hi = speed_range
        self.speed = lo + rng.random() * (hi - lo)        # m/s
        self.distance_m = 0.0
        self.steps = [0.0] * HISTORY_LEN             # meters walked per 10-min bucket
        self.step_idx = 0

    def prefill(self):
        act = 0.75
        for i in range(HISTORY_LEN):
            act = max(0.45, min(1.0, act + (self.rng.random() - 0.5) * 0.2))
            self.steps[i] = self.speed * 600 * act   # meters per 10-min bucket
        self.steps[self.step_idx] = 0.0

    def move(self, dt):
        d = self.speed * dt
        self.advance(d)
        self.distance_m += d
        self.steps[self.step_idx] += d

    def rotate_bucket(self):
        self.step_idx = (self.step_idx + 1) % HISTORY_LEN
        self.steps[self.step_idx] = 0.0

    def steps_series_per_hour(self, bucket_frac):
        rate = STEPS_PER_M * (60 / SAMPLE_MIN)       # bucket meters -> steps/hour
        vals = [round(self.steps[(self.step_idx + k) % HISTORY_LEN] * rate)
                for k in range(1, HISTORY_LEN)]
        frac = max(0.15, min(1.0, bucket_frac))
        vals.append(round(self.steps[self.step_idx] / frac * rate))
        return vals


class Simulation:
    def __init__(self, cfg=None):
        cfg = cfg or config.load_config()
        self.mode = cfg["world"]
        if self.mode not in WORLD_BUILDERS:
            raise ValueError(f"unknown world {self.mode!r}, expected one of {sorted(WORLD_BUILDERS)}")
        seed = cfg.get("seed", 0)
        self.rng = random.Random(seed)
        self.clock_min = cfg.get("start_hour", 9) * 60.0
        self.last_sample_min = self.clock_min
        self.car_sample_acc = 0.0
        self.sim_min_per_sec = cfg.get("sim_min_per_sec", SIM_MIN_PER_SEC)
        self.tick_interval = 1.0 / cfg.get("tick_hz", TICK_HZ)   # seconds between ticks
        self.world_rev = 0    # bumped on every edit; clients refetch /api/world on change

        spec = config.load_world_spec(self.mode)
        w = self.world_data = WORLD_BUILDERS[self.mode](spec, seed)
        self._car_speed = tuple(w.get("car_speed_mps") or CAR_SPEED_MPS)
        self._person_speed = tuple(w.get("person_speed_mps") or PERSON_SPEED_MPS)
        self.buildings = [Building(b, self.rng) for b in w["buildings"]]
        self.cars = [Car(i, w["car_graph"], self.rng, self._car_speed)
                     for i in range(w["n_cars"])]
        self.people = [Person(i, w["ped_graph"], self.rng, self._person_speed)
                       for i in range(w["n_people"])]
        self._next_car_id = len(self.cars)        # ids stay unique across removals
        self._next_person_id = len(self.people)
        self._next_road_id = len(w["roads"])

        for b in self.buildings:
            b.prefill(self.clock_min)
        for p in self.people:
            p.prefill()
        self.total_load_kw = sum(b.load_kw for b in self.buildings)

    def tick(self, dt):
        """Advance the world by dt real seconds."""
        self.clock_min += dt * self.sim_min_per_sec
        hour = (self.clock_min % 1440) / 60.0

        for c in self.cars:
            c.move(dt)
        for p in self.people:
            p.move(dt)
        self.total_load_kw = sum(b.estimate_load(hour) for b in self.buildings)

        while self.clock_min - self.last_sample_min >= SAMPLE_MIN:
            self.last_sample_min += SAMPLE_MIN
            h = (self.last_sample_min % 1440) / 60.0
            for b in self.buildings:
                b.sample(h)
            for p in self.people:
                p.rotate_bucket()

        self.car_sample_acc += dt
        while self.car_sample_acc >= CAR_SPD_DT:
            self.car_sample_acc -= CAR_SPD_DT
            for c in self.cars:
                c.sample_speed()

    # ---------- edits ----------
    def apply_edit(self, op):
        """Apply one edit command, e.g. {"op": "set_floors", "id": 0, "floors": 5}.

        Handlers mutate both the live objects and world_data so /api/world stays
        in sync. Raises ValueError on bad input (-> HTTP 400). The tick loop and
        request handlers share one asyncio loop, so edits never race a tick.
        """
        kind = op.get("op")
        handler = self._EDIT_OPS.get(kind)
        if handler is None:
            raise ValueError(f"unknown edit op {kind!r}, expected one of {sorted(self._EDIT_OPS)}")
        handler(self, op)
        self.world_rev += 1
        return {"ok": True, "world_rev": self.world_rev}

    @staticmethod
    def _as_int(v):
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @staticmethod
    def _find(seq, eid):
        return next((e for e in seq if e.id == eid), None)

    @staticmethod
    def _spawn_point(op):
        """Optional spawn location {x, y} in meters; None spawns at random."""
        x, y = op.get("x"), op.get("y")
        if x is None and y is None:
            return None
        num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
        if not (num(x) and num(y)):
            raise ValueError("x and y must both be numbers (meters), or both omitted")
        return (float(x), float(y))

    def _edit_set_floors(self, op):
        b = self._find(self.buildings, self._as_int(op.get("id")))
        if b is None:
            raise ValueError(f"unknown building id {op.get('id')!r}")
        floors = self._as_int(op.get("floors"))
        if floors is None or not 1 <= floors <= MAX_FLOORS:
            raise ValueError(f"floors must be an integer in 1..{MAX_FLOORS}")
        b.set_floors(floors)
        self.world_data["buildings"][b.id]["floors"] = floors

    def _edit_spawn_car(self, op):
        if len(self.cars) >= MAX_CARS:
            raise ValueError(f"car limit reached ({MAX_CARS})")
        if not self.world_data["car_graph"]["adj"]:
            raise ValueError("no drivable road to spawn a car on")
        c = Car(self._next_car_id, self.world_data["car_graph"], self.rng,
                self._car_speed, near=self._spawn_point(op))
        self._next_car_id += 1
        self.cars.append(c)

    def _edit_spawn_person(self, op):
        if len(self.people) >= MAX_PEOPLE:
            raise ValueError(f"person limit reached ({MAX_PEOPLE})")
        if not self.world_data["ped_graph"]["adj"]:
            raise ValueError("no walkable road to spawn a person on")
        p = Person(self._next_person_id, self.world_data["ped_graph"], self.rng,
                   self._person_speed, near=self._spawn_point(op))
        p.prefill()
        self._next_person_id += 1
        self.people.append(p)

    def _edit_remove_car(self, op):
        c = self._find(self.cars, self._as_int(op.get("id")))
        if c is None:
            raise ValueError(f"unknown car id {op.get('id')!r}")
        self.cars.remove(c)

    def _edit_remove_person(self, op):
        p = self._find(self.people, self._as_int(op.get("id")))
        if p is None:
            raise ValueError(f"unknown person id {op.get('id')!r}")
        self.people.remove(p)

    def _apply_roads(self, roads):
        """Swap in a new roads list: rebuild graphs, validate, re-seat agents."""
        graphs = grid_world.build_graphs(roads)
        if self.cars and not graphs["car_graph"]["adj"]:
            raise ValueError("cars exist but no drivable road would remain — remove the cars first")
        if self.people and not graphs["ped_graph"]["adj"]:
            raise ValueError("people exist but no walkable road would remain — remove the people first")
        self.world_data["roads"] = roads
        self.world_data["car_graph"] = graphs["car_graph"]
        self.world_data["ped_graph"] = graphs["ped_graph"]
        for c in self.cars:
            c.reseat(graphs["car_graph"])
        for p in self.people:
            p.reseat(graphs["ped_graph"])

    def _edit_add_road(self, op):
        cls = op.get("class", "residential")
        if cls not in osm_world.ROAD_CLASSES:
            raise ValueError(f"unknown road class {cls!r}, "
                             f"expected one of {sorted(osm_world.ROAD_CLASSES)}")
        pts = op.get("points")
        if not (isinstance(pts, list) and 2 <= len(pts) <= 100):
            raise ValueError("points must be a list of 2..100 [x, y] pairs")
        num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
        clean = []
        for p in pts:
            if not (isinstance(p, (list, tuple)) and len(p) == 2
                    and num(p[0]) and num(p[1])
                    and abs(p[0]) < 1e5 and abs(p[1]) < 1e5):
                raise ValueError("each point must be [x, y] in meters")
            clean.append([round(float(p[0]), 1), round(float(p[1]), 1)])
        if all(p == clean[0] for p in clean):
            raise ValueError("road has zero length")
        name = op.get("name", "")
        if not isinstance(name, str) or len(name) > 60:
            raise ValueError("name must be a string of at most 60 chars")
        width, drivable = osm_world.ROAD_CLASSES[cls]
        road = {"id": self._next_road_id, "name": name, "class": cls,
                "width": width, "drivable": drivable, "points": clean}
        self._apply_roads(self.world_data["roads"] + [road])
        self._next_road_id += 1

    def _edit_remove_road(self, op):
        rid = self._as_int(op.get("id"))
        roads = [r for r in self.world_data["roads"] if r["id"] != rid]
        if len(roads) == len(self.world_data["roads"]):
            raise ValueError(f"unknown road id {op.get('id')!r}")
        self._apply_roads(roads)

    _EDIT_OPS = {
        "set_floors": _edit_set_floors,
        "spawn_car": _edit_spawn_car,
        "spawn_person": _edit_spawn_person,
        "remove_car": _edit_remove_car,
        "remove_person": _edit_remove_person,
        "add_road": _edit_add_road,
        "remove_road": _edit_remove_road,
    }

    # ---------- API snapshots ----------
    def world(self):
        """Static layout for the frontend (graphs stay server-side)."""
        w = self.world_data
        return {
            "mode": self.mode,
            "world_rev": self.world_rev,
            "name": w["name"],
            "radius_m": w["radius_m"],
            "buildings": [{
                "id": b["id"], "name": b["name"], "type": b["type"],
                "floors": b["floors"], "polygon": b["polygon"], "center": b["center"],
            } for b in w["buildings"]],
            "roads": w["roads"],
            "parks": w["parks"],
            "water": w["water"],
            "lamps": w["lamps"],
            "signals": w["signals"],
        }

    def state(self):
        return {
            "world_rev": self.world_rev,
            "clock_min": round(self.clock_min, 2),
            "total_load_kw": round(self.total_load_kw),
            "cars": [{
                "id": c.id, "name": c.name, "color": c.color,
                "x": round(c.pos()[0], 2), "y": round(c.pos()[1], 2),
                "hx": round(c.ux, 3), "hy": round(c.uy, 3),
                "speed_kmh": round(c.speed * 3.6, 1),
            } for c in self.cars],
            "people": [{
                "id": p.id, "name": p.name, "shirt": p.shirt,
                "x": round(p.pos()[0], 2), "y": round(p.pos()[1], 2),
            } for p in self.people],
        }

    def building_detail(self, i):
        b = self._find(self.buildings, i)
        if b is None:
            return None
        return {
            "id": b.id, "name": b.name, "type": b.type,
            "floors": b.floors, "area_m2": b.area_m2,
            "load_kw": round(b.load_kw, 1),
            "occupancy": round(b.occupancy((self.clock_min % 1440) / 60.0), 2),
            "sample_min": SAMPLE_MIN,
            "history_kw": b.history_series(),
        }

    def car_detail(self, i):
        c = self._find(self.cars, i)
        if c is None:
            return None
        return {
            "id": c.id, "name": c.name, "color": c.color,
            "speed_kmh": round(c.speed * 3.6, 1),
            "distance_km_today": round(c.distance_m / 1000, 2),
            "sample_dt_s": CAR_SPD_DT,
            "capacity": CAR_SPD_LEN,
            "history_kmh": c.speed_series_kmh(),
        }

    def person_detail(self, i):
        p = self._find(self.people, i)
        if p is None:
            return None
        bucket_frac = (self.clock_min - self.last_sample_min) / SAMPLE_MIN
        series = p.steps_series_per_hour(bucket_frac)
        return {
            "id": p.id, "name": p.name,
            "activity": "Walking",
            "steps_per_h": series[-1],
            "distance_km_today": round(p.distance_m / 1000, 2),
            "sample_min": SAMPLE_MIN,
            "history_steps_h": series,
        }
