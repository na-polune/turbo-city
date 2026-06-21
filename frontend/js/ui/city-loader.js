import { loadCity } from '../api.js';
import { flashToast } from './toast.js';

const panel = () => document.getElementById('cityPanel');

export function setupCityLoader() {
  document.getElementById('changeCityBtn').addEventListener('click', () => {
    const p = panel();
    p.style.display = p.style.display === 'block' ? 'none' : 'block';
    if (p.style.display === 'block') document.getElementById('cityLat').focus();
  });
  document.getElementById('cityClose').addEventListener('click', closePanel);
  document.getElementById('citySubmit').addEventListener('click', submitCity);
  document.getElementById('cityForm').addEventListener('keydown', e => {
    if (e.key === 'Enter') submitCity();
    if (e.key === 'Escape') closePanel();
  });
}

function closePanel() {
  panel().style.display = 'none';
  document.getElementById('cityStatus').textContent = '';
}

async function submitCity() {
  const lat = parseFloat(document.getElementById('cityLat').value);
  const lon = parseFloat(document.getElementById('cityLon').value);
  const radius_m = Math.round(parseFloat(document.getElementById('cityRadius').value) || 250);
  const name = document.getElementById('cityName').value.trim();
  const status = document.getElementById('cityStatus');
  const btn = document.getElementById('citySubmit');

  if (!isFinite(lat) || lat < -90 || lat > 90) {
    status.textContent = 'Latitude must be −90 to 90.';
    return;
  }
  if (!isFinite(lon) || lon < -180 || lon > 180) {
    status.textContent = 'Longitude must be −180 to 180.';
    return;
  }
  if (radius_m < 50 || radius_m > 2000) {
    status.textContent = 'Radius must be 50–2000 m.';
    return;
  }

  btn.disabled = true;
  status.textContent = 'Fetching OSM data… first load may take ~10 s.';
  try {
    const result = await loadCity(lat, lon, radius_m, name || undefined);
    flashToast('Loaded: ' + result.name);
    closePanel();
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}
