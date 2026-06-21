// Retrofit scenario panel — "before vs. after" city-wide comparison.
// Sliders set city-wide measure multipliers; every change debounce-posts to
// /api/scenario (a stateless design-day recompute) and re-renders the two-column
// Baseline | Retrofit | Δ table plus a headline EUI before→after.
import { runScenario } from '../api.js';

// Each measure's slider value IS the multiplier sent to the backend (1.0 = no
// change). dir 'down' = a factor below 1 is the improvement (U-values, lighting,
// appliances); dir 'up' = a factor above 1 is the improvement (COP, PV area).
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

// Per-day comparison rows. good = direction that counts as an improvement.
const ROWS = [
  { key: 'energy_kwh', label: 'Energy use',        kind: 'energy', good: 'down', strong: true },
  { key: 'hvac_kwh',   label: 'Heating / cooling', kind: 'energy', good: 'down' },
  { key: 'light_kwh',  label: 'Lighting',          kind: 'energy', good: 'down' },
  { key: 'elec_kwh',   label: 'Appliances',        kind: 'energy', good: 'down' },
  { key: 'pv_kwh',     label: 'Solar PV',          kind: 'energy', good: 'up'   },
  { key: 'net_kwh',    label: 'Net grid import',   kind: 'energy', good: 'down', strong: true },
  { key: 'co2_kg',     label: 'CO₂ emissions',     kind: 'mass',   good: 'down' },
];

const state = {};   // measure key -> current multiplier
let panel, measuresEl, resultsEl, presetsEl;
let debounceTimer = null;

export function setupScenario() {
  panel = document.getElementById('scenarioPanel');
  measuresEl = document.getElementById('scenarioMeasures');
  resultsEl = document.getElementById('scenarioResults');
  presetsEl = document.getElementById('scenarioPresets');
  for (const m of MEASURES) state[m.key] = m.def;

  buildPresets();
  buildMeasures();

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

function debouncedRun() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(run, 200);
}

async function run() {
  const measures = {};
  for (const m of MEASURES) {
    if (Math.abs(state[m.key] - m.def) > 1e-9) measures[m.key] = state[m.key];
  }
  resultsEl.classList.add('loading');
  try {
    renderResults(await runScenario(measures));
  } catch (e) {
    resultsEl.innerHTML = `<p class="scenErr">${e.message}</p>`;
  } finally {
    resultsEl.classList.remove('loading');
  }
}

function renderResults(r) {
  if (!r.n_buildings) {
    resultsEl.innerHTML = `<p class="scenErr">No buildings in this world to analyse.</p>`;
    return;
  }
  const eb = r.baseline.eui_kwh_m2_yr, ea = r.retrofit.eui_kwh_m2_yr, ed = r.delta.eui_kwh_m2_yr;
  const headline = `
    <div class="scenHeadline">
      <div class="scenHL"><span class="scenHLk">Baseline EUI</span><b>${Math.round(eb)}</b></div>
      <div class="scenArrow ${deltaClass('down', ed.pct)}">${deltaText(ed.pct)}</div>
      <div class="scenHL"><span class="scenHLk">Retrofit EUI</span><b>${Math.round(ea)}</b></div>
    </div>
    <div class="scenUnit">EUI in kWh/m²·yr</div>`;
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
  resultsEl.innerHTML =
    headline +
    `<div class="scenMeta">${r.n_buildings} buildings · deterministic design day</div>` +
    head + rows;
}

function fmt(kind, v) {
  if (kind === 'mass') return v >= 1000 ? (v / 1000).toFixed(1) + ' t' : Math.round(v) + ' kg';
  return v >= 1000 ? (v / 1000).toFixed(1) + ' MWh' : Math.round(v) + ' kWh';
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
