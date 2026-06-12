'use strict';
/* ================================================================
   City Energy Analysis — render-only frontend (real OSM area).
   All simulation runs in the Python backend; this file:
     1. fetches /api/world once (real building footprints, roads, lamps),
     2. polls /api/state at 10 Hz (positions, clock, total load),
     3. on click, fetches /api/building|car|person/{id} and shows results.
   World coordinates are meters (x east, y south), centered on the area.
   ================================================================ */

/* ---------------- config / iso math ---------------- */
const HW = 6.4, HH = 3.2;               // iso px per meter (half-vector)
const FLOOR_H = 10;                     // px per storey
const POLL_MS = 100;
const DETAIL_REFRESH_MS = 2000;
const isoX = (wx, wy) => (wx - wy) * HW;
const isoY = (wx, wy) => (wx + wy) * HH;
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function hexToRgb(h) {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}
function shade(hex, f) {
  const c = hexToRgb(hex).map(v => clamp(Math.round(v * f), 0, 255));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
const PALETTES = {
  res:    [['#c9a486', '#8a6e54'], ['#b8909a', '#7d5b64'], ['#a8b59a', '#6f7a62'], ['#d3b78f', '#94805f']],
  office: [['#8fa6bd', '#5c7390'], ['#9aa9b8', '#66788c'], ['#7e93ad', '#52647e'], ['#a3b6c9', '#6e8298']],
  shop:   [['#e0a35c', '#a8743a'], ['#d98b7a', '#a05c4e'], ['#86bda0', '#578a6e'], ['#c9a0c4', '#8f6a8b']]
};

/* ---------------- canvas / camera ---------------- */
const canvas = document.getElementById('city');
const ctx = canvas.getContext('2d');
let W = 0, Hh = 0, DPR = 1;
const cam = { x: 0, y: 0, zoom: 0.3 };
const ZOOM_MIN = 0.12, ZOOM_MAX = 3.5;
let world = null;
let isoBounds = null;                   // {x0, y0, x1, y1} of all geometry, iso px

function resize() {
  DPR = Math.min(2, window.devicePixelRatio || 1);
  W = window.innerWidth; Hh = window.innerHeight;
  canvas.width = Math.round(W * DPR); canvas.height = Math.round(Hh * DPR);
}
window.addEventListener('resize', resize);

function fitCamera() {
  const bw = isoBounds.x1 - isoBounds.x0, bh = isoBounds.y1 - isoBounds.y0;
  cam.x = (isoBounds.x0 + isoBounds.x1) / 2;
  cam.y = (isoBounds.y0 + isoBounds.y1) / 2;
  cam.zoom = clamp(Math.min(W / bw, Hh / bh) * 1.12, ZOOM_MIN, ZOOM_MAX);
}
function screenToIso(sx, sy) {
  return { ix: (sx - W / 2) / cam.zoom + cam.x, iy: (sy - Hh / 2) / cam.zoom + cam.y };
}
function isoToScreen(ix, iy) {
  return { sx: (ix - cam.x) * cam.zoom + W / 2, sy: (iy - cam.y) * cam.zoom + Hh / 2 };
}
function worldToScreen(wx, wy) { return isoToScreen(isoX(wx, wy), isoY(wx, wy)); }
function clampCam() {
  cam.zoom = clamp(cam.zoom, ZOOM_MIN, ZOOM_MAX);
  cam.x = clamp(cam.x, isoBounds.x0, isoBounds.x1);
  cam.y = clamp(cam.y, isoBounds.y0, isoBounds.y1);
}
function zoomAt(sx, sy, factor) {
  const before = screenToIso(sx, sy);
  cam.zoom = clamp(cam.zoom * factor, ZOOM_MIN, ZOOM_MAX);
  const after = screenToIso(sx, sy);
  cam.x += before.ix - after.ix;
  cam.y += before.iy - after.iy;
  clampCam();
}

/* ---------------- pointer input (pan / pinch / click / hover) ---------------- */
const pointers = new Map();
let dragStart = null, pinchDist = 0, moved = 0;
canvas.addEventListener('pointerdown', e => {
  canvas.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  moved = 0;
  if (pointers.size === 1) {
    dragStart = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y };
    canvas.classList.add('dragging');
  } else if (pointers.size === 2) {
    const pts = [...pointers.values()];
    pinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    dragStart = null;
  }
});
canvas.addEventListener('pointermove', e => {
  const p = pointers.get(e.pointerId);
  if (p) {
    moved += Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y);
    p.x = e.clientX; p.y = e.clientY;
  }
  if (pointers.size === 1 && dragStart) {
    cam.x = dragStart.cx - (e.clientX - dragStart.x) / cam.zoom;
    cam.y = dragStart.cy - (e.clientY - dragStart.y) / cam.zoom;
    clampCam();
  } else if (pointers.size === 2) {
    const pts = [...pointers.values()];
    const d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    if (pinchDist > 0) zoomAt((pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2, d / pinchDist);
    pinchDist = d;
  } else if (!pointers.size) {
    handleHover(e.clientX, e.clientY);
  }
});
function endPointer(e) {
  pointers.delete(e.pointerId);
  canvas.classList.remove('dragging');
  if (pointers.size < 2) pinchDist = 0;
  if (pointers.size === 1) {
    const pts = [...pointers.values()];
    dragStart = { x: pts[0].x, y: pts[0].y, cx: cam.x, cy: cam.y };
  } else dragStart = null;
  if (e.type === 'pointerup' && moved < 6) handleClick(e.clientX, e.clientY);
}
canvas.addEventListener('pointerup', endPointer);
canvas.addEventListener('pointercancel', endPointer);
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0012));
}, { passive: false });

