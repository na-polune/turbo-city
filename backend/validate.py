"""Archetype validation — model EUI vs published building-stock benchmarks.

Runs one reference building per archetype through the annual engine
(backend/annual.py) and compares its energy-use intensity against published
UK stock benchmarks, so the model's absolute numbers carry an evidence trail
instead of "plausible defaults".

    python -m backend.validate                     # synthetic year
    python -m backend.validate --weather city.epw  # a real TMY (use a UK file
                                                   # for like-for-like vs UK benchmarks)
    python -m backend.validate --csv validation.csv

Benchmark basis and honesty notes (also printed with the results):
  - Benchmarks are CIBSE TM46 (2008) category medians (kWh/m² GIA per year,
    delivered electricity + delivered fossil fuel), except 'res' which uses a
    typical UK dwelling from ECUK-style stock figures (TM46 is non-domestic).
  - The model city is all-electric with heat-pump heating, so the fossil
    benchmark is converted to equivalent electricity:
        equivalent = elec + fossil x BOILER_EFF / COP_HEAT
    (useful heat from a gas boiler, re-delivered by the model's heat pump).
  - The model has NO domestic hot water; benchmarks include it. Expect the
    model to sit LOW on that account, most visibly for res and hospital.
  - Schedules repeat one deterministic day 365x (no weekends/holidays).
  - Deviations within roughly +/-30% are what this class of reduced model can
    honestly claim. Use per-building overrides (backend/overrides.py) to
    calibrate against measured data where it exists.
"""
import argparse
import csv
import random
import sys

from . import annual, energy
from .simulation import Building

BOILER_EFF = 0.85    # useful heat per delivered fossil kWh in the benchmark stock

# type -> (elec kWh/m2/yr, fossil kWh/m2/yr, source label)
BENCHMARKS = {
    "res":        (35.0, 110.0, "typical UK dwelling (ECUK-style stock figure)"),
    "office":     (95.0, 120.0, "CIBSE TM46 'General office'"),
    "shop":       (165.0, 0.0,  "CIBSE TM46 'General retail'"),
    "hospital":   (90.0, 420.0, "CIBSE TM46 'Hospital: clinical and research'"),
    "school":     (40.0, 150.0, "CIBSE TM46 'Schools and seasonal public buildings'"),
    "industrial": (35.0, 180.0, "CIBSE TM46 'Workshop' (indicative; sector varies widely)"),
}

# reference geometry per archetype: (footprint m2, floors)
REFERENCE = {
    "res":        (200, 2),
    "office":     (800, 4),
    "shop":       (400, 1),
    "hospital":   (2500, 4),
    "school":     (1200, 2),
    "industrial": (1500, 1),
}


def reference_building(btype, i):
    """A synthetic archetype building (square footprint, isotropic facades)."""
    area, floors = REFERENCE[btype]
    return Building({"id": i, "name": f"ref-{btype}", "type": btype,
                     "floors": floors, "area_m2": area, "center": [0, 0]},
                    random.Random(0))


def run(weather):
    rows = []
    for i, btype in enumerate(energy.BUILDING_TYPES):
        b = reference_building(btype, i)
        p = energy.base_params(btype)
        r = annual.run_building(b, p, weather)
        elec, fossil, source = BENCHMARKS[btype]
        equivalent = elec + fossil * BOILER_EFF / p.cop_heat
        model = r["eui_kwh_m2_yr"]
        rows.append({
            "type": btype,
            "area_m2": REFERENCE[btype][0], "floors": REFERENCE[btype][1],
            "model_eui": round(model, 1),
            "bench_elec": elec, "bench_fossil": fossil,
            "bench_equivalent": round(equivalent, 1),
            "deviation_pct": round((model - equivalent) / equivalent * 100.0, 1),
            "source": source,
        })
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m backend.validate",
        description="Compare per-archetype annual EUI against published benchmarks.")
    ap.add_argument("--weather", metavar="FILE.EPW",
                    help="EPW/TMY weather year (default: synthetic year)")
    ap.add_argument("--csv", metavar="FILE.CSV", help="also write the table as CSV")
    args = ap.parse_args(argv)

    if args.weather:
        wx_name, wx = annual.read_epw(args.weather)
    else:
        wx_name, wx = annual.synthetic_year()
    print(f"weather basis: {wx_name}")
    print(f"comparison basis: benchmark elec + fossil x {BOILER_EFF} / COP "
          f"{energy.COP_HEAT:g} (all-electric heat-pump equivalent)\n")

    rows = run(wx)
    hdr = f"{'type':<11} {'model EUI':>10} {'bench elec':>11} {'bench fossil':>13} " \
          f"{'HP-equiv':>9} {'deviation':>10}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['type']:<11} {r['model_eui']:>10.1f} {r['bench_elec']:>11.0f} "
              f"{r['bench_fossil']:>13.0f} {r['bench_equivalent']:>9.1f} "
              f"{r['deviation_pct']:>+9.1f}%")
    print("\n(all values kWh/m2/yr; benchmark sources:)")
    for r in rows:
        print(f"  {r['type']:<11} {r['source']}")
    print("\ncaveats: model has no DHW (benchmarks include it, expect low bias); "
          "one schedule day repeated 365x;\nbenchmarks are UK stock medians — "
          "run with a UK EPW for like-for-like climate.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
