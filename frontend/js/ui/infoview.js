// Info-View rail + shared legend. One overlay is active at a time (appState.activeView);
// the rail picks it, the bottom-centre legend shows its colour ramp, range, units,
// tabs (for the Energy view) and any view-specific detail/stats. Live views recolor
// from each /api/state tick; the Overheating view runs its analysis on demand.
import { appState } from '../state.js';
import { VIEWS, VIEW_BY_ID, recomputeActiveView } from '../views.js';
import { runHeatmap } from '../api.js';

let rail, legend;

export function setupInfoView() {
  rail = document.getElementById('infoRail');
  legend = document.getElementById('viewLegend');
  rail.innerHTML = '';
  rail.appendChild(railBtn(null, 'Off'));
  for (const v of VIEWS) rail.appendChild(railBtn(v.id, v.label));
  document.getElementById('vlClose').addEventListener('click', () => setActiveView(null));
  renderRail();
  renderLegend();
}

function railBtn(id, label) {
  const b = document.createElement('button');
  b.textContent = label;
  b.dataset.view = id || '';
  b.addEventListener('click', () => setActiveView(id === appState.activeView ? null : id));
  return b;
}

// Switch the active overlay (or null). The Overheating view fetches its analysis
// the first time it's shown.
export async function setActiveView(id) {
  appState.activeView = id;
  renderRail();
  if (!id) { appState.viewNorm = {}; appState.viewLegend = null; renderLegend(); appState.dirty = true; return; }
  if (id === 'overheat' && !Object.keys(appState.heatMap).length) {
    showStatus('Running overheating analysis…');
    try { await runOverheat(); } catch (e) { showStatus('⚠ ' + e.message); return; }
  }
  recomputeActiveView();
  renderLegend();
  appState.dirty = true;
}

function setActiveTab(tab) {
  appState.activeTab = tab;
  recomputeActiveView();
  renderLegend();
  appState.dirty = true;
}

// Re-pull data for the active view without toggling it (e.g. retrofit sliders moved).
export function refreshView() {
  recomputeActiveView();
  renderLegend();
  appState.dirty = true;
}

async function runOverheat() {
  const d = await runHeatmap();
  const map = {};
  for (const b of d.buildings) map[b.id] = b;
  appState.heatMap = map;
  const w = d.weather, s = d.summary;
  const where = appState.world ? appState.world.name : 'This city';
  appState.heatMeta = {
    lo: s.legend_lo_c, hi: s.legend_hi_c, unit: '°C',
    detail: w.source === 'api'
      ? `${where} · today · peak ${w.peak_outdoor_c}°C, wind ${w.mean_wind_ms} m/s`
      : `Hot design day · peak ${w.peak_outdoor_c}°C, wind ${w.mean_wind_ms} m/s`,
    stats: [`Hottest ${s.max_peak_c}°C`, `Mean ${s.mean_peak_c}°C`, `Over 28°C ${s.n_over_28}/${s.n_buildings}`],
  };
}

function renderRail() {
  for (const b of rail.children) {
    const id = b.dataset.view || null;
    b.classList.toggle('active', id === appState.activeView);
    if (id === 'retrofit') b.disabled = !Object.keys(appState.scenarioMap).length;
  }
}

function gradientCss(view) {
  const [a, b] = view.domain;
  const stops = [];
  for (let i = 0; i <= 6; i++) stops.push(view.ramp(a + (b - a) * (i / 6)));
  return `linear-gradient(90deg, ${stops.join(', ')})`;
}

function fmt(v, unit) {
  if (v == null) return '';
  if (typeof v === 'number') return unit ? `${v} ${unit}` : `${v}`;
  return v;
}

function showStatus(msg) {
  legend.classList.add('open');
  document.getElementById('vlTitle').textContent = VIEW_BY_ID[appState.activeView]?.label || '';
  document.getElementById('vlDetail').textContent = msg;
  document.getElementById('vlTabs').innerHTML = '';
  document.getElementById('vlStats').innerHTML = '';
  document.getElementById('vlBar').style.background = 'transparent';
  document.getElementById('vlLo').textContent = '';
  document.getElementById('vlHi').textContent = '';
}

function renderLegend() {
  const id = appState.activeView;
  if (!id) { legend.classList.remove('open'); return; }
  legend.classList.add('open');
  const view = VIEW_BY_ID[id];
  const lg = appState.viewLegend;
  document.getElementById('vlTitle').textContent = view.label;
  document.getElementById('vlDetail').textContent = lg && lg.detail ? lg.detail : '';

  const tabsEl = document.getElementById('vlTabs');
  tabsEl.innerHTML = '';
  if (view.tabs) {
    for (const t of view.tabs) {
      const tb = document.createElement('button');
      tb.className = 'vl-tab' + (t.id === appState.activeTab ? ' active' : '');
      tb.textContent = t.label;
      tb.addEventListener('click', () => setActiveTab(t.id));
      tabsEl.appendChild(tb);
    }
  }

  const statsEl = document.getElementById('vlStats');
  statsEl.innerHTML = '';
  if (lg && lg.stats) for (const s of lg.stats) {
    const sp = document.createElement('span');
    sp.textContent = s;
    statsEl.appendChild(sp);
  }

  document.getElementById('vlBar').style.background = lg ? gradientCss(view) : 'transparent';
  document.getElementById('vlLo').textContent = lg ? fmt(lg.lo, '') : '';
  document.getElementById('vlHi').textContent = lg ? fmt(lg.hi, lg.unit) : '';
}