/* ---------------- backend state ---------------- */
let prevState = null, curState = null;
let backendLive = false;

async function fetchWorld() {
  const r = await fetch('/api/world');
  world = await r.json();
  prepareWorld();
  fitCamera();
  document.querySelector('#hud h1').textContent = world.name;
  document.title = world.name + ' — City Energy Analysis';
  document.getElementById('statBldg').textContent = world.buildings.length;
}
async function pollState() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    s.recvT = performance.now();
    prevState = curState || s;
    curState = s;
    setBackend(true);
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
function frameState() {
  if (!curState) return null;
  if (!prevState || prevState === curState) return curState;
  const span = Math.max(1, curState.recvT - prevState.recvT);
  // per-entity lerp from prev -> cur, extrapolating slightly past t=1
  const t = clamp((performance.now() - curState.recvT) / span, 0, 1.5);
  const out = {
    clock_min: lerp(prevState.clock_min, curState.clock_min, t),
    total_load_kw: curState.total_load_kw,
    cars: [], people: []
  };
  for (let i = 0; i < curState.cars.length; i++) {
    const a = prevState.cars[i] || curState.cars[i], b = curState.cars[i];
    out.cars.push({ ...b, x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) });
  }
  for (let i = 0; i < curState.people.length; i++) {
    const a = prevState.people[i] || curState.people[i], b = curState.people[i];
    out.people.push({ ...b, x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) });
  }
  return out;
}

/* ================================================================
   STATIC WORLD PREP — iso polygons, Path2D ground layers, wall faces
   ================================================================ */
const ground = { layers: [] };          // [{path, fill | stroke, width, dash}]

function isoPath(points, close) {
  const p = new Path2D();
  points.forEach(([wx, wy], i) => {
    const x = isoX(wx, wy), y = isoY(wx, wy);
    i ? p.lineTo(x, y) : p.moveTo(x, y);
  });
  if (close) p.closePath();
  return p;
}

