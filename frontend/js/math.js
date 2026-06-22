import { HW, HH } from './config.js';

export const lerp = (a, b, t) => a + (b - a) * t;
export const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;
export const isoX = (wx, wy) => (wx - wy) * HW;
export const isoY = (wx, wy) => (wx + wy) * HH;

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hexToRgb(h) {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

export function shade(hex, f) {
  const c = hexToRgb(hex).map(v => clamp(Math.round(v * f), 0, 255));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function lerpColor(hex1, hex2, t) {
  const [r1, g1, b1] = hexToRgb(hex1), [r2, g2, b2] = hexToRgb(hex2);
  return `rgb(${Math.round(lerp(r1, r2, t))},${Math.round(lerp(g1, g2, t))},${Math.round(lerp(b1, b2, t))})`;
}

export function euiColor(norm) {
  if (norm < 0.5) return lerpColor('#22c55e', '#facc15', norm * 2);
  return lerpColor('#facc15', '#ef4444', (norm - 0.5) * 2);
}

// Retrofit-savings ramp: norm in [-1, 1]. Positive (energy cut) → green,
// negative (worse) → red, 0 → neutral slate.
export function savingsColor(norm) {
  if (norm >= 0) return lerpColor('#5b6b80', '#22c55e', clamp(norm, 0, 1));
  return lerpColor('#5b6b80', '#ef4444', clamp(-norm, 0, 1));
}

export function nightFactor(clockMin) {
  const h = ((clockMin % 1440) + 1440) % 1440 / 60;
  if (h >= 7 && h < 17)  return 0;
  if (h >= 21 || h < 3)  return 1;
  if (h < 7)             return 1 - (h - 3) / 4;
  return (h - 17) / 4;
}

export function pointInPoly(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
