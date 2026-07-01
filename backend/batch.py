"""Headless batch runner — city energy results as files, no server, no browser.

Builds the world from input/ exactly like the live app (OSM fetch is cached the
same way), evaluates every building over the deterministic design day used by
the retrofit engine (backend/scenario.py), and writes results for downstream
tools. No agents, no live weather, no tick loop — just the pure energy model.

    python -m backend.batch                          # baseline CSV + GeoJSON
    python -m backend.batch --measure u_wall=0.7 --measure cop=1.3
    python -m backend.batch --scenario myplan.json --out results/
    python -m backend.batch --list-measures

Outputs (in --out, default output/):
    buildings.csv           per-building baseline day: energy breakdown, CO2, PV,
                            peak kW, annualised EUI
    buildings.geojson       building footprints in WGS84 with the same metrics as
                            properties — drop straight into QGIS/ArcGIS/kepler.gl
                            (map worlds only; the grid world has no geo-reference)
    scenario.json           full before/after comparison (when measures are given)
    scenario_buildings.csv  per-building before/after/delta (when measures are given)

A scenario file is the same JSON body as POST /api/scenario:
    {"measures": {"u_wall": 0.7, "cop": 1.3}, "target": {"types": ["res"]}, "tariff": 0.28}
--measure / --target-* / --tariff flags merge over (and win against) the file.
"""
import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

from . import config, energy, scenario
from .simulation import WORLD_BUILDERS, Building

BASELINE_COLS = ["id", "name", "type", "floors", "area_m2",
                 "energy_kwh_day", "hvac_kwh_day", "elec_kwh_day", "light_kwh_day",
                 "pv_kwh_day", "net_kwh_day", "co2_kg_day", "peak_kw", "eui_kwh_m2_yr"]

SCENARIO_COLS = ["id", "name", "type", "floors", "area_m2", "in_scope",
                 "baseline_energy_kwh_day", "retrofit_energy_kwh_day", "delta_pct",
                 "baseline_co2_kg_day", "retrofit_co2_kg_day",
                 "baseline_pv_kwh_day", "retrofit_pv_kwh_day",
                 "baseline_eui_kwh_m2_yr", "retrofit_eui_kwh_m2_yr"]


def build_buildings(cfg):
    """World name, spec, and Building objects from input/ — no agents, no weather."""
    mode = cfg["world"]
    seed = cfg.get("seed", 0)
    spec = config.load_world_spec(mode)
    w = WORLD_BUILDERS[mode](spec, seed)
    rng = random.Random(seed)
    return w, spec, [Building(b, rng) for b in w["buildings"]]


def baseline_rows(buildings):
    """Per-building design-day evaluation under baseline (unretrofitted) params."""
    rows = []
    for b in buildings:
        r = scenario.evaluate_building(b, energy.base_params(b.type))
        rows.append({
            "id": b.id, "name": b.name, "type": b.type,
            "floors": b.floors, "area_m2": b.area_m2,
            "energy_kwh_day": round(r["energy_kwh"], 1),
            "hvac_kwh_day": round(r["hvac_kwh"], 1),
            "elec_kwh_day": round(r["elec_kwh"], 1),
            "light_kwh_day": round(r["light_kwh"], 1),
            "pv_kwh_day": round(r["pv_kwh"], 1),
            "net_kwh_day": round(r["net_kwh"], 1),
            "co2_kg_day": round(r["co2_kg"], 1),
            "peak_kw": round(r["peak_kw"], 1),
            "eui_kwh_m2_yr": round(r["eui_kwh_m2_yr"], 1),
        })
    return rows


def write_csv(path, cols, rows):
    # utf-8-sig prepends a BOM so Excel reads non-ASCII building names correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def unproject(center):
    """Inverse of osm_world.project: local meters (x-east, y-south) -> [lon, lat]."""
    lat0, lon0 = center
    m_per_deg_lon = 111320 * math.cos(math.radians(lat0))

    def _to_lonlat(x, y):
        return [round(lon0 + x / m_per_deg_lon, 7), round(lat0 - y / 110540, 7)]
    return _to_lonlat


def write_geojson(path, world, center, props_by_id):
    """Building footprints as a WGS84 FeatureCollection with result properties."""
    to_lonlat = unproject(center)
    features = []
    for b in world["buildings"]:
        ring = [to_lonlat(x, y) for x, y in b["polygon"]]
        ring.append(ring[0])                      # GeoJSON rings must close
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": props_by_id[b["id"]],
        })
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                    encoding="utf-8")


def merge_scenario_args(args):
    """Scenario request from --scenario file + CLI flags (flags win)."""
    body = {}
    if args.scenario:
        body = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            raise ValueError(f"{args.scenario}: scenario file must be a JSON object")
    measures = dict(body.get("measures") or {})
    for m in args.measure:
        key, _, val = m.partition("=")
        if not _:
            raise ValueError(f"--measure {m!r}: expected key=value")
        try:
            measures[key] = float(val)
        except ValueError:
            raise ValueError(f"--measure {m!r}: value must be a number")
    target = body.get("target")
    if args.target_types or args.target_ids:
        target = {}
        if args.target_types:
            target["types"] = [t.strip() for t in args.target_types.split(",") if t.strip()]
        if args.target_ids:
            target["ids"] = [int(i) for i in args.target_ids.split(",") if i.strip()]
    tariff = args.tariff if args.tariff is not None else body.get("tariff")
    return measures, target, tariff


