"""City simulation core (no web code) on a real OSM street network.

World geometry comes from backend.osm_world (Cambridge, Market Square).
Agents random-walk the street graph (edge to edge, avoid reversing) —
same design as the original toy version, just on real geometry in meters.
"""
import math
import random

from .osm_world import build_world

# ---- time ----
SIM_MIN_PER_SEC = 1.0     # 1 real second = 1 sim minute (full day in 24 real minutes)
SAMPLE_MIN = 10           # energy / pedometer sample every N sim minutes
HISTORY_LEN = 144         # 24 h * 6 samples/h

# ---- telemetry ----
CAR_SPD_LEN = 120         # speed ring buffer
CAR_SPD_DT = 0.5          # sample every 0.5 real seconds (60 s window)
STEPS_PER_M = 1.35        # pedometer scale

N_CARS = 8
N_PEOPLE = 15

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


class Building:
    def __init__(self, data, rng):
        self.rng = rng
        self.id = data["id"]
        self.name = data["name"]
        self.type = data["type"]
        self.floors = data["floors"]
        self.area_m2 = data["area_m2"]
        self.center = data["center"]
        tiles = self.area_m2 / TILE_M2
        self.base = 2 + self.floors * 1.4 * tiles
        self.peak = self.floors * PEAK_COEF[self.type] * tiles
        self.noise = 0.0
        self.load_kw = 0.0
        self.history = [0.0] * HISTORY_LEN
        self.hist_idx = 0

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

    def __init__(self, graph, rng, lateral=0.0):
        self.nodes = graph["nodes"]
        self.adj = graph["adj"]
        self.rng = rng
        self.lateral = lateral          # right-hand offset from the centerline, meters
        start = rng.choice(largest_component(self.adj))
        self.prev = start
        self._set_edge(start, rng.choice(self.adj[start]))

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
    def __init__(self, i, graph, rng):
        super().__init__(graph, rng, lateral=1.5)
        self.id = i
        self.name = f"{CAR_NAMES[i % len(CAR_NAMES)]} {i + 1}"
        self.color = CAR_COLORS[i % len(CAR_COLORS)]
        self.base_speed = 6.0 + rng.random() * 3.0   # m/s
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
    def __init__(self, i, graph, rng):
        super().__init__(graph, rng, lateral=0.8)
        self.id = i
        self.name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        self.shirt = SHIRTS[i % len(SHIRTS)]
        self.speed = 1.1 + rng.random() * 0.6        # m/s
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
    def __init__(self, seed=20260612):
        self.rng = random.Random(seed)
        self.clock_min = 9 * 60.0      # start at 09:00
        self.last_sample_min = self.clock_min
        self.car_sample_acc = 0.0

        self.world_data = build_world(seed)
        self.buildings = [Building(b, self.rng) for b in self.world_data["buildings"]]
        self.cars = [Car(i, self.world_data["car_graph"], self.rng) for i in range(N_CARS)]
        self.people = [Person(i, self.world_data["ped_graph"], self.rng) for i in range(N_PEOPLE)]

        for b in self.buildings:
            b.prefill(self.clock_min)
        for p in self.people:
            p.prefill()
        self.total_load_kw = sum(b.load_kw for b in self.buildings)

    def tick(self, dt):
        """Advance the world by dt real seconds."""
        self.clock_min += dt * SIM_MIN_PER_SEC
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

    # ---------- API snapshots ----------
    def world(self):
        """Static layout for the frontend (graphs stay server-side)."""
        w = self.world_data
        return {
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
        b = self.buildings[i]
        return {
            "id": b.id, "name": b.name, "type": b.type,
            "floors": b.floors, "area_m2": b.area_m2,
            "load_kw": round(b.load_kw, 1),
            "occupancy": round(b.occupancy((self.clock_min % 1440) / 60.0), 2),
            "sample_min": SAMPLE_MIN,
            "history_kw": b.history_series(),
        }

    def car_detail(self, i):
        c = self.cars[i]
        return {
            "id": c.id, "name": c.name, "color": c.color,
            "speed_kmh": round(c.speed * 3.6, 1),
            "distance_km_today": round(c.distance_m / 1000, 2),
            "sample_dt_s": CAR_SPD_DT,
            "capacity": CAR_SPD_LEN,
            "history_kmh": c.speed_series_kmh(),
        }

    def person_detail(self, i):
        p = self.people[i]
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
