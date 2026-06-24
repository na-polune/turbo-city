import { cam, viewport } from './camera.js';
import { HW, HH, FLOOR_H } from './config.js';
import { lerp, clamp, lerpColor, shade, mulberry32, nightFactor, isoX, isoY } from './math.js';
import { overlayColorFor } from './views.js';
import { appState, frameState } from './state.js';
import { ground } from './world-prep.js';
import { updateHUD } from './ui/hud.js';

const canvas = document.getElementById('city');
const ctx = canvas.getContext('2d');

let nightF = 0;
let nightClockMin = 9 * 60;
const walkPhases = new Map();

const SIG_DUR = [9, 2.5, 9, 2.5];
const SIG_CYCLE = SIG_DUR.reduce((a, b) => a + b);

function drawBuilding(b, withWindows) {
  const lift = b.H;
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
  ctx.beginPath();
  b.iso.forEach(([x, y], i) => i ? ctx.lineTo(x, y - lift) : ctx.moveTo(x, y - lift));
  ctx.closePath();
  const overlay = overlayColorFor(b.id);
  if (overlay) {
    ctx.fillStyle = overlay;
    ctx.globalAlpha = 0.85;
    ctx.fill();
    ctx.globalAlpha = 1.0;
  } else {
    ctx.fillStyle = shade(b.palette[1], 1.18);
    ctx.fill();
  }
  ctx.strokeStyle = 'rgba(0,0,0,0.25)';
  ctx.lineWidth = 1;
  ctx.stroke();
  const vd = appState.viewMap[b.id];
  if (vd && vd.pv > 0.5) {
    ctx.beginPath();
    b.iso.forEach(([x, y], i) => i ? ctx.lineTo(x, y - lift) : ctx.moveTo(x, y - lift));
    ctx.closePath();
    ctx.fillStyle = `rgba(253,224,71,${Math.min(0.55, vd.pv / 20)})`;
    ctx.fill();
  }
}