function pointInPoly(px, py, poly) {     // poly = [[x,y],...] (any consistent units)
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function prepareWorld() {
  // --- iso bounds over everything ---
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  const acc = (wx, wy) => {
    const x = isoX(wx, wy), y = isoY(wx, wy);
    if (x < x0) x0 = x; if (x > x1) x1 = x;
    if (y < y0) y0 = y; if (y > y1) y1 = y;
  };
  for (const b of world.buildings) for (const [wx, wy] of b.polygon) acc(wx, wy);
  for (const r of world.roads) for (const [wx, wy] of r.points) acc(wx, wy);
  isoBounds = { x0: x0 - 60, y0: y0 - 160, x1: x1 + 60, y1: y1 + 60 };

  // --- ground layers (drawn back to front each frame, vector Path2D) ---
  const L = ground.layers;
  L.length = 0;
  // grass disk slightly beyond the data radius
  const disk = new Path2D();
  const R = world.radius_m * 1.12;
  for (let k = 0; k <= 64; k++) {
    const a = k / 64 * Math.PI * 2;
    const x = isoX(Math.cos(a) * R, Math.sin(a) * R), y = isoY(Math.cos(a) * R, Math.sin(a) * R);
    k ? disk.lineTo(x, y) : disk.moveTo(x, y);
  }
  disk.closePath();
  L.push({ path: disk, fill: '#84bb68' });
  for (const poly of world.parks) L.push({ path: isoPath(poly, true), fill: '#79b563' });
  for (const poly of world.water) L.push({ path: isoPath(poly, true), fill: '#4f8fd0' });
  // footways under roads; widths are meters -> iso px (mean of HW/HH axes)
  const w2px = m => m * (HW + HH);
  for (const r of world.roads) {
    if (!r.drivable) L.push({ path: isoPath(r.points, false), stroke: '#cdc9bd', width: w2px(r.width) });
  }
  for (const r of world.roads) {
    if (r.drivable) L.push({ path: isoPath(r.points, false), stroke: '#4a4c52', width: w2px(r.width) });
  }
  for (const r of world.roads) {
    if (r.drivable && r.width >= 5) {
      L.push({ path: isoPath(r.points, false), stroke: 'rgba(240,220,130,0.65)', width: 1.6, dash: [9, 9] });
    }
  }

  // --- buildings: iso polygon, depth, bbox, visible wall faces ---
  for (const b of world.buildings) {
    b.iso = b.polygon.map(([wx, wy]) => [isoX(wx, wy), isoY(wx, wy)]);
    b.H = b.floors * FLOOR_H;
    b.depth = Math.max(...b.polygon.map(([wx, wy]) => wx + wy));
    const xs = b.iso.map(p => p[0]), ys = b.iso.map(p => p[1]);
    b.bb = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys) - b.H, y1: Math.max(...ys) };
    b.palette = PALETTES[b.type][b.id % PALETTES[b.type].length];
    // visible walls: edges whose outward normal projects "toward" the viewer
    b.walls = [];
    const n = b.polygon.length;
    for (let i = 0; i < n; i++) {
      const [ax, ay] = b.polygon[i], [bx, by] = b.polygon[(i + 1) % n];
      const ex = bx - ax, ey = by - ay;
      const len = Math.hypot(ex, ey);
      if (len < 0.5) continue;
      let nx = ey / len, ny = -ex / len;             // candidate outward normal
      const mx = (ax + bx) / 2 + nx * 0.3, my = (ay + by) / 2 + ny * 0.3;
      if (pointInPoly(mx, my, b.polygon)) { nx = -nx; ny = -ny; }
      if (nx + ny <= 0) continue;                    // back-facing in iso view
      b.walls.push({ i, len, u: nx / (Math.abs(nx) + Math.abs(ny)) });
    }
    b.roofPath = null;                               // built lazily below
  }
  world.buildings.sort((a, b) => a.depth - b.depth);

  // --- lamps / signals as depth-sorted props ---
  world.props = [];
  for (const [wx, wy] of world.lamps) {
    world.props.push({ kind: 'lamp', wx, wy, depth: wx + wy, ix: isoX(wx, wy), iy: isoY(wx, wy) });
  }
  for (const s of world.signals) {
    world.props.push({ kind: 'signal', wx: s.x, wy: s.y, phase: s.phase_offset, depth: s.x + s.y, ix: isoX(s.x, s.y), iy: isoY(s.x, s.y) });
  }
}
/* ================================================================
   DRAWING
   ================================================================ */
