import { appState } from '../state.js';

let lastHud = 0;

export function updateHUD(s) {
  const now = performance.now();
  if (!s || now - lastHud < 250) return;
  lastHud = now;
  const m = Math.floor(((s.clock_min % 1440) + 1440) % 1440);
  document.getElementById('clockText').textContent =
    String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
  const hour = m / 60;
  document.getElementById('clockGlyph').textContent = (hour >= 6.5 && hour < 18.5) ? '☀️' : '🌙';
  if (s.weather) {
    const wr = document.getElementById('weatherRow');
    document.getElementById('weatherIcon').textContent = s.weather.icon;
    const tag = s.weather.source === 'api' ? ' 🌐' : '';
    document.getElementById('weatherLabel').textContent = s.weather.label + tag;
    wr.style.display = 'flex';
  }
  document.getElementById('statCars').textContent = s.cars.length;
  document.getElementById('statPop').textContent = s.people.length;
  const kw = s.total_load_kw;
  document.getElementById('statLoad').textContent =
    kw >= 1000 ? (kw / 1000).toFixed(1) + ' MW' : kw + ' kW';
  const co2 = s.total_co2_kg_h;
  document.getElementById('statCO2').textContent =
    co2 == null ? '–' : co2 >= 1000 ? (co2 / 1000).toFixed(1) + ' t/h' : co2.toFixed(1) + ' kg/h';
  const pv = s.total_pv_kw || 0;
  document.getElementById('statPV').textContent =
    pv >= 1000 ? (pv / 1000).toFixed(1) + ' MW' : pv.toFixed(1) + ' kW';
  if (!appState.sliderDragging) {
    document.getElementById('timeSlider').value = m;
    const paused = s.sim_min_per_sec === 0;
    document.getElementById('playBtn').textContent = paused ? '▶' : '⏸';
    if (!paused) {
      const mps = s.sim_min_per_sec;
      document.querySelectorAll('#speedRow button').forEach(b =>
        b.classList.toggle('active', Number(b.dataset.speed) === mps));
    }
  }
}