function drawWindows(b, w, x1, y1, x2, y2) {
  const wr = mulberry32(b.id * 2654435761 + w.i * 97);
  const cols = clamp(Math.floor(w.len / 3), 1, 9);
  const ex = x2 - x1, ey = y2 - y1;
  const winFill = ['rgba(40,60,90,0.85)', 'rgba(120,160,200,0.8)'];
  const hour = ((nightClockMin % 1440) + 1440) % 1440 / 60;
  const nightRng = mulberry32(b.id * 1234577 + w.i * 113 + Math.floor(hour) * 7919);
  const litProb = nightF < 0.05 ? 0
    : b.type === 'res'        ? (hour >= 18 ? 0.55 : hour < 6 ? 0.06 : 0.25)
    : b.type === 'office'     ? 0.04
    : b.type === 'hospital'   ? 0.55
    : b.type === 'school'     ? (hour >= 7 && hour < 18 ? 0.6 : 0.0)
    : b.type === 'industrial' ? (hour >= 6 && hour < 22 ? 0.4 : 0.1)
    : (hour >= 19 ? 0.0 : 0.35);
  for (let f = 0; f < b.floors; f++) {
    const wy = -(f * FLOOR_H) - FLOOR_H * 0.62 - 2;
    for (let c = 0; c < cols; c++) {
      const t0 = (c + 0.25) / cols, t1 = (c + 0.75) / cols;
      const dayChoice = Math.floor(wr() * 2);
      const isLit = nightRng() < litProb;
      ctx.fillStyle = nightF < 0.05 ? winFill[dayChoice]
        : isLit ? `rgba(255,240,170,${lerp(0.7, 0.92, nightF)})`
        : `rgba(18,22,35,0.9)`;
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
  const hx = c.hx, hy = c.hy;
  const px = -hy, py = hx;
  const hl = 2.3, hw = 1.0, bh = 7;
  const P = (l, w) => [
    isoX(c.x + hx * l + px * w, c.y + hy * l + py * w),
    isoY(c.x + hx * l + px * w, c.y + hy * l + py * w),
  ];
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
  const C = (l, w) => P(l, w).map((v, k) => v - (k ? bh + 4 : 0));
  const c1 = C(hl * 0.4, hw * 0.7), c2 = C(hl * 0.4, -hw * 0.7);
  const c3 = C(-hl * 0.6, -hw * 0.7), c4 = C(-hl * 0.6, hw * 0.7);
  ctx.fillStyle = '#aac4dd';
  ctx.beginPath();
  ctx.moveTo(c1[0], c1[1]); ctx.lineTo(c2[0], c2[1]);
  ctx.lineTo(c3[0], c3[1]); ctx.lineTo(c4[0], c4[1]);
  ctx.closePath(); ctx.fill();
}

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
  if (nightF > 0) {
    const glow = ctx.createRadialGradient(d.ix, d.iy - 24, 0, d.ix, d.iy - 24, 40);
    glow.addColorStop(0, `rgba(255,220,100,${0.50 * nightF})`);
    glow.addColorStop(1, 'rgba(255,180,50,0)');
    ctx.fillStyle = glow;
    ctx.beginPath(); ctx.arc(d.ix, d.iy - 24, 40, 0, Math.PI * 2); ctx.fill();
  }
  ctx.strokeStyle = '#3c4148'; ctx.lineWidth = 2; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(d.ix, d.iy); ctx.lineTo(d.ix, d.iy - 22); ctx.stroke();
  ctx.fillStyle = nightF > 0.15 ? '#ffe89a' : '#c9ccd2';
  ctx.beginPath(); ctx.arc(d.ix, d.iy - 24, 2.6, 0, 7); ctx.fill();
}

function drawRain(state, nowSec) {
  const { W, Hh, DPR } = viewport;
  const heavy = state === 'heavy_rain';
  const drops = heavy ? 280 : 150;
  const speed = heavy ? 500 : 350;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.strokeStyle = heavy ? 'rgba(174,214,241,0.55)' : 'rgba(174,214,241,0.38)';
  ctx.lineWidth = heavy ? 1.5 : 1;
  ctx.beginPath();
  for (let i = 0; i < drops; i++) {
    const x = (i * 137.508) % W;
    const y = ((nowSec * speed + i * (Hh * 1.15 / drops)) % (Hh + 30)) - 15;
    ctx.moveTo(x + 5, y - 10);
    ctx.lineTo(x, y);
  }
  ctx.stroke();
}

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

function render(nowMs) {
  requestAnimationFrame(render);
  const { world, cur: curState, roadDraft, bldgDraft } = appState;
  if (!world) return;
  // When the sim is paused, the world is frozen — only redraw on a fresh state,
  // a recent interaction, or an in-progress draft. Otherwise leave the last
  // frame on screen so an idle paused tab stops burning the GPU.
  const paused = curState && curState.sim_min_per_sec === 0;
  if (paused && !appState.dirty && !roadDraft && !bldgDraft
      && nowMs - appState.lastInteract > 600) return;
  appState.dirty = false;
  const { W, Hh, DPR } = viewport;
  const nowSec = nowMs / 1000;
  nightClockMin = curState ? curState.clock_min : 9 * 60;
  nightF = nightFactor(nightClockMin);

  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  const grad = ctx.createLinearGradient(0, 0, 0, Hh);
  grad.addColorStop(0, lerpColor('#8ec8f2', '#0a1525', nightF));
  grad.addColorStop(1, lerpColor('#cfe9ff', '#1a2e50', nightF));
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, Hh);

  if (nightF > 0) {
    const starRng = mulberry32(42);
    ctx.fillStyle = `rgba(255,255,255,${nightF * 0.85})`;
    for (let i = 0; i < 80; i++) {
      const sx = starRng() * W, sy = starRng() * Hh * 0.55;
      ctx.beginPath(); ctx.arc(sx, sy, starRng() * 0.9 + 0.4, 0, Math.PI * 2); ctx.fill();
    }
  }

  const cWeather = curState && curState.weather;
  if (cWeather && cWeather.cloud_cover > 0.1) {
    ctx.fillStyle = `rgba(160,175,195,${cWeather.cloud_cover * 0.42})`;
    ctx.fillRect(0, 0, W, Hh);
  }

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

  if (roadDraft) {
    ctx.strokeStyle = 'rgba(95,212,168,0.75)';
    ctx.lineWidth = 6 * (HW + HH);
    ctx.setLineDash([16, 10]);
    ctx.beginPath();
    ctx.moveTo(isoX(roadDraft.x0, roadDraft.y0), isoY(roadDraft.x0, roadDraft.y0));
    ctx.lineTo(isoX(roadDraft.x1, roadDraft.y1), isoY(roadDraft.x1, roadDraft.y1));
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (bldgDraft) {
    const x0 = Math.min(bldgDraft.x0, bldgDraft.x1), x1 = Math.max(bldgDraft.x0, bldgDraft.x1);
    const y0 = Math.min(bldgDraft.y0, bldgDraft.y1), y1 = Math.max(bldgDraft.y0, bldgDraft.y1);
    ctx.beginPath();
    [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].forEach(([wx, wy], i) => {
      const x = isoX(wx, wy), y = isoY(wx, wy);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.closePath();
    ctx.fillStyle = 'rgba(255,201,77,0.30)'; ctx.fill();
    ctx.strokeStyle = 'rgba(255,201,77,0.9)'; ctx.lineWidth = 2;
    ctx.setLineDash([8, 6]); ctx.stroke(); ctx.setLineDash([]);
  }

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

  if (nightF > 0) {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.fillStyle = `rgba(5,15,40,${nightF * 0.55})`;
    ctx.fillRect(0, 0, W, Hh);
  }
  if (cWeather && (cWeather.state === 'rain' || cWeather.state === 'heavy_rain')) {
    drawRain(cWeather.state, nowSec);
  }
  updateHUD(s);
}

export function startRenderLoop() {
  requestAnimationFrame(render);
}
