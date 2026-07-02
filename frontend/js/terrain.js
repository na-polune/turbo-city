// Terrain + realistic-ground rendering for the 2.5D canvas renderer.
//
// Three jobs, all optional (style panel), all baked once per world/style change
// so the per-frame cost is a single drawImage:
//   1. Elevation sampling — bilinear over the backend's DEM grid (world.terrain).
//      groundLift(wx, wy) is the vertical screen offset every drawn feature
//      subtracts so the city sits on the terrain (only in relief-capable modes).
//   2. Hillshade mesh — each terrain cell drawn as an iso-projected quad with
//      slope-dependent shading (light from the NW) and an altitude tint.
//   3. Imagery ground — OSM map or Esri satellite tiles warped into the iso
//      plane per cell (two texture-mapped triangles), riding the same relief.
//
// The iso ground plane is an affine image of the world plane, which is what
// makes tile imagery possible without a 3D engine.
import { HW, HH, FLOOR_H } from './config.js';
import { isoX, isoY, hexToRgb, clamp } from './math.js';
import { appState } from './state.js';

export const ELEV_PX_M = FLOOR_H / 3;   // match building scale: FLOOR_H px per 3 m storey

const TILE_PROVIDERS = {
  map: {
    url: (z, x, y) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`,
    attribution: '© OpenStreetMap contributors',
    targetMpp: 1.2,
  },
  satellite: {
    url: (z, x, y) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`,
    attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
    targetMpp: 0.7,
  },
};

let T = null;            // terrain grid from /api/world (or null: flat)
let zRel = null;         // rows of elevation above z_min [m]
let baked = null;        // { canvas, x0, y0, w, h } in iso coords
let bakeSeq = 0;         // cancels stale async bakes
const texCache = new Map();   // ground mode -> { canvas, toTex } imagery texture

export function setTerrain(t) {
  T = t || null;
  zRel = T ? T.z.map(row => row.map(v => v - T.z_min)) : null;
  texCache.clear();      // new world = new imagery
  baked = null;
}

export const hasTerrain = () => !!T;

// Elevation above the world's lowest point [m]; bilinear, clamped to the grid.
export function elevM(wx, wy) {
  if (!T) return 0;
  const gx = clamp((wx - T.x0) / T.cell_m, 0, T.nx - 1.001);
  const gy = clamp((wy - T.y0) / T.cell_m, 0, T.ny - 1.001);
  const i = Math.floor(gx), j = Math.floor(gy);
  const fx = gx - i, fy = gy - j;
  const z00 = zRel[j][i], z10 = zRel[j][i + 1];
  const z01 = zRel[j + 1][i], z11 = zRel[j + 1][i + 1];
  return (z00 * (1 - fx) + z10 * fx) * (1 - fy) + (z01 * (1 - fx) + z11 * fx) * fy;
}

// Vertical screen lift [iso px] applied to everything drawn at (wx, wy).
// Zero in stylized mode (the flat disk can't follow the relief) or with relief off.
export function groundLift(wx, wy) {
  const st = appState.style;
  if (!T || !st || st.ground === 'stylized' || !st.relief) return 0;
  return elevM(wx, wy) * ELEV_PX_M;
}

export const getGroundImage = () => baked;

// ---- imagery tiles ----------------------------------------------------------

function lonLatToTilePx(lon, lat, z) {
  const n = 256 * Math.pow(2, z);
  const la = lat * Math.PI / 180;
  return [
    (lon + 180) / 360 * n,
    (1 - Math.log(Math.tan(la) + 1 / Math.cos(la)) / Math.PI) / 2 * n,
  ];
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('tile failed: ' + src));
    img.src = src;
  });
}

