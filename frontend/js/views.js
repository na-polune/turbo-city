// Info-View registry — one switchable map overlay at a time, modelled on the
// Cities: Skylines info-views system. Each view turns a per-building scalar into
// a roof colour via a ramp, with a shared legend (units + range) and, for the
// Energy view, tabs that swap which scalar is shown.
//
// LIVE views (Energy/Solar/CO₂) read per-building values straight from the
// /api/state snapshot (appState.viewMap) and normalise client-side.
// TRIGGERED views (Overheating/Retrofit) read pre-computed maps produced by the
// /api/heatmap and /api/scenario passes (appState.heatMap / scenarioMap).
import { appState } from './state.js';
import { euiColor, savingsColor, lerpColor } from './math.js';

// PV generation ramp: faint slate (little) → gold (lots) — "more is good".
export function pvColor(norm) { return lerpColor('#33415e', '#ffd24d', norm); }

export const VIEWS = [
  {
    id: 'eui', label: 'Energy', kind: 'live', ramp: euiColor, unit: 'W/m²', domain: [0, 1],
    tabs: [
      { id: 'e_total', label: 'Total' },
      { id: 'e_hvac', label: 'Heating / cooling' },
      { id: 'e_light', label: 'Lighting' },
      { id: 'e_plug', label: 'Appliances' },
    ],
    field: tab => tab || 'e_total',
  },
  { id: 'solar', label: 'Solar PV', kind: 'live', ramp: pvColor, unit: 'kW', domain: [0, 1], field: () => 'pv' },
  { id: 'co2', label: 'CO₂', kind: 'live', ramp: euiColor, unit: 'kg/h', domain: [0, 1], field: () => 'co2' },
  {
    id: 'overheat', label: 'Overheating', kind: 'triggered', ramp: euiColor, unit: '°C', domain: [0, 1],
    data: () => appState.heatMap, norm: b => b.severity, meta: () => appState.heatMeta,
  },
  {
    id: 'retrofit', label: 'Retrofit', kind: 'triggered', ramp: savingsColor, unit: '', domain: [-1, 1],
    data: () => appState.scenarioMap, norm: b => (b.in_scope ? b.norm : null), meta: () => appState.scenarioMeta,
  },
];

export const VIEW_BY_ID = Object.fromEntries(VIEWS.map(v => [v.id, v]));

const round1 = v => Math.round(v * 10) / 10;

// Recompute the normalised per-building values + legend for the active view.
// Cheap and called only on view/tab change or a fresh /api/state — never per frame.
export function recomputeActiveView() {
  appState.viewNorm = {};
  appState.viewLegend = null;
  const view = appState.activeView && VIEW_BY_ID[appState.activeView];
  if (!view) return;

  if (view.kind === 'triggered') {
    const data = view.data() || {};
    for (const id in data) {
      const n = view.norm(data[id]);
      if (n != null) appState.viewNorm[id] = n;
    }
    appState.viewLegend = { ramp: view.ramp, domain: view.domain, ...(view.meta() || {}) };
    return;
  }

  // live: pull the active field off every building and min/max normalise
  const vm = appState.viewMap || {};
  const field = view.field(appState.activeTab);
  let lo = Infinity, hi = -Infinity;
  const raw = {};
  for (const id in vm) {
    const v = vm[id][field];
    if (v == null) continue;
    raw[id] = v;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!isFinite(lo)) { lo = 0; hi = 1; }
  const rng = Math.max(1e-6, hi - lo);
  for (const id in raw) appState.viewNorm[id] = (raw[id] - lo) / rng;
  appState.viewLegend = { lo: round1(lo), hi: round1(hi), unit: view.unit, ramp: view.ramp, domain: view.domain };
}

// Roof fill colour for a building under the active view, or null for no overlay.
export function overlayColorFor(buildingId) {
  if (!appState.activeView) return null;
  const n = appState.viewNorm[buildingId];
  if (n == null) return null;
  const view = VIEW_BY_ID[appState.activeView];
  return view ? view.ramp(n) : null;
}
