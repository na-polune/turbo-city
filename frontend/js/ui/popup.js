import { appState } from '../state.js';
import { sendEdit } from '../api.js';
import { MAX_FLOORS, DETAIL_REFRESH_MS, TYPE_LABEL } from '../config.js';
import { flashToast } from './toast.js';

const popup = document.getElementById('popup');
const chart = document.getElementById('chart');
let curFloors = null;
let refreshTimer = null;

export function setupPopup() {
  document.getElementById('popupClose').addEventListener('click', closePopup);
  document.getElementById('floorMinus').addEventListener('click', () => nudgeFloors(-1));
  document.getElementById('floorPlus').addEventListener('click', () => nudgeFloors(1));
  document.getElementById('entityRemove').addEventListener('click', () => {
    if (!appState.openKind) return;
    sendEdit({ op: 'remove_' + appState.openKind, id: appState.openId });
    closePopup();
  });
}

export async function openDetail(kind, id) {
  appState.openKind = kind;
  appState.openId = id;
  await refreshDetail();
  popup.classList.add('open');
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshDetail, DETAIL_REFRESH_MS);
}

export function closePopup() {
  popup.classList.remove('open');
  appState.openKind = null;
  appState.openId = null;
  clearInterval(refreshTimer);
}

export async function refreshDetail() {
  if (!appState.openKind) return;
  let d;
  try {
    const r = await fetch(`/api/${appState.openKind}/${appState.openId}`);
    if (!r.ok) return closePopup();
    d = await r.json();
  } catch { return; }
  document.getElementById('popupTitle').textContent = d.name;
  popup.classList.toggle('editable', appState.openKind === 'building');
  popup.classList.add('removable');
  const sub = document.getElementById('popupSub');
  const nowEl = document.getElementById('popupNow');
  if (appState.openKind === 'building') {
    curFloors = d.floors;
    document.getElementById('floorVal').textContent = d.floors;
    document.getElementById('floorMinus').disabled = d.floors <= 1;
    document.getElementById('floorPlus').disabled = d.floors >= MAX_FLOORS;
    sub.textContent = `${TYPE_LABEL[d.type]} · ${d.floors} floor${d.floors > 1 ? 's' : ''} · ${d.area_m2} m² — electricity, last 24 h`;
    renderChart(chart, d.history_kw, {
      yStep: 50, color: '#ffc94d', fill: 'rgba(255,201,77,0.16)',
      xTicks: timeTicks((d.history_kw.length - 1) * d.sample_min, 6),
    });
    const pvStr = d.pv_kw > 0.1 ? ` · ☀️ PV ${d.pv_kw.toFixed(1)} kW` : '';
    nowEl.innerHTML = `Now: <b>${Math.round(d.load_kw)}</b> kW${pvStr} · ${d.co2_kg_h.toFixed(1)} kg CO₂/h · T<sub>in</sub> ${d.t_in_c}°C / T<sub>out</sub> ${d.t_out_c}°C · occ ${Math.round(d.occupancy * 100)}%`;
  } else if (appState.openKind === 'car') {
    sub.textContent = 'Vehicle telemetry — speed, last 60 s';
    renderChart(chart, d.history_kmh, {
      yStep: 10, yMin: 20, capacity: d.capacity,
      color: '#5fd4a8', fill: 'rgba(95,212,168,0.16)',
      xTicks: secTicks(d.capacity * d.sample_dt_s, 4),
    });
    nowEl.innerHTML = `Now: <b>${Math.round(d.speed_kmh)}</b> km/h · ${d.distance_km_today} km driven`;
  } else {
    sub.textContent = 'Citizen activity — steps per hour, last 24 h';
    renderChart(chart, d.history_steps_h, {
      yStep: 1000, yMin: 2000, color: '#7aa7ff', fill: 'rgba(122,167,255,0.16)',
      xTicks: timeTicks((d.history_steps_h.length - 1) * d.sample_min, 6),
    });
    nowEl.innerHTML = `${d.activity} · <b>${d.steps_per_h.toLocaleString()}</b> steps/h · ${d.distance_km_today} km today`;
  }
}

async function nudgeFloors(delta) {
  if (appState.openKind !== 'building' || curFloors === null) return;
  const floors = curFloors + delta;
  if (floors < 1 || floors > MAX_FLOORS) return;
  const ok = await sendEdit({ op: 'set_floors', id: appState.openId, floors });
  if (ok) refreshDetail();
}

// Line chart on the given canvas. opt.series2 = {vals, color, fill} draws a second
// series behind the primary (used by the retrofit panel to overlay baseline vs
// after); opt.noDot suppresses the trailing marker.
export function renderChart(cv, vals, opt) {
  const g = cv.getContext('2d');
  const cw = cv.width, ch = cv.height;
  g.clearRect(0, 0, cw, ch);
  if (!vals.length) return;
  const padL = 56, padR = 16, padT = 14, padB = 34;
  const pw = cw - padL - padR, ph = ch - padT - padB;
  let vmax = opt.yMin || 10;
  const scan = opt.series2 ? vals.concat(opt.series2.vals) : vals;
  for (const v of scan) if (v > vmax) vmax = v;
  vmax = Math.ceil(vmax / opt.yStep) * opt.yStep;
  g.strokeStyle = 'rgba(255,255,255,0.12)'; g.lineWidth = 1;
  g.fillStyle = '#aab4cc'; g.font = '20px system-ui, sans-serif'; g.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const y = padT + ph - (ph * i) / 4;
    g.beginPath(); g.moveTo(padL, y); g.lineTo(cw - padR, y); g.stroke();
    g.fillText(Math.round((vmax * i) / 4), padL - 8, y + 7);
  }
  g.textAlign = 'center';
  for (const tick of opt.xTicks) g.fillText(tick.label, padL + pw * tick.frac, ch - 10);
  const cap = opt.capacity || vals.length;
  const X = i => padL + pw * ((cap - vals.length + i) / Math.max(1, cap - 1));
  const Y = v => padT + ph - (ph * v) / vmax;
  const series = (data, color, fill, dot) => {
    g.beginPath();
    for (let i = 0; i < data.length; i++) i ? g.lineTo(X(i), Y(data[i])) : g.moveTo(X(i), Y(data[i]));
    g.strokeStyle = color; g.lineWidth = 3; g.stroke();
    if (fill) {
      g.lineTo(X(data.length - 1), padT + ph); g.lineTo(X(0), padT + ph); g.closePath();
      g.fillStyle = fill; g.fill();
    }
    if (dot) { g.fillStyle = color; g.beginPath(); g.arc(X(data.length - 1), Y(data[data.length - 1]), 6, 0, 7); g.fill(); }
  };
  if (opt.series2) series(opt.series2.vals, opt.series2.color, opt.series2.fill, false);
  series(vals, opt.color, opt.fill, !opt.noDot);
}

function timeTicks(windowMin, n) {
  const clockMin = appState.cur ? appState.cur.clock_min : 0;
  const ticks = [];
  for (let k = 0; k <= n; k++) {
    const m = clockMin - windowMin * (1 - k / n);
    const mm = ((m % 1440) + 1440) % 1440;
    ticks.push({
      frac: k / n,
      label: String(Math.floor(mm / 60)).padStart(2, '0') + ':' +
             String(Math.floor(mm % 60)).padStart(2, '0'),
    });
  }
  return ticks;
}

function secTicks(windowSec, n) {
  const ticks = [];
  for (let k = 0; k <= n; k++) {
    const ago = Math.round(windowSec * (1 - k / n));
    ticks.push({ frac: k / n, label: ago === 0 ? 'now' : `-${ago}s` });
  }
  return ticks;
}