function drawBuilding(b, withWindows) {
  const lift = b.H;
  // walls (each visible edge: quad from base edge to raised edge)
  for (const w of b.walls) {
    const [x1, y1] = b.iso[w.i], [x2, y2] = b.iso[(w.i + 1) % b.iso.length];
    const base = w.u > 0 ? b.palette[1] : b.palette[0];
    ctx.fillStyle = shade(base, 0.92 + 0.10 * Math.abs(w.u) * (w.u > 0 ? -0.8 : 0.6));
    ctx.beginPath();
    ctx.moveTo(x1, y1 - lift); ctx.lineTo(x2, y2 - lift);
    ctx.lineTo(x2, y2); ctx.lineTo(x1, y1);
    ctx.closePath(); ctx.fill();
    if (withWindows && w.len >= 4) drawWindows(b, w, x1, y1, x2, y2);
  }
  // roof
  ctx.beginPath();
  b.iso.forEach(([x, y], i) => i ? ctx.lineTo(x, y - lift) : ctx.moveTo(x, y - lift));
  ctx.closePath();
  ctx.fillStyle = shade(b.palette[1], 1.18);
  ctx.fill();
  ctx.strokeStyle = 'rgba(0,0,0,0.25)';
  ctx.lineWidth = 1;
  ctx.stroke();
}
function drawWindows(b, w, x1, y1, x2, y2) {
  const wr = mulberry32(b.id * 2654435761 + w.i * 97);
  const cols = clamp(Math.floor(w.len / 3), 1, 9);
  const ex = x2 - x1, ey = y2 - y1;
  const winFill = ['rgba(40,60,90,0.85)', 'rgba(120,160,200,0.8)'];
  for (let f = 0; f < b.floors; f++) {
    const wy = -(f * FLOOR_H) - FLOOR_H * 0.62 - 2;
    for (let c = 0; c < cols; c++) {
      const t0 = (c + 0.25) / cols, t1 = (c + 0.75) / cols;
      ctx.fillStyle = winFill[Math.floor(wr() * 2)];
      ctx.beginPath();
      ctx.moveTo(x1 + ex * t0, y1 + ey * t0 + wy);
      ctx.lineTo(x1 + ex * t1, y1 + ey * t1 + wy);
      ctx.lineTo(x1 + ex * t1, y1 + ey * t1 + wy + FLOOR_H * 0.5);
      ctx.lineTo(x1 + ex * t0, y1 + ey * t0 + wy + FLOOR_H * 0.5);
      ctx.closePath(); ctx.fill();
    }
  }
}

