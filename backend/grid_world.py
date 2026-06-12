"""Build the grid-city test world from the spec dict loaded from input/grid.json.

The spec defines everything (no geometry in code): buildings (name, type,
floors, polygon), roads (name, class, polyline points in meters), lamps,
signals and agent counts. Road width/drivability follow the same class table
as the OSM world; road points with equal coordinates are merged into one
graph node, so crossing roads connect.

Run standalone to check the data:  python -m backend.grid_world
"""
from .osm_world import ROAD_CLASSES, centroid, shoelace_area


def build_graphs(roads):
    """Car/ped graphs from road polylines (any world).

    Points with equal coordinates (rounded to 0.1 m) merge into one node, so
    roads that share an endpoint or cross at a common point connect. Used both
    at build time and to rebuild after road edits.
    """
    car_adj, ped_adj, nodes = {}, {}, {}
    coord_to_id = {}      # (x, y) -> integer node id (tuples can't be node ids)

    def node_id(p):
        key = (round(p[0], 1), round(p[1], 1))
        if key not in coord_to_id:
            coord_to_id[key] = len(coord_to_id)
            nodes[coord_to_id[key]] = (float(p[0]), float(p[1]))
        return coord_to_id[key]

    for r in roads:
        ids = [node_id(p) for p in r["points"]]
        for a, b in zip(ids, ids[1:]):
            if a == b:
                continue              # zero-length segment
            if r["drivable"]:
                car_adj.setdefault(a, []).append((b, r["width"]))
                car_adj.setdefault(b, []).append((a, r["width"]))
            if r["class"] != "steps":
                ped_adj.setdefault(a, []).append(b)
                ped_adj.setdefault(b, []).append(a)
    return {"car_graph": {"nodes": nodes, "adj": car_adj},
            "ped_graph": {"nodes": nodes, "adj": ped_adj}}


def build_world(spec, seed=0):
    buildings = []
    for i, b in enumerate(spec.get("buildings", [])):
        poly = [[float(x), float(y)] for x, y in b["polygon"]]
        buildings.append({
            "id": i,
            "name": b["name"],
            "type": b["type"],
            "floors": b["floors"],
            "polygon": poly,
            "area_m2": round(shoelace_area(poly)),
            "center": [round(v, 1) for v in centroid(poly)],
        })

    roads = []
    for i, r in enumerate(spec.get("roads", [])):
        cls = r.get("class", "residential")
        if cls not in ROAD_CLASSES:
            raise ValueError(f"input/grid.json: unknown road class {cls!r}, "
                             f"expected one of {sorted(ROAD_CLASSES)}")
        width, drivable = ROAD_CLASSES[cls]
        roads.append({
            "id": i,
            "name": r.get("name", ""),
            "class": cls, "width": width, "drivable": drivable,
            "points": [[float(x), float(y)] for x, y in r["points"]],
        })
    graphs = build_graphs(roads)

    if spec["n_cars"] > 0 and not graphs["car_graph"]["adj"]:
        raise ValueError("input/grid.json: n_cars > 0 needs at least one drivable road")
    if spec["n_people"] > 0 and not graphs["ped_graph"]["adj"]:
        raise ValueError("input/grid.json: n_people > 0 needs at least one walkable road")

    return {
        "name": spec["name"],
        "radius_m": spec["radius_m"],
        "n_cars": spec["n_cars"],
        "n_people": spec["n_people"],
        "car_speed_mps": spec.get("car_speed_mps"),
        "person_speed_mps": spec.get("person_speed_mps"),
        "buildings": buildings,
        "roads": roads,
        "parks": spec.get("parks", []),
        "water": spec.get("water", []),
        "lamps": [[float(x), float(y)] for x, y in spec.get("lamps", [])],
        "signals": spec.get("signals", []),
        "car_graph": graphs["car_graph"],
        "ped_graph": graphs["ped_graph"],
    }


if __name__ == "__main__":
    from .config import load_world_spec
    w = build_world(load_world_spec("grid"))
    print(f"area: {w['name']}, radius {w['radius_m']} m")
    print(f"buildings: {len(w['buildings'])}, roads: {len(w['roads'])}, "
          f"lamps: {len(w['lamps'])}, signals: {len(w['signals'])}")
    print(f"car graph: {len(w['car_graph']['adj'])} nodes, "
          f"ped graph: {len(w['ped_graph']['adj'])} nodes")
    print(f"agents: {w['n_cars']} cars, {w['n_people']} people")
