import { POLL_MS } from './config.js';
import { appState } from './state.js';
import { prepareWorld } from './world-prep.js';
import { flashToast } from './ui/toast.js';

let backendLive = null;
let worldRefreshing = false;

export async function fetchWorld() {
  const r = await fetch('/api/world');
  appState.world = await r.json();
  prepareWorld();
  document.querySelector('#hud h1').textContent = appState.world.name;
  document.title = appState.world.name + ' — City Energy Analysis';
  document.getElementById('statBldg').textContent = appState.world.buildings.length;
}

export async function refreshWorld() {
  if (worldRefreshing) return;
  worldRefreshing = true;
  try {
    const r = await fetch('/api/world');
    appState.world = await r.json();
    prepareWorld();
    document.getElementById('statBldg').textContent = appState.world.buildings.length;
  } catch {} finally { worldRefreshing = false; }
}

export async function pollState() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    s.recvT = performance.now();
    appState.prev = appState.cur || s;
    appState.cur = s;
    if (s.buildings_eui) {
      appState.euiMap = {};
      for (const e of s.buildings_eui) appState.euiMap[e.id] = e;
    }
    setBackend(true);
    if (appState.world && s.world_rev !== appState.world.world_rev) refreshWorld();
  } catch {
    setBackend(false);
  } finally {
    setTimeout(pollState, POLL_MS);
  }
}

function setBackend(live) {
  if (live === backendLive) return;
  backendLive = live;
  const badge = document.getElementById('backendBadge');
  badge.classList.toggle('live', live);
  badge.classList.toggle('dead', !live);
  document.getElementById('backendText').textContent =
    live ? 'Python backend · live' : 'backend unreachable';
}

export async function sendEdit(op) {
  try {
    const r = await fetch('/api/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(op),
    });
    if (r.ok) return true;
    const e = await r.json().catch(() => null);
    flashToast('✋ ' + (e && e.detail ? e.detail : 'edit rejected'));
    return false;
  } catch { return false; }
}

export function sendSpeed(mps) {
  fetch('/api/edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'set_speed', sim_min_per_sec: mps }),
  }).catch(() => {});
}

export function sendSeek(clockMin) {
  fetch('/api/edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'seek_time', clock_min: clockMin }),
  }).catch(() => {});
}
