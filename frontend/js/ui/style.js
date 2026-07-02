// Render-style rails: Ground (Stylized | Hillshade | Map | Satellite), Relief
// and Detail (LOD). All optional looks on top of the classic stylized view —
// persisted in localStorage, availability driven by what the world provides
// (hillshade needs the DEM grid, imagery needs a real lat/lon center).
import { appState } from '../state.js';
import { prepareWorld } from '../world-prep.js';
import { hasTerrain, groundAttribution } from '../terrain.js';
import { flashToast } from './toast.js';

const STORE_KEY = 'cityStyle';
const GROUNDS = [
  ['stylized', 'Stylized', () => true],
  ['hillshade', 'Hillshade', () => hasTerrain()],
  ['map', 'Map', () => !!(appState.world && appState.world.center)],
  ['satellite', 'Satellite', () => !!(appState.world && appState.world.center)],
];
const DETAILS = { auto: 'Detail: Auto', low: 'Detail: Low', high: 'Detail: High' };

let groundRail, displayRail, attributionEl;

export function setupStyle() {
  groundRail = document.getElementById('groundRail');
  displayRail = document.getElementById('displayRail');
  attributionEl = document.getElementById('attribution');
  try {
    Object.assign(appState.style, JSON.parse(localStorage.getItem(STORE_KEY)) || {});
  } catch {}

  for (const [id, label] of GROUNDS) {
    const b = document.createElement('button');
    b.textContent = label;
    b.dataset.ground = id;
    b.addEventListener('click', () => {
      appState.style.ground = id;
      if (id === 'map' || id === 'satellite') flashToast('Loading imagery tiles…');
      applyStyle();
    });
    groundRail.appendChild(b);
  }

  const relief = document.createElement('button');
  relief.id = 'reliefBtn';
  relief.textContent = 'Relief';
  relief.addEventListener('click', () => {
    appState.style.relief = !appState.style.relief;
    applyStyle();
  });
  displayRail.appendChild(relief);

  const detail = document.createElement('button');
  detail.id = 'detailBtn';
  detail.title = 'Level of detail: Auto switches with zoom, Low/High pin it';
  detail.addEventListener('click', () => {
    const keys = Object.keys(DETAILS);
    const st = appState.style;
    st.detail = keys[(keys.indexOf(st.detail) + 1) % keys.length];
    persist();
    renderRails();
    appState.dirty = true;
  });
  displayRail.appendChild(detail);

  // Rebaked (world load or style change) → refresh availability + attribution.
  window.addEventListener('ground-baked', renderRails);
  window.addEventListener('ground-bake-failed', e => {
    flashToast(`⚠ Could not load ${e.detail} tiles — back to Stylized`);
    appState.style.ground = 'stylized';
    applyStyle();
  });
  renderRails();
}

function applyStyle() {
  persist();
  // Re-lift every baked vertex and re-bake the ground for the new style.
  if (appState.world) prepareWorld();
  renderRails();
  appState.dirty = true;
}

function persist() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(appState.style)); } catch {}
}

const RELIEF_TITLE = 'Lift buildings, roads and agents to their real terrain height';

function renderRails() {
  const st = appState.style;
  // A world switch can strip a mode's data (grid world: no DEM, no lat/lon).
  const current = GROUNDS.find(([id]) => id === st.ground);
  if (current && !current[2]()) { st.ground = 'stylized'; persist(); }
  for (const b of groundRail.querySelectorAll('button')) {
    b.disabled = !GROUNDS.find(([id]) => id === b.dataset.ground)[2]();
    b.classList.toggle('active', st.ground === b.dataset.ground);
  }
  const relief = document.getElementById('reliefBtn');
  relief.disabled = !hasTerrain() || st.ground === 'stylized';
  relief.classList.toggle('active', st.relief && !relief.disabled);
  relief.title = !hasTerrain()
    ? 'No terrain data for this world'
    : st.ground === 'stylized'
      ? 'Relief needs a terrain-aware ground (Hillshade, Map or Satellite)'
      : RELIEF_TITLE;
  const detail = document.getElementById('detailBtn');
  detail.textContent = DETAILS[st.detail] || DETAILS.auto;
  detail.classList.toggle('active', st.detail !== 'auto');
  const attr = groundAttribution();
  attributionEl.textContent = attr || '';
  attributionEl.style.display = attr ? 'block' : 'none';
}
