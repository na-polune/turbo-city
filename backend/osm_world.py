"""Load a real area from OpenStreetMap and convert it to simulation world data.

The area (name, center, radius, cache file, agent counts) comes from the spec
dict loaded from input/map.json — see backend.config. Queries the Overpass API
directly (stdlib only, no osmnx/geopandas) and caches the raw response in
backend/data/ so the network is hit only once.

Run standalone to check the data:  python -m backend.osm_world
"""
import json
import math
import random
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# road class -> (width m, drivable)
ROAD_CLASSES = {
    "primary": (9, True), "primary_link": (8, True),
    "secondary": (8, True), "secondary_link": (7, True),
    "tertiary": (7, True), "tertiary_link": (6, True),
    "residential": (6, True), "unclassified": (6, True),
    "living_street": (5, True), "service": (4, True),
    "pedestrian": (4, False), "footway": (2.5, False),
    "path": (2.5, False), "cycleway": (2.5, False), "steps": (2.5, False),
}

# name generation for unnamed buildings (from the design reference)
BLD_PRE = ['Maple', 'Cedar', 'Willow', 'Aspen', 'Lotus', 'Harbor', 'Summit', 'Granite',
           'Juniper', 'Magnolia', 'Quartz', 'Meridian', 'Crescent', 'Orchid', 'Bamboo',
           'Amber', 'Cobalt', 'Sterling', 'Pearl', 'Linden']
BLD_SUF = {
    'res': ['Apartments', 'Residences', 'Court', 'Heights', 'Terrace', 'House'],
    'office': ['Tower', 'Works', 'Labs', 'Centre', 'Exchange', 'Chambers'],
    'shop': ['Mart', 'Market', 'Café', 'Books', 'Bakery', 'Studio'],
}
RES_TAGS = {'residential', 'house', 'apartments', 'dormitory', 'terrace', 'semidetached_house', 'detached'}
SHOP_TAGS = {'retail', 'commercial', 'supermarket', 'kiosk'}


