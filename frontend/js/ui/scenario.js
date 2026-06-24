// Retrofit scenario panel — "before vs. after" comparison, city-wide or targeted.
// Sliders set measure multipliers; every change debounce-posts to /api/scenario
// (a stateless design-day recompute) and re-renders: a headline EUI before→after,
// the Baseline | Retrofit | Δ table, an overlaid 24 h load chart, an indicative
// cost/payback block, an optional map heat-overlay of per-building savings, and a
// CSV export of the per-building comparison.
import { runScenario, exportScenarioCsv } from '../api.js';
import { renderChart } from './popup.js';
import { appState } from '../state.js';
import { TYPE_LABEL } from '../config.js';
import { clamp } from '../math.js';
import { setActiveView, refreshView } from './infoview.js';

// Slider value IS the multiplier sent to the backend (1.0 = no change). dir 'down'
// = a factor below 1 is the improvement; dir 'up' = a factor above 1 is.
const MEASURES = [
  { key: 'u_wall',      label: 'Wall insulation',      min: 0.3, max: 1, step: 0.05, def: 1, dir: 'down' },
  { key: 'u_roof',      label: 'Roof insulation',      min: 0.3, max: 1, step: 0.05, def: 1, dir: 'down' },
  { key: 'u_win',       label: 'Glazing (window U)',   min: 0.3, max: 1, step: 0.05, def: 1, dir: 'down' },
  { key: 'lpd',         label: 'LED lighting',         min: 0.3, max: 1, step: 0.05, def: 1, dir: 'down' },
  { key: 'e_density',   label: 'Efficient appliances', min: 0.5, max: 1, step: 0.05, def: 1, dir: 'down' },
  { key: 'cop',         label: 'Heat-pump COP',        min: 1,   max: 2, step: 0.1,  def: 1, dir: 'up'   },
  { key: 'pv_fraction', label: 'Rooftop PV area',      min: 1,   max: 3, step: 0.1,  def: 1, dir: 'up'   },
];

const PRESETS = {
  Light: { u_wall: 0.8, u_roof: 0.8, u_win: 0.8, lpd: 0.7, cop: 1.2, pv_fraction: 1.3 },
  Deep:  { u_wall: 0.45, u_roof: 0.45, u_win: 0.5, lpd: 0.45, e_density: 0.8, cop: 1.6, pv_fraction: 2.5 },
  Reset: {},
};

const ROWS = [
  { key: 'energy_kwh', label: 'Energy use',        kind: 'energy', good: 'down', strong: true },
  { key: 'hvac_kwh',   label: 'Heating / cooling', kind: 'energy', good: 'down' },
  { key: 'light_kwh',  label: 'Lighting',          kind: 'energy', good: 'down' },
  { key: 'elec_kwh',   label: 'Appliances',        kind: 'energy', good: 'down' },
  { key: 'pv_kwh',     label: 'Solar PV',          kind: 'energy', good: 'up'   },
  { key: 'net_kwh',    label: 'Net grid import',   kind: 'energy', good: 'down', strong: true },
  { key: 'co2_kg',     label: 'CO₂ emissions',     kind: 'mass',   good: 'down' },
];

const HOUR_TICKS = [0, 6, 12, 18, 23].map(h => ({ frac: h / 23, label: String(h).padStart(2, '0') + ':00' }));

const state = {};   // measure key -> current multiplier
let panel, measuresEl, resultsEl, presetsEl, targetSel, tariffInp, chartCv, costEl, mapToggle;
let debounceTimer = null;
let last = null;    // most recent result, for map overlay + export
let runSeq = 0;     // guards against out-of-order responses overwriting newer ones

export function setupScenario() {
  panel = document.getElementById('scenarioPanel');
  measuresEl = document.getElementById('scenarioMeasures');
  resultsEl = document.getElementById('scenarioResults');
  presetsEl = document.getElementById('scenarioPresets');
  targetSel = document.getElementById('scenarioTarget');
  tariffInp = document.getElementById('scenarioTariff');
  chartCv = document.getElementById('scenarioChart');
  costEl = document.getElementById('scenarioCost');
  mapToggle = document.getElementById('scenarioMapToggle');
  for (const m of MEASURES) state[m.key] = m.def;

  targetSel.innerHTML = `<option value="">All buildings</option>` +
    Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}">${v} only</option>`).join('');
  buildPresets();
  buildMeasures();

  targetSel.addEventListener('change', run);
  tariffInp.addEventListener('input', debouncedRun);
  mapToggle.addEventListener('change', () => {
    if (mapToggle.checked) {
      applyMap(last);
      setActiveView('retrofit');
    } else if (appState.activeView === 'retrofit') {
      setActiveView(null);
    }
  });
  document.getElementById('scenarioExport').addEventListener('click', () =>
    exportScenarioCsv(currentMeasures(), currentTarget(), currentTariff()).catch(() => {}));

  document.getElementById('scenarioBtn').addEventListener('click', () => {
    const open = panel.style.display === 'block';
    panel.style.display = open ? 'none' : 'block';
    if (!open) run();
  });
  document.getElementById('scenarioClose').addEventListener('click', () => {
    panel.style.display = 'none';
  });
}

