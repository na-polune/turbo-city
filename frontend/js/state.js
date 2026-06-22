const _lerp = (a, b, t) => a + (b - a) * t;
const _clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;

export const appState = {
  world: null,
  cur: null,
  prev: null,
  euiMap: {},
  euiOverlay: false,
  scenarioOverlay: false,
  scenarioMap: {},      // building id -> { norm: -1..1, in_scope }
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