// Fetch the tiles covering the world disk into one texture canvas.
// Returns { canvas, toTex(wx, wy) -> [px, py] }.
async function fetchImagery(world, mode) {
  if (texCache.has(mode)) return texCache.get(mode);
  const prov = TILE_PROVIDERS[mode];
  const [lat0, lon0] = world.center;
  const R = world.radius_m * 1.13;
  const mppAtLat = 156543.03 * Math.cos(lat0 * Math.PI / 180);
  const z = clamp(Math.round(Math.log2(mppAtLat / prov.targetMpp)), 14, 19);
  const mPerDegLon = 111320 * Math.cos(lat0 * Math.PI / 180);
  const toLonLat = (wx, wy) => [lon0 + wx / mPerDegLon, lat0 - wy / 110540];
  const [pxW, pyN] = lonLatToTilePx(...toLonLat(-R, -R), z);
  const [pxE, pyS] = lonLatToTilePx(...toLonLat(R, R), z);
  const tx0 = Math.floor(pxW / 256), tx1 = Math.floor(pxE / 256);
  const ty0 = Math.floor(pyN / 256), ty1 = Math.floor(pyS / 256);

  const canvas = document.createElement('canvas');
  canvas.width = (tx1 - tx0 + 1) * 256;
  canvas.height = (ty1 - ty0 + 1) * 256;
  const ctx = canvas.getContext('2d');
  const jobs = [];
  for (let ty = ty0; ty <= ty1; ty++) {
    for (let tx = tx0; tx <= tx1; tx++) {
      jobs.push(loadImage(prov.url(z, tx, ty)).then(img =>
        ctx.drawImage(img, (tx - tx0) * 256, (ty - ty0) * 256)));
    }
  }
  await Promise.all(jobs);
  const toTex = (wx, wy) => {
    const [px, py] = lonLatToTilePx(...toLonLat(wx, wy), z);
    return [px - tx0 * 256, py - ty0 * 256];
  };
  const tex = { canvas, toTex };
  texCache.set(mode, tex);
  return tex;
}

// ---- baking ------------------------------------------------------------------

// Affine texture-mapped triangle: src (texture px) -> dst (bake px).
function texTriangle(ctx, img, s, d) {
  const [[sx0, sy0], [sx1, sy1], [sx2, sy2]] = s;
  let [[dx0, dy0], [dx1, dy1], [dx2, dy2]] = d;
  // expand dst triangle ~0.7px from its centroid to hide seams between cells
  const cx = (dx0 + dx1 + dx2) / 3, cy = (dy0 + dy1 + dy2) / 3;
  const grow = (x, y) => {
    const l = Math.hypot(x - cx, y - cy) || 1;
    return [x + (x - cx) / l * 0.7, y + (y - cy) / l * 0.7];
  };
  [[dx0, dy0], [dx1, dy1], [dx2, dy2]] = [grow(dx0, dy0), grow(dx1, dy1), grow(dx2, dy2)];
  const den = sx0 * (sy1 - sy2) + sx1 * (sy2 - sy0) + sx2 * (sy0 - sy1);
  if (Math.abs(den) < 1e-9) return;
  const a = (dx0 * (sy1 - sy2) + dx1 * (sy2 - sy0) + dx2 * (sy0 - sy1)) / den;
  const b = (dy0 * (sy1 - sy2) + dy1 * (sy2 - sy0) + dy2 * (sy0 - sy1)) / den;
  const c = (dx0 * (sx2 - sx1) + dx1 * (sx0 - sx2) + dx2 * (sx1 - sx0)) / den;
  const dd = (dy0 * (sx2 - sx1) + dy1 * (sx0 - sx2) + dy2 * (sx1 - sx0)) / den;
  const e = dx0 - a * sx0 - c * sy0;
  const f = dy0 - b * sx0 - dd * sy0;
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(dx0, dy0); ctx.lineTo(dx1, dy1); ctx.lineTo(dx2, dy2);
  ctx.closePath(); ctx.clip();
  ctx.transform(a, b, c, dd, e, f);
  ctx.drawImage(img, 0, 0);
  ctx.restore();
}

