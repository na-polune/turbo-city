const _lerp = (a, b, t) => a + (b - a) * t;
const _clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;

export const appState = {
  world: null,
  cur: null,
  prev: null,
  activeView: null,     // active Info-View id (null = no overlay)
  activeTab: 'e_total', // active tab within a tabbed view (Energy)
  viewMap: {},          // building id -> live per-building scalars (from /api/state)
  viewNorm: {},         // building id -> normalised value for the active view
  viewLegend: null,     // { lo, hi, unit, ramp, detail?, stats? } for the active view
  scenarioMap: {},      // building id -> { norm: -1..1, in_scope } (retrofit view)
  scenarioMeta: null,
  heatMap: {},          // building id -> { severity: 0..1, peak_t_in_c, overheat_hours }
  heatMeta: null,       // { lo, hi, unit, detail, stats } for the overheating view
  dirty: true,          // request a redraw (render loop idles when paused + clean)
  lastInteract: 0,      // performance.now() of last pointer/wheel input
  style: {              // render style (persisted by ui/style.js)
    ground: 'stylized', // 'stylized' | 'hillshade' | 'map' | 'satellite'
    relief: true,       // lift features to terrain height (non-stylized modes)
    detail: 'auto',     // LOD: 'auto' | 'low' | 'high'
  },
  tool: null,
  bldgType: 'res',
  openKind: null,
  openId: null,
  sliderDragging: false,
  roadDraft: null,
  bldgDraft: null,
};

export function frameState() {
  const { cur, prev } = appState;
  if (!cur) return null;
  if (!prev || prev === cur) return cur;
  const span = Math.max(1, cur.recvT - prev.recvT);
  const t = _clamp((performance.now() - cur.recvT) / span, 0, 1.5);
  const out = {
    clock_min: _lerp(prev.clock_min, cur.clock_min, t),
    total_load_kw: cur.total_load_kw,
    total_co2_kg_h: cur.total_co2_kg_h,
    total_pv_kw: cur.total_pv_kw,
    sim_min_per_sec: cur.sim_min_per_sec,
    weather: cur.weather,
    cars: [],
    people: [],
  };
  const prevCars = new Map(prev.cars.map(c => [c.id, c]));
  for (const b of cur.cars) {
    const a = prevCars.get(b.id) || b;
    out.cars.push({ ...b, x: _lerp(a.x, b.x, t), y: _lerp(a.y, b.y, t) });
  }
  const prevPeople = new Map(prev.people.map(p => [p.id, p]));
  for (const b of cur.people) {
    const a = prevPeople.get(b.id) || b;
    out.people.push({ ...b, x: _lerp(a.x, b.x, t), y: _lerp(a.y, b.y, t) });
  }
  return out;
}
