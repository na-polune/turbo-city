import { ZOOM_MIN, ZOOM_MAX, HW, HH } from './config.js';
import { clamp } from './math.js';

export const cam = { x: 0, y: 0, zoom: 0.3 };
export const viewport = { W: 0, Hh: 0, DPR: 1 };
let isoBounds = null;

export function setIsoBounds(bounds) { isoBounds = bounds; }
export function getIsoBounds() { return isoBounds; }

const canvas = document.getElementById('city');

export function resize() {
  viewport.DPR = Math.min(2, window.devicePixelRatio || 1);
  viewport.W = window.innerWidth;
  viewport.Hh = window.innerHeight;
  canvas.width = Math.round(viewport.W * viewport.DPR);
  canvas.height = Math.round(viewport.Hh * viewport.DPR);
}
window.addEventListener('resize', resize);

export function fitCamera() {
  const { W, Hh } = viewport;
  const bw = isoBounds.x1 - isoBounds.x0, bh = isoBounds.y1 - isoBounds.y0;
  cam.x = (isoBounds.x0 + isoBounds.x1) / 2;
  cam.y = (isoBounds.y0 + isoBounds.y1) / 2;
  cam.zoom = clamp(Math.min(W / bw, Hh / bh) * 1.12, ZOOM_MIN, ZOOM_MAX);
}

export function screenToIso(sx, sy) {
  const { W, Hh } = viewport;
  return { ix: (sx - W / 2) / cam.zoom + cam.x, iy: (sy - Hh / 2) / cam.zoom + cam.y };
}

export function isoToScreen(ix, iy) {
  const { W, Hh } = viewport;
  return { sx: (ix - cam.x) * cam.zoom + W / 2, sy: (iy - cam.y) * cam.zoom + Hh / 2 };
}

export function worldToScreen(wx, wy) {
  return isoToScreen((wx - wy) * HW, (wx + wy) * HH);
}

export function screenToWorld(sx, sy) {
  const { ix, iy } = screenToIso(sx, sy);
  return { wx: (ix / HW + iy / HH) / 2, wy: (iy / HH - ix / HW) / 2 };
}

export function clampCam() {
  cam.zoom = clamp(cam.zoom, ZOOM_MIN, ZOOM_MAX);
  if (isoBounds) {
    cam.x = clamp(cam.x, isoBounds.x0, isoBounds.x1);
    cam.y = clamp(cam.y, isoBounds.y0, isoBounds.y1);
  }
}

export function zoomAt(sx, sy, factor) {
  const before = screenToIso(sx, sy);
  cam.zoom = clamp(cam.zoom * factor, ZOOM_MIN, ZOOM_MAX);
  const after = screenToIso(sx, sy);
  cam.x += before.ix - after.ix;
  cam.y += before.iy - after.iy;
  clampCam();
}