def print_measures():
    print("City-wide retrofit measures (multiplier on the baseline value; 1.0 = no-op):")
    for key, (label, _) in scenario.MULTIPLIER_MEASURES.items():
        print(f"  {key:<12} {label}")
    print(f"  {'cop':<12} Heat pump / chiller COP (one factor scales both)")
    print("Setpoint measures (degrees C added to the setpoint):")
    for key in scenario.SETPOINT_MEASURES:
        print(f"  {key:<12} {'heating setback (negative saves)' if 'heat' in key else 'cooling setup (positive saves)'}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m backend.batch",
        description="Headless city energy run: baseline + optional retrofit scenario, "
                    "written as CSV/GeoJSON/JSON. World and locale come from input/.")
    ap.add_argument("--out", default="output", help="output directory (default: output/)")
    ap.add_argument("--scenario", help="JSON file with {measures, target, tariff} "
                                       "(same body as POST /api/scenario)")
    ap.add_argument("--measure", action="append", default=[], metavar="KEY=VALUE",
                    help="one retrofit measure, e.g. u_wall=0.7 (repeatable)")
    ap.add_argument("--target-types", metavar="T1,T2",
                    help="restrict measures to building types, e.g. res,office")
    ap.add_argument("--target-ids", metavar="I1,I2",
                    help="restrict measures to building ids, e.g. 3,17,42")
    ap.add_argument("--tariff", type=float, help="electricity price per kWh for payback")
    ap.add_argument("--list-measures", action="store_true",
                    help="list available measure keys and exit")
    args = ap.parse_args(argv)

    if args.list_measures:
        print_measures()
        return 0

    measures, target, tariff = merge_scenario_args(args)

    cfg = config.load_config()
    print(f"building world '{cfg['world']}' from input/ ...")
    world, spec, buildings = build_buildings(cfg)
    print(f"  {world['name']}: {len(buildings)} buildings")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # ---- baseline: per-building design day ----
    rows = baseline_rows(buildings)
    write_csv(out / "buildings.csv", BASELINE_COLS, rows)
    total_kwh = sum(r["energy_kwh_day"] for r in rows)
    total_co2 = sum(r["co2_kg_day"] for r in rows)
    total_pv = sum(r["pv_kwh_day"] for r in rows)
    floor_m2 = sum(max(1.0, b.area_m2 * b.floors) for b in buildings)
    print(f"  baseline day: {total_kwh:,.0f} kWh, {total_co2:,.0f} kg CO2, "
          f"{total_pv:,.0f} kWh PV, city EUI "
          f"{total_kwh * scenario.DAYS_PER_YEAR / floor_m2:,.0f} kWh/m2/yr")
    print(f"wrote {out / 'buildings.csv'}")

    props_by_id = {r["id"]: dict(r) for r in rows}

    # ---- optional retrofit scenario ----
    if measures:
        result = scenario.compare(buildings, measures, target, tariff)
        (out / "scenario.json").write_text(json.dumps(result, indent=2),
                                           encoding="utf-8")
        scen_rows = []
        for r in result["buildings"]:
            b, a = r["baseline"], r["retrofit"]
            scen_rows.append({
                "id": r["id"], "name": r["name"], "type": r["type"],
                "floors": r["floors"], "area_m2": r["area_m2"], "in_scope": r["in_scope"],
                "baseline_energy_kwh_day": b["energy_kwh"],
                "retrofit_energy_kwh_day": a["energy_kwh"],
                "delta_pct": r["delta_pct"],
                "baseline_co2_kg_day": b["co2_kg"], "retrofit_co2_kg_day": a["co2_kg"],
                "baseline_pv_kwh_day": b["pv_kwh"], "retrofit_pv_kwh_day": a["pv_kwh"],
                "baseline_eui_kwh_m2_yr": b["eui_kwh_m2_yr"],
                "retrofit_eui_kwh_m2_yr": a["eui_kwh_m2_yr"],
            })
            p = props_by_id[r["id"]]
            p["in_scope"] = r["in_scope"]
            p["retrofit_energy_kwh_day"] = a["energy_kwh"]
            p["retrofit_eui_kwh_m2_yr"] = a["eui_kwh_m2_yr"]
            p["retrofit_co2_kg_day"] = a["co2_kg"]
            p["delta_pct"] = r["delta_pct"]
        write_csv(out / "scenario_buildings.csv", SCENARIO_COLS, scen_rows)
        c = result["cost"]
        d = result["delta"]["energy_kwh"]
        print(f"  scenario ({result['n_in_scope']}/{result['n_buildings']} buildings in scope): "
              f"energy {d['pct']:+.1f}%, capex {c['capex']:,.0f}, "
              f"saves {c['annual_savings']:,.0f}/yr"
              + (f", payback {c['payback_years']:.1f} yr"
                 if c["payback_years"] is not None else ""))
        print(f"wrote {out / 'scenario.json'}")
        print(f"wrote {out / 'scenario_buildings.csv'}")

    # ---- GeoJSON (map worlds only: the grid world has no geo-reference) ----
    if cfg["world"] == "map" and "center" in spec:
        write_geojson(out / "buildings.geojson", world, tuple(spec["center"]), props_by_id)
        print(f"wrote {out / 'buildings.geojson'}")
    else:
        print("skipping buildings.geojson: grid world has no lat/lon reference")
    return 0


if __name__ == "__main__":
    sys.exit(main())