// Bake the ground for the current style into an offscreen iso-space canvas.
// Async because imagery modes fetch tiles; stale bakes are dropped via bakeSeq.
// Dispatches 'ground-baked' when the ground changed (any mode, including back
// to stylized) and 'ground-bake-failed' when imagery tiles can't be loaded.
export async function bakeGround(world, onDone) {
  const st = appState.style;
  const seq = ++bakeSeq;
  const done = () => {
    window.dispatchEvent(new CustomEvent('ground-baked'));
    onDone && onDone(baked);
  };
  if (!st || st.ground === 'stylized' || (st.ground === 'hillshade' && !T)
      || (st.ground !== 'hillshade' && !world.center)) {
    baked = null;
    done();
    return;
  }
  let tex = null;
  if (st.ground !== 'hillshade') {
    try {
      tex = await fetchImagery(world, st.ground);
    } catch (e) {
      if (seq !== bakeSeq) return;
      baked = null;
      window.dispatchEvent(new CustomEvent('ground-bake-failed', { detail: st.ground }));
      onDone && onDone(null);
      return;
    }
    if (seq !== bakeSeq) return;   // superseded while tiles loaded
  }

  const R = world.radius_m * 1.12;
  const lift = (wx, wy) => (st.relief && T) ? elevM(wx, wy) * ELEV_PX_M : 0;
  const isoW = 2 * R * Math.SQRT2 * HW;
  const maxLift = T ? (T.z_max - T.z_min) * ELEV_PX_M : 0;
  const isoH = 2 * R * Math.SQRT2 * HH + maxLift;
  const scale = Math.min(1.25, 2800 / isoW);
  const x0 = -R * Math.SQRT2 * HW, y0 = -R * Math.SQRT2 * HH - maxLift;
  const cv = document.createElement('canvas');
  cv.width = Math.ceil(isoW * scale);
  cv.height = Math.ceil(isoH * scale);
  const ctx = cv.getContext('2d');
  ctx.setTransform(scale, 0, 0, scale, -x0 * scale, -y0 * scale);

  // Terrain cell mesh over the disk (single flat cell when no DEM).
  const nx = T ? T.nx - 1 : 1, ny = T ? T.ny - 1 : 1;
  const gx0 = T ? T.x0 : -R, gy0 = T ? T.y0 : -R;
  const cell = T ? T.cell_m : 2 * R;
  const zAmp = T ? Math.max(1, T.z_max - T.z_min) : 1;
  const rIn = R + cell;   // skip cells fully outside the disk (with margin)
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const wx0 = gx0 + i * cell, wy0 = gy0 + j * cell;
      const wx1 = wx0 + cell, wy1 = wy0 + cell;
      const cxm = wx0 + cell / 2, cym = wy0 + cell / 2;
      if (Math.hypot(cxm, cym) > rIn) continue;
      const corners = [[wx0, wy0], [wx1, wy0], [wx1, wy1], [wx0, wy1]];
      const dst = corners.map(([wx, wy]) =>
        [isoX(wx, wy), isoY(wx, wy) - lift(wx, wy)]);
      if (tex) {
        const src = corners.map(([wx, wy]) => tex.toTex(wx, wy));
        texTriangle(ctx, tex.canvas, [src[0], src[1], src[2]], [dst[0], dst[1], dst[2]]);
        texTriangle(ctx, tex.canvas, [src[0], src[2], src[3]], [dst[0], dst[2], dst[3]]);
      } else {
        // hillshade: slope-shaded fill, light from the NW, altitude tint
        const zc = elevM(cxm, cym);
        const sxs = elevM(cxm - cell, cym) - elevM(cxm + cell, cym);
        const sys = elevM(cxm, cym - cell) - elevM(cxm, cym + cell);
        const bright = clamp(1 + (sxs + sys) * (0.35 / cell) * 8, 0.62, 1.45);
        const t = clamp(zc / zAmp, 0, 1) * 0.8;
        const lo = hexToRgb('#84bb68'), hi = hexToRgb('#b3a578');
        const rgb = lo.map((v, k) =>
          clamp(Math.round((v + (hi[k] - v) * t) * bright), 0, 255));
        ctx.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
        ctx.beginPath();
        dst.forEach(([x, y], k) => k ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
        ctx.closePath();
        ctx.fill();
        ctx.strokeStyle = ctx.fillStyle;   // hairline overlap hides seams
        ctx.lineWidth = 1 / scale;
        ctx.stroke();
      }
    }
  }
  if (seq !== bakeSeq) return;
  baked = { canvas: cv, x0, y0, w: isoW, h: isoH };
  done();
}

export function groundAttribution() {
  const st = appState.style;
  if (!st || !baked) return null;
  return TILE_PROVIDERS[st.ground] ? TILE_PROVIDERS[st.ground].attribution
    : st.ground === 'hillshade' ? 'Elevation: SRTM via Open-Elevation' : null;
}