function buildPresets() {
  presetsEl.innerHTML = Object.keys(PRESETS)
    .map(n => `<button data-preset="${n}">${n}</button>`).join('');
  presetsEl.querySelectorAll('button').forEach(b =>
    b.addEventListener('click', () => applyPreset(b.dataset.preset)));
}

function applyPreset(name) {
  const p = PRESETS[name] || {};
  for (const m of MEASURES) state[m.key] = p[m.key] != null ? p[m.key] : m.def;
  syncSliders();
  run();
}

function buildMeasures() {
  measuresEl.innerHTML = MEASURES.map(m => `
    <div class="measure">
      <label>${m.label}<span class="mval" data-val="${m.key}">${fmtMeasure(m, state[m.key])}</span></label>
      <input type="range" data-key="${m.key}" min="${m.min}" max="${m.max}" step="${m.step}" value="${state[m.key]}">
    </div>`).join('');
  measuresEl.querySelectorAll('input[type=range]').forEach(inp =>
    inp.addEventListener('input', () => {
      const m = MEASURES.find(x => x.key === inp.dataset.key);
      state[m.key] = Number(inp.value);
      measuresEl.querySelector(`[data-val="${m.key}"]`).textContent = fmtMeasure(m, state[m.key]);
      debouncedRun();
    }));
}

function syncSliders() {
  for (const m of MEASURES) {
    const inp = measuresEl.querySelector(`input[data-key="${m.key}"]`);
    if (inp) inp.value = state[m.key];
    const lab = measuresEl.querySelector(`[data-val="${m.key}"]`);
    if (lab) lab.textContent = fmtMeasure(m, state[m.key]);
  }
}

function currentMeasures() {
  const m = {};
  for (const x of MEASURES) if (Math.abs(state[x.key] - x.def) > 1e-9) m[x.key] = state[x.key];
  return m;
}
function currentTarget() { return targetSel.value ? { types: [targetSel.value] } : null; }
function currentTariff() { const v = Number(tariffInp.value); return Number.isFinite(v) && v >= 0 ? v : undefined; }

function debouncedRun() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(run, 200);
}

async function run() {
  const seq = ++runSeq;
  resultsEl.classList.add('loading');
  try {
    const r = await runScenario(currentMeasures(), currentTarget(), currentTariff());
    if (seq !== runSeq) return;          // a newer run started — discard this stale result
    last = r;
    renderResults(last);
    if (appState.activeView === 'retrofit') { applyMap(last); refreshView(); }
  } catch (e) {
    if (seq === runSeq) resultsEl.innerHTML = `<p class="scenErr">${e.message}</p>`;
  } finally {
    if (seq === runSeq) resultsEl.classList.remove('loading');
  }
}