function drawCar(c) {
  const ix = isoX(c.x, c.y), iy = isoY(c.x, c.y);
  const hx = c.hx, hy = c.hy;                       // world heading (unit)
  const px = -hy, py = hx;                          // world perpendicular
  const hl = 2.3, hw = 1.0, bh = 7;                 // half-length/width m, body height px
  const P = (l, w) => [isoX(c.x + hx * l + px * w, c.y + hy * l + py * w),
                       isoY(c.x + hx * l + px * w, c.y + hy * l + py * w)];
  const cor = [P(hl, hw), P(hl, -hw), P(-hl, -hw), P(-hl, hw)];
  ctx.fillStyle = 'rgba(0,0,0,0.25)';
  ctx.beginPath(); ctx.ellipse(ix, iy, 14, 6, 0, 0, 7); ctx.fill();
  const faces = [[0, 1], [1, 2], [2, 3], [3, 0]]
    .map(([a, b]) => ({ a: cor[a], b: cor[b], my: (cor[a][1] + cor[b][1]) / 2 }))
    .sort((f, g) => f.my - g.my);
  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    ctx.fillStyle = shade(c.color, i < 2 ? 0.7 : 0.88);
    ctx.beginPath();
    ctx.moveTo(f.a[0], f.a[1] - bh); ctx.lineTo(f.b[0], f.b[1] - bh);
    ctx.lineTo(f.b[0], f.b[1]); ctx.lineTo(f.a[0], f.a[1]);
    ctx.closePath(); ctx.fill();
  }
  ctx.fillStyle = c.color;
  ctx.beginPath();
  ctx.moveTo(cor[0][0], cor[0][1] - bh); ctx.lineTo(cor[1][0], cor[1][1] - bh);
  ctx.lineTo(cor[2][0], cor[2][1] - bh); ctx.lineTo(cor[3][0], cor[3][1] - bh);
  ctx.closePath(); ctx.fill();
  // cabin
  const C = (l, w) => P(l, w).map((v, k) => v - (k ? bh + 4 : 0));
  const c1 = C(hl * 0.4, hw * 0.7), c2 = C(hl * 0.4, -hw * 0.7),
        c3 = C(-hl * 0.6, -hw * 0.7), c4 = C(-hl * 0.6, hw * 0.7);
  ctx.fillStyle = '#aac4dd';
  ctx.beginPath();
  ctx.moveTo(c1[0], c1[1]); ctx.lineTo(c2[0], c2[1]);
  ctx.lineTo(c3[0], c3[1]); ctx.lineTo(c4[0], c4[1]);
  ctx.closePath(); ctx.fill();
}

