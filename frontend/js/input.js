import { cam, screenToIso, screenToWorld, clampCam, zoomAt } from './camera.js';
import { SNAP_M } from './config.js';
import { isoX, isoY, pointInPoly, clamp } from './math.js';
import { appState, frameState } from './state.js';
import { sendEdit } from './api.js';
import { openDetail, closePopup } from './ui/popup.js';
import { setTool } from './ui/toolbar.js';

const canvas = document.getElementById('city');
const tooltip = document.getElementById('tooltip');
const pointers = new Map();
let dragStart = null, pinchDist = 0, moved = 0;
const snap = v => Math.round(v / SNAP_M) * SNAP_M;

export function setupInput() {
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0012));
  }, { passive: false });
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      closePopup();
      appState.roadDraft = null;
      appState.bldgDraft = null;
      if (appState.tool) setTool(appState.tool);
    }
  });
}

function onPointerDown(e) {
  try { canvas.setPointerCapture(e.pointerId); } catch {}
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  moved = 0;
  if (pointers.size === 1) {
    if (appState.tool === 'road' || appState.tool === 'bldg') {
      const w = screenToWorld(e.clientX, e.clientY);
      const d = { x0: snap(w.wx), y0: snap(w.wy), x1: snap(w.wx), y1: snap(w.wy) };
      if (appState.tool === 'road') appState.roadDraft = d;
      else appState.bldgDraft = d;
      dragStart = null;
    } else {
      dragStart = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y };
      canvas.classList.add('dragging');
    }
  } else if (pointers.size === 2) {
    const pts = [...pointers.values()];
    pinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    dragStart = null;
    appState.roadDraft = null;
    appState.bldgDraft = null;
  }
}

function onPointerMove(e) {
  const p = pointers.get(e.pointerId);
  if (p) {
    moved += Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y);
    p.x = e.clientX; p.y = e.clientY;
  }
  const draft = appState.roadDraft || appState.bldgDraft;
  if (pointers.size === 1 && draft) {
    const w = screenToWorld(e.clientX, e.clientY);
    draft.x1 = snap(w.wx); draft.y1 = snap(w.wy);
  } else if (pointers.size === 1 && dragStart) {
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
}

function endPointer(e) {
  pointers.delete(e.pointerId);
  canvas.classList.remove('dragging');
  if (pointers.size < 2) pinchDist = 0;
  if (appState.roadDraft && pointers.size === 0) {
    const rd = appState.roadDraft;
    if (e.type === 'pointerup' && (rd.x0 !== rd.x1 || rd.y0 !== rd.y1)) {
      sendEdit({ op: 'add_road', class: 'residential',
                 points: [[rd.x0, rd.y0], [rd.x1, rd.y1]] });
    }
    appState.roadDraft = null;
    return;
  }
  if (appState.bldgDraft && pointers.size === 0) {
    const bd = appState.bldgDraft;
    const x0 = Math.min(bd.x0, bd.x1), x1 = Math.max(bd.x0, bd.x1);
    const y0 = Math.min(bd.y0, bd.y1), y1 = Math.max(bd.y0, bd.y1);
    if (e.type === 'pointerup' && x1 - x0 >= SNAP_M && y1 - y0 >= SNAP_M) {
      sendEdit({ op: 'add_building', type: appState.bldgType,
                 polygon: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] });
    }
    appState.bldgDraft = null;
    return;
  }
  if (pointers.size === 1) {
    const pts = [...pointers.values()];
    dragStart = { x: pts[0].x, y: pts[0].y, cx: cam.x, cy: cam.y };
  } else dragStart = null;
  if (e.type === 'pointerup' && moved < 6) handleClick(e.clientX, e.clientY);
}

function hitTest(sx, sy) {
  const { world, cur } = appState;
  if (!world || !cur) return null;
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
  for (let i = world.buildings.length - 1; i >= 0; i--) {
    const b = world.buildings[i];
    if (pt.ix < b.bb.x0 || pt.ix > b.bb.x1 || pt.iy < b.bb.y0 || pt.iy > b.bb.y1) continue;
    for (const k of [0, b.H / 2, b.H]) {
      if (pointInPoly(pt.ix, pt.iy + k, b.iso)) return { kind: 'building', e: b };
    }
  }
  return null;
}

function segDist(px, py, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 ? clamp(((px - a[0]) * dx + (py - a[1]) * dy) / len2, 0, 1) : 0;
  return Math.hypot(px - (a[0] + dx * t), py - (a[1] + dy * t));
}

function roadHit(wx, wy) {
  const { world } = appState;
  if (!world) return null;
  let best = null, bestD = 1e9;
  for (const r of world.roads) {
    for (let i = 0; i + 1 < r.points.length; i++) {
      const d = segDist(wx, wy, r.points[i], r.points[i + 1]);
      if (d < bestD) { bestD = d; best = r; }
    }
  }
  return best && bestD <= Math.max(best.width / 2, 2.5) + 1.5 ? best : null;
}

function buildingHit(wx, wy) {
  const { world } = appState;
  if (!world) return null;
  for (let i = world.buildings.length - 1; i >= 0; i--)
    if (pointInPoly(wx, wy, world.buildings[i].polygon)) return world.buildings[i];
  return null;
}

function handleHover(sx, sy) {
  const { tool } = appState;
  if (tool === 'road' || tool === 'bldg') {
    canvas.classList.remove('pointing');
    tooltip.style.display = 'none';
    return;
  }
  if (tool === 'dozer') {
    const { wx, wy } = screenToWorld(sx, sy);
    const b = buildingHit(wx, wy);
    const r = b ? null : roadHit(wx, wy);
    if (b || r) {
      tooltip.style.display = 'block';
      tooltip.style.left = (sx + 14) + 'px';
      tooltip.style.top = (sy + 10) + 'px';
      tooltip.textContent = '🧨 ' + (b ? b.name : (r.name || r.class));
    } else tooltip.style.display = 'none';
    return;
  }
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
  const { tool } = appState;
  if (tool === 'car' || tool === 'person') {
    const { wx, wy } = screenToWorld(sx, sy);
    sendEdit({ op: tool === 'car' ? 'spawn_car' : 'spawn_person',
               x: Math.round(wx * 10) / 10, y: Math.round(wy * 10) / 10 });
    return;
  }
  if (tool === 'dozer') {
    const { wx, wy } = screenToWorld(sx, sy);
    const b = buildingHit(wx, wy);
    if (b) sendEdit({ op: 'remove_building', id: b.id });
    else {
      const r = roadHit(wx, wy);
      if (r) sendEdit({ op: 'remove_road', id: r.id });
    }
    return;
  }
  if (tool === 'road' || tool === 'bldg') return;
  const hit = hitTest(sx, sy);
  if (hit) openDetail(hit.kind, hit.e.id);
  else closePopup();
}
