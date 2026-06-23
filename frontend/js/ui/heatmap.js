// Overheating heat-map: a triggered analysis (never on the live clock). Clicking
// "Heat Map" runs a design-day overheating pass on the current city under today's
// weather and overlays each building by how hot it free-floats indoors.
import { appState } from '../state.js';
import { runHeatmap } from '../api.js';

let panel, btn;

export function setupHeatmap() {
  panel = document.getElementById('heatPanel');
  btn = document.getElementById('heatBtn');
  btn.addEventListener('click', run);
  document.getElementById('heatClose').addEventListener('click', close);
}

async function run() {
  // The heat overlay owns the map while it's up — clear the other overlays.
  appState.euiOverlay = false;
  document.getElementById('euiToggle').classList.remove('active');
  appState.scenarioOverlay = false;
  panel.classList.add('open');
  setStatus('Running analysis…');
  btn.disabled = true;
  try {
    apply(await runHeatmap());
  } catch (e) {
    setStatus('⚠ ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

function close() {
  panel.classList.remove('open');
  appState.heatOverlay = false;
  appState.heatMap = {};
  appState.dirty = true;
}

function apply(d) {
  const map = {};
  for (const b of d.buildings) map[b.id] = b;
  appState.heatMap = map;
  appState.heatOverlay = true;
  appState.dirty = true;

  const w = d.weather, s = d.summary;
  const where = appState.world ? appState.world.name : 'This city';
  document.getElementById('heatBasis').textContent = w.source === 'api'
    ? `${where} · today · peak ${w.peak_outdoor_c}°C outdoor, wind ${w.mean_wind_ms} m/s`
    : `Hot design day (offline) · peak ${w.peak_outdoor_c}°C, wind ${w.mean_wind_ms} m/s`;
  document.getElementById('heatLegendLo').textContent = `${s.legend_lo_c}°C`;
  document.getElementById('heatLegendHi').textContent = `${s.legend_hi_c}°C`;
  document.getElementById('heatMax').textContent = `${s.max_peak_c}°C`;
  document.getElementById('heatMean').textContent = `${s.mean_peak_c}°C`;
  document.getElementById('heatOver').textContent = `${s.n_over_28} / ${s.n_buildings}`;
  setStatus('');
}

function setStatus(msg) {
  document.getElementById('heatStatus').textContent = msg;
}