const walkPhases = new Map();           // person id -> {phase, lastX, lastY}
function drawPerson(p) {
  const ix = isoX(p.x, p.y), iy = isoY(p.x, p.y);
  let st = walkPhases.get(p.id);
  if (!st) { st = { phase: Math.random() * 7, lastX: p.x, lastY: p.y }; walkPhases.set(p.id, st); }
  st.phase += Math.hypot(p.x - st.lastX, p.y - st.lastY) * 4;
  st.lastX = p.x; st.lastY = p.y;
  const bob = Math.sin(st.phase) * 1.2;
  ctx.fillStyle = 'rgba(0,0,0,0.25)';
  ctx.beginPath(); ctx.ellipse(ix, iy, 6, 3, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = '#2c3038'; ctx.lineWidth = 2; ctx.lineCap = 'round';
  const lp = Math.sin(st.phase) * 2.5;
  ctx.beginPath();
  ctx.moveTo(ix - 1.5, iy - 8 + bob); ctx.lineTo(ix - 1.5 + lp, iy);
  ctx.moveTo(ix + 1.5, iy - 8 + bob); ctx.lineTo(ix + 1.5 - lp, iy);
  ctx.stroke();
  ctx.fillStyle = p.shirt;
  ctx.beginPath(); ctx.roundRect(ix - 3.5, iy - 15 + bob, 7, 9, 2.5); ctx.fill();
  ctx.fillStyle = '#f0c8a0';
  ctx.beginPath(); ctx.arc(ix, iy - 18 + bob, 3.6, 0, 7); ctx.fill();
  ctx.fillStyle = '#2a2a2e';
  ctx.beginPath(); ctx.arc(ix, iy - 19.2 + bob, 3.1, Math.PI, 2 * Math.PI); ctx.fill();
}

function drawLamp(d) {
  ctx.strokeStyle = '#3c4148'; ctx.lineWidth = 2; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(d.ix, d.iy); ctx.lineTo(d.ix, d.iy - 22); ctx.stroke();
  ctx.fillStyle = '#c9ccd2';
  ctx.beginPath(); ctx.arc(d.ix, d.iy - 24, 2.6, 0, 7); ctx.fill();
}
const SIG_DUR = [9, 2.5, 9, 2.5];       // visual cycle only (v1: cars don't obey)
const SIG_CYCLE = SIG_DUR.reduce((a, b) => a + b);
function drawSignal(d, nowSec) {
  let u = (nowSec + d.phase) % SIG_CYCLE, phase = 0;
  for (let p = 0; p < 4; p++) { if (u < SIG_DUR[p]) { phase = p; break; } u -= SIG_DUR[p]; }
  const nsC = phase === 0 ? '#41d05c' : phase === 1 ? '#ffb13d' : '#e84545';
  const ewC = phase === 2 ? '#41d05c' : phase === 3 ? '#ffb13d' : '#e84545';
  ctx.strokeStyle = '#33373d'; ctx.lineWidth = 2.5; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(d.ix, d.iy); ctx.lineTo(d.ix, d.iy - 28); ctx.stroke();
  ctx.fillStyle = '#23262b';
  ctx.fillRect(d.ix - 7, d.iy - 36, 14, 9);
  ctx.fillStyle = nsC; ctx.beginPath(); ctx.arc(d.ix - 3.5, d.iy - 31.5, 2.6, 0, 7); ctx.fill();
  ctx.fillStyle = ewC; ctx.beginPath(); ctx.arc(d.ix + 3.5, d.iy - 31.5, 2.6, 0, 7); ctx.fill();
}

/* ---------------- render loop ---------------- */
function render(nowMs) {
  requestAnimationFrame(render);
  if (!world) return;
  const nowSec = nowMs / 1000;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  const grad = ctx.createLinearGradient(0, 0, 0, Hh);
  grad.addColorStop(0, '#8ec8f2'); grad.addColorStop(1, '#cfe9ff');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, Hh);

  ctx.setTransform(DPR * cam.zoom, 0, 0, DPR * cam.zoom,
    DPR * (W / 2 - cam.x * cam.zoom), DPR * (Hh / 2 - cam.y * cam.zoom));
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  for (const l of ground.layers) {
    if (l.fill) { ctx.fillStyle = l.fill; ctx.fill(l.path); }
    else {
      ctx.strokeStyle = l.stroke; ctx.lineWidth = l.width;
      if (l.dash) ctx.setLineDash(l.dash);
      ctx.stroke(l.path);
      if (l.dash) ctx.setLineDash([]);
    }
  }

  // visible viewport in iso coords (margin for tall buildings)
  const vx0 = cam.x - W / (2 * cam.zoom) - 80, vx1 = cam.x + W / (2 * cam.zoom) + 80;
  const vy0 = cam.y - Hh / (2 * cam.zoom) - 160, vy1 = cam.y + Hh / (2 * cam.zoom) + 80;
  const withWindows = cam.zoom >= 0.7;

  const s = frameState();
  const items = [];
  for (const b of world.buildings) {
    if (b.bb.x1 < vx0 || b.bb.x0 > vx1 || b.bb.y1 < vy0 || b.bb.y0 > vy1) continue;
    items.push({ depth: b.depth, kind: 'bldg', b });
  }
  for (const d of world.props) {
    if (d.ix < vx0 || d.ix > vx1 || d.iy < vy0 || d.iy > vy1) continue;
    items.push({ depth: d.depth, kind: d.kind, d });
  }
  if (s) {
    for (const c of s.cars) items.push({ depth: c.x + c.y, kind: 'car', c });
    for (const p of s.people) items.push({ depth: p.x + p.y, kind: 'person', p });
  }
  items.sort((a, b) => a.depth - b.depth);
  for (const it of items) {
    if (it.kind === 'bldg') drawBuilding(it.b, withWindows);
    else if (it.kind === 'lamp') drawLamp(it.d);
    else if (it.kind === 'signal') drawSignal(it.d, nowSec);
    else if (it.kind === 'car') drawCar(it.c);
    else drawPerson(it.p);
  }
  updateHUD(s);
}

let lastHud = 0;
function updateHUD(s) {
  const now = performance.now();
  if (!s || now - lastHud < 250) return;
  lastHud = now;
  const m = Math.floor(((s.clock_min % 1440) + 1440) % 1440);
  document.getElementById('clockText').textContent =
    String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
  const hour = m / 60;
  document.getElementById('clockGlyph').textContent = (hour >= 6.5 && hour < 18.5) ? '☀️' : '🌙';
  document.getElementById('statCars').textContent = s.cars.length;
  document.getElementById('statPop').textContent = s.people.length;
  const kw = s.total_load_kw;
  document.getElementById('statLoad').textContent =
    kw >= 1000 ? (kw / 1000).toFixed(1) + ' MW' : kw + ' kW';
}