function renderResults(r) {
  if (!r.n_in_scope) {
    resultsEl.innerHTML = `<p class="scenErr">No buildings match this target.</p>`;
    clearChart();
    costEl.innerHTML = '';
    return;
  }
  const eb = r.baseline.eui_kwh_m2_yr, ea = r.retrofit.eui_kwh_m2_yr, ed = r.delta.eui_kwh_m2_yr;
  const scope = r.target ? `${r.n_in_scope} buildings` : `${r.n_in_scope} buildings (whole city)`;
  const headline = `
    <div class="scenHeadline">
      <div class="scenHL"><span class="scenHLk">Baseline EUI</span><b>${Math.round(eb)}</b></div>
      <div class="scenArrow ${deltaClass('down', ed.pct)}">${deltaText(ed.pct)}</div>
      <div class="scenHL scenHL--hero"><span class="scenHLk">Retrofit EUI</span><b>${Math.round(ea)}</b></div>
    </div>
    <div class="scenUnit">EUI in kWh/m²·yr · ${scope}</div>`;
  const head = `
    <div class="scenRow scenHead">
      <span class="scenLabel">Per day</span><span class="scenNum">Baseline</span>
      <span class="scenNum">Retrofit</span><span class="scenDelta">Change</span>
    </div>`;
  const rows = ROWS.map(row => {
    const d = r.delta[row.key];
    return `<div class="scenRow${row.strong ? ' strong' : ''}">
      <span class="scenLabel">${row.label}</span>
      <span class="scenNum">${fmt(row.kind, r.baseline[row.key])}</span>
      <span class="scenNum">${fmt(row.kind, r.retrofit[row.key])}</span>
      <span class="scenDelta ${deltaClass(row.good, d.pct)}">${deltaText(d.pct)}</span>
    </div>`;
  }).join('');
  resultsEl.innerHTML = headline + head + rows +
    `<div class="scenUnit">City load over the day —
       <span class="scenLeg-base">baseline</span> vs <span class="scenLeg-after">retrofit</span> (kW)</div>`;
  renderProfile(r);
  renderCost(r);
}

function renderProfile(r) {
  const base = r.profile_kw.baseline, after = r.profile_kw.retrofit;
  const peak = Math.max(1, ...base, ...after);
  renderChart(chartCv, after, {
    yStep: niceStep(peak / 4), color: '#5fd4a8', fill: 'rgba(95,212,168,0.16)', noDot: true,
    series2: { vals: base, color: '#8090a8', fill: 'rgba(128,144,168,0.10)' },
    xTicks: HOUR_TICKS,
  });
}

function renderCost(r) {
  const c = r.cost;
  if (!c.capex) { costEl.innerHTML = ''; return; }
  const pay = c.payback_years == null ? '—' : c.payback_years + ' yr';
  costEl.innerHTML = `
    <div class="scenCostRow"><span>Capex (indicative)</span><b>${c.currency}${money(c.capex)}</b></div>
    <div class="scenCostRow"><span>Annual saving</span><b>${c.currency}${money(c.annual_savings)}/yr</b></div>
    <div class="scenCostRow"><span>Simple payback</span><b>${pay}</b></div>
    <div class="scenCostRow"><span>CO₂ avoided</span><b>${c.annual_co2_t_saved} t/yr</b></div>`;
}

function applyMap(r) {
  if (!r) { appState.scenarioMap = {}; appState.scenarioMeta = null; return; }
  let maxImp = 0;
  for (const row of r.buildings) if (row.in_scope) maxImp = Math.max(maxImp, Math.abs(row.delta_pct));
  const map = {};
  for (const row of r.buildings) {
    const imp = row.in_scope ? -row.delta_pct : 0;   // positive = energy reduction
    map[row.id] = { norm: maxImp ? clamp(imp / maxImp, -1, 1) : 0, in_scope: row.in_scope };
  }
  appState.scenarioMap = map;
  const n = r.n_in_scope != null ? r.n_in_scope : Object.keys(map).length;
  appState.scenarioMeta = { lo: 'uses more', hi: 'saves', unit: '', detail: `Retrofit savings · ${n} buildings in scope` };
}

function clearChart() {
  const g = chartCv.getContext('2d');
  g.clearRect(0, 0, chartCv.width, chartCv.height);
}

function fmt(kind, v) {
  if (kind === 'mass') return v >= 1000 ? (v / 1000).toFixed(1) + ' t' : Math.round(v) + ' kg';
  return v >= 1000 ? (v / 1000).toFixed(1) + ' MWh' : Math.round(v) + ' kWh';
}

function money(v) { return Math.round(v).toLocaleString(); }

function niceStep(v) {
  if (v <= 0) return 10;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * p;
}

function fmtMeasure(m, v) {
  if (m.dir === 'down') return v >= 0.999 ? 'none' : `−${Math.round((1 - v) * 100)}%`;
  return v <= 1.001 ? 'none' : `+${Math.round((v - 1) * 100)}%`;
}

function deltaText(pct) {
  if (Math.abs(pct) < 0.05) return '0%';
  return (pct > 0 ? '+' : '−') + Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0) + '%';
}

function deltaClass(good, pct) {
  if (Math.abs(pct) < 0.05) return 'flat';
  return (good === 'down' ? pct < 0 : pct > 0) ? 'good' : 'bad';
}