def fetch_overpass(center, radius_m):
    lat, lon = center
    around = f"(around:{radius_m},{lat},{lon})"
    query = f"""
[out:json][timeout:60];
(
  way[building]{around};
  way[highway]{around};
  node[highway=street_lamp]{around};
  node[highway=traffic_signals]{around};
  way[leisure~"^(park|garden|common|recreation_ground)$"]{around};
  way[natural=water]{around};
  way[landuse~"^(grass|meadow)$"]{around};
);
out body;
>;
out skel qt;
"""
    req = urllib.request.Request(
        OVERPASS_URL, data=query.encode(),
        headers={"User-Agent": "city-energy-analysis-demo/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def load_raw(spec):
    cache = DATA_DIR / spec["cache_file"]
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = fetch_overpass(spec["center"], spec["radius_m"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def project(lat, lon, center):
    """lat/lon -> local meters; y grows southward so the iso view reads naturally."""
    lat0, lon0 = center
    x = (lon - lon0) * 111320 * math.cos(math.radians(lat0))
    y = (lat0 - lat) * 110540
    return x, y


def shoelace_area(poly):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def centroid(poly):
    n = len(poly)
    return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)


def classify_building(tags):
    b = tags.get("building", "yes")
    if b in RES_TAGS:
        return "res"
    if b in SHOP_TAGS or "shop" in tags:
        return "shop"
    return "office"


def building_name(tags, btype, rng):
    name = tags.get("name")
    if name:
        return name
    street = tags.get("addr:street")
    num = tags.get("addr:housenumber")
    if street and num:
        return f"{num} {street}"
    return rng.choice(BLD_PRE) + " " + rng.choice(BLD_SUF[btype])


def default_floors(btype, tags, rng):
    levels = tags.get("building:levels")
    if levels:
        try:
            return max(1, min(12, round(float(levels))))
        except ValueError:
            pass
    return {"res": rng.randint(2, 3), "shop": rng.randint(1, 2),
            "office": rng.randint(3, 5)}[btype]


def build_world(spec, seed=0):
    """Parse cached/downloaded OSM data into simulation-ready structures."""
    rng = random.Random(seed)
    raw = load_raw(spec)
    center = tuple(spec["center"])
    nodes = {}        # osm node id -> (x, y)
    node_tags = {}    # osm node id -> tags
    ways = []
    for el in raw["elements"]:
        if el["type"] == "node":
            nodes[el["id"]] = project(el["lat"], el["lon"], center)
            if el.get("tags"):
                node_tags[el["id"]] = el["tags"]
        elif el["type"] == "way":
            ways.append(el)

    buildings, roads, parks, water = [], [], [], []
    car_adj, ped_adj = {}, {}
    graph_nodes = {}  # osm node id -> (x, y), nodes used by any road

    def add_edge(adj, a, b, width=None):
        # car graph keeps the road width per edge (speed varies by road class)
        ea = (b, width) if width is not None else b
        eb = (a, width) if width is not None else a
        adj.setdefault(a, []).append(ea)
        adj.setdefault(b, []).append(eb)

    for w in sorted(ways, key=lambda w: w["id"]):
        tags = w.get("tags", {})
        pts = [nodes[n] for n in w["nodes"] if n in nodes]
        if len(pts) < 2:
            continue

        if "building" in tags:
            poly = pts[:-1] if w["nodes"][0] == w["nodes"][-1] else pts
            if len(poly) < 3:
                continue
            area = shoelace_area(poly)
            if area < 20:
                continue
            btype = classify_building(tags)
            buildings.append({
                "id": len(buildings),
                "name": building_name(tags, btype, rng),
                "type": btype,
                "floors": default_floors(btype, tags, rng),
                "polygon": [[round(x, 1), round(y, 1)] for x, y in poly],
                "area_m2": round(area),
                "center": [round(v, 1) for v in centroid(poly)],
            })
        elif "highway" in tags:
            cls = tags["highway"]
            if cls not in ROAD_CLASSES:
                continue
            width, drivable = ROAD_CLASSES[cls]
            roads.append({
                "id": len(roads),
                "name": tags.get("name", ""),
                "class": cls, "width": width, "drivable": drivable,
                "points": [[round(x, 1), round(y, 1)] for x, y in pts],
            })
            ids = [n for n in w["nodes"] if n in nodes]
            for n in ids:
                graph_nodes[n] = nodes[n]
            for a, b in zip(ids, ids[1:]):
                if drivable:
                    add_edge(car_adj, a, b, width)
                if cls != "steps":
                    add_edge(ped_adj, a, b)
        elif tags.get("natural") == "water":
            water.append([[round(x, 1), round(y, 1)] for x, y in pts])
        elif "leisure" in tags or "landuse" in tags:
            parks.append([[round(x, 1), round(y, 1)] for x, y in pts])

    lamps = [list(map(lambda v: round(v, 1), nodes[nid]))
             for nid, t in node_tags.items() if t.get("highway") == "street_lamp"]
    signals = [{"x": round(nodes[nid][0], 1), "y": round(nodes[nid][1], 1),
                "phase_offset": round(rng.random() * 23, 1)}
               for nid, t in node_tags.items() if t.get("highway") == "traffic_signals"]

    # sparse lamp coverage in OSM -> synthesize along drivable roads every ~30 m
    if len(lamps) < 15:
        lamps = synthesize_lamps(roads, spacing=30)

    return {
        "name": spec["name"],
        "radius_m": spec["radius_m"],
        "n_cars": spec["n_cars"],
        "n_people": spec["n_people"],
        "car_speed_mps": spec.get("car_speed_mps"),
        "person_speed_mps": spec.get("person_speed_mps"),
        "buildings": buildings,
        "roads": roads,
        "parks": parks,
        "water": water,
        "lamps": lamps,
        "signals": signals,
        "car_graph": {"nodes": graph_nodes, "adj": car_adj},
        "ped_graph": {"nodes": graph_nodes, "adj": ped_adj},
    }


def synthesize_lamps(roads, spacing=30):
    lamps = []
    side = 1
    for r in roads:
        if not r["drivable"]:
            continue
        acc = spacing / 2
        pts = r["points"]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            seg = math.hypot(x2 - x1, y2 - y1)
            if seg < 1e-6:
                continue
            ux, uy = (x2 - x1) / seg, (y2 - y1) / seg
            d = acc
            while d < seg:
                off = (r["width"] / 2 + 1) * side
                lamps.append([round(x1 + ux * d - uy * off, 1),
                              round(y1 + uy * d + ux * off, 1)])
                side = -side
                d += spacing
            acc = d - seg
    return lamps


if __name__ == "__main__":
    from .config import load_world_spec
    spec = load_world_spec("map")
    cached = (DATA_DIR / spec["cache_file"]).exists()
    w = build_world(spec)
    print(f"source: {'cache' if cached else 'overpass download'} ({spec['cache_file']})")
    print(f"area: {w['name']}, radius {w['radius_m']} m")
    print(f"buildings: {len(w['buildings'])}")
    print(f"roads: {len(w['roads'])} "
          f"(drivable {sum(1 for r in w['roads'] if r['drivable'])})")
    print(f"car graph: {len(w['car_graph']['adj'])} nodes")
    print(f"ped graph: {len(w['ped_graph']['adj'])} nodes")
    print(f"lamps: {len(w['lamps'])}, signals: {len(w['signals'])}")
    print(f"parks: {len(w['parks'])}, water: {len(w['water'])}")
    named = [b["name"] for b in w["buildings"]][:8]
    print("sample buildings:", ", ".join(named))