/* ---------------- hit testing / tooltip / click ---------------- */
function hitTest(sx, sy) {
  if (!world || !curState) return null;
  const pt = screenToIso(sx, sy);
  const s = frameState();
  for (const p of s.people) {
    const d = Math.hypot(pt.ix - isoX(p.x, p.y), pt.iy - (isoY(p.x, p.y) - 12));
    if (d < 14 / Math.min(1, cam.zoom)) return { kind: 'person', e: p };
  }
  for (const c of s.cars) {
    const d = Math.hypot(pt.ix - isoX(c.x, c.y), pt.iy - (isoY(c.x, c.y) - 5));
    if (d < 18 / Math.min(1, cam.zoom)) return { kind: 'car', e: c };
  }
  // buildings front-to-back; sample base / mid / roof of the extrusion
  for (let i = world.buildings.length - 1; i >= 0; i--) {
    const b = world.buildings[i];
    if (pt.ix < b.bb.x0 || pt.ix > b.bb.x1 || pt.iy < b.bb.y0 || pt.iy > b.bb.y1) continue;
    for (const k of [0, b.H / 2, b.H]) {
      if (pointInPoly(pt.ix, pt.iy + k, b.iso)) return { kind: 'building', e: b };
    }
  }
  return null;
}
const tooltip = document.getElementById('tooltip');
function handleHover(sx, sy) {
  const hit = hitTest(sx, sy);
  if (hit) {
    canvas.classList.add('pointing');
    tooltip.style.display = 'block';
    tooltip.style.left = (sx + 14) + 'px';
    tooltip.style.top = (sy + 10) + 'px';
    tooltip.textContent = hit.e.name;
  } else {
    canvas.classList.remove('pointing');
    tooltip.style.display = 'none';
  }
}
function handleClick(sx, sy) {
  const hit = hitTest(sx, sy);
  if (hit) openDetail(hit.kind, hit.e.id);
  else closePopup();
}

/* ---------------- detail popup (backend results) ---------------- */
const popup = document.getElementById('popup');
let openKind = null, openId = null, refreshTimer = null;

async function openDetail(kind, id) {
  openKind = kind; openId = id;
  await refreshDetail();
  popup.classList.add('open');
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshDetail, DETAIL_REFRESH_MS);
}
function closePopup() {
  popup.classList.remove('open');
  openKind = openId = null;
  clearInterval(refreshTimer);
}
document.getElementById('popupClose').addEventListener('click', closePopup);
window.addEventListener('keydown', e => { if (e.key === 'Escape') closePopup(); });

const TYPE_LABEL = { res: 'Residential', office: 'Office', shop: 'Shop' };
async function refreshDetail() {
  if (!openKind) return;
  let d;
  try {
    const r = await fetch(`/api/${openKind}/${openId}`);
    if (!r.ok) return closePopup();
    d = await r.json();
  } catch { return; }
  const title = document.getElementById('popupTitle');
  const sub = document.getElementById('popupSub');
  const nowEl = document.getElementById('popupNow');
  title.textContent = d.name;
  if (openKind === 'building') {
    sub.textContent = `${TYPE_LABEL[d.type]} · ${d.floors} floor${d.floors > 1 ? 's' : ''} · ${d.area_m2} m² — electricity, last 24 h`;
    renderChart(d.history_kw, {
      yStep: 50, color: '#ffc94d', fill: 'rgba(255,201,77,0.16)',
      xTicks: timeTicks((d.history_kw.length - 1) * d.sample_min, 6)
    });
    nowEl.innerHTML = `Now: <b>${Math.round(d.load_kw)}</b> kW · occupancy ${Math.round(d.occupancy * 100)}%`;
  } else if (openKind === 'car') {
    sub.textContent = 'Vehicle telemetry — speed, last 60 s';
    renderChart(d.history_kmh, {
      yStep: 10, yMin: 20, capacity: d.capacity,
      color: '#5fd4a8', fill: 'rgba(95,212,168,0.16)',
      xTicks: secTicks(d.capacity * d.sample_dt_s, 4)
    });
    nowEl.innerHTML = `Now: <b>${Math.round(d.speed_kmh)}</b> km/h · ${d.distance_km_today} km driven`;
  } else {
    sub.textContent = 'Citizen activity — steps per hour, last 24 h';
    renderChart(d.history_steps_h, {
      yStep: 1000, yMin: 2000, color: '#7aa7ff', fill: 'rgba(122,167,255,0.16)',
      xTicks: timeTicks((d.history_steps_h.length - 1) * d.sample_min, 6)
    });
    nowEl.innerHTML = `${d.activity} · <b>${d.steps_per_h.toLocaleString()}</b> steps/h · ${d.distance_km_today} km today`;
  }
}

/* ---------------- chart (ported from the design reference) ---------------- */
function renderChart(vals, opt) {
  const cv = document.getElementById('chart');
  const g = cv.getContext('2d');
  const cw = cv.width, ch = cv.height;
  g.clearRect(0, 0, cw, ch);
  if (!vals.length) return;
  const padL = 56, padR = 16, padT = 14, padB = 34;
  const pw = cw - padL - padR, ph = ch - padT - padB;
  let vmax = opt.yMin || 10;
  for (const v of vals) if (v > vmax) vmax = v;
  vmax = Math.ceil(vmax / opt.yStep) * opt.yStep;
  g.strokeStyle = 'rgba(255,255,255,0.12)'; g.lineWidth = 1;
  g.fillStyle = '#aab4cc'; g.font = '20px system-ui, sans-serif'; g.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const y = padT + ph - (ph * i) / 4;
    g.beginPath(); g.moveTo(padL, y); g.lineTo(cw - padR, y); g.stroke();
    g.fillText(Math.round((vmax * i) / 4), padL - 8, y + 7);
  }
  g.textAlign = 'center';
  for (const t of opt.xTicks) g.fillText(t.label, padL + pw * t.frac, ch - 10);
  const cap = opt.capacity || vals.length;
  const X = i => padL + pw * ((cap - vals.length + i) / Math.max(1, cap - 1));
  const Y = v => padT + ph - (ph * v) / vmax;
  g.beginPath();
  for (let i = 0; i < vals.length; i++) i ? g.lineTo(X(i), Y(vals[i])) : g.moveTo(X(i), Y(vals[i]));
  g.strokeStyle = opt.color; g.lineWidth = 3; g.stroke();
  g.lineTo(X(vals.length - 1), padT + ph); g.lineTo(X(0), padT + ph); g.closePath();
  g.fillStyle = opt.fill; g.fill();
  g.fillStyle = opt.color;
  g.beginPath(); g.arc(X(vals.length - 1), Y(vals[vals.length - 1]), 6, 0, 7); g.fill();
}
function timeTicks(windowMin, n) {
  const clockMin = curState ? curState.clock_min : 0;
  const ticks = [];
  for (let k = 0; k <= n; k++) {
    const m = clockMin - windowMin * (1 - k / n);
    const mm = ((m % 1440) + 1440) % 1440;
    ticks.push({
      frac: k / n,
      label: String(Math.floor(mm / 60)).padStart(2, '0') + ':' +
             String(Math.floor(mm % 60)).padStart(2, '0')
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

/* ---------------- boot ---------------- */
window.cityDebug = { worldToScreen, cam, get world() { return world; }, get state() { return curState; } };
setTimeout(() => document.getElementById('toast').classList.add('hide'), 9000);
resize();
fetchWorld().then(() => { fitCamera(); pollState(); requestAnimationFrame(render); });
