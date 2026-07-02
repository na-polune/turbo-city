import { HW, HH, FLOOR_H, PALETTES } from './config.js';
import { isoX, isoY, pointInPoly } from './math.js';
import { setIsoBounds } from './camera.js';
import { appState } from './state.js';
import { setTerrain, groundLift, bakeGround } from './terrain.js';

export const ground = { layers: [] };

// Iso-project a world polyline into a Path2D, dropping each vertex by its
// terrain lift so vector features (roads, parks, water) ride the relief.
export function isoPath(points, close) {
  const p = new Path2D();
  points.forEach(([wx, wy], i) => {
    const x = isoX(wx, wy), y = isoY(wx, wy) - groundLift(wx, wy);
    i ? p.lineTo(x, y) : p.moveTo(x, y);
  });
  if (close) p.closePath();
  return p;
}

export function prepareWorld() {
  const { world } = appState;
  setTerrain(world.terrain);
  // Re-bake the ground for the current style (async for imagery; drops stale bakes).
  bakeGround(world, () => { appState.dirty = true; });

  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  const acc = (wx, wy) => {
    const x = isoX(wx, wy), y = isoY(wx, wy);
    if (x < x0) x0 = x; if (x > x1) x1 = x;
    if (y < y0) y0 = y; if (y > y1) y1 = y;
  };
  for (const b of world.buildings) for (const [wx, wy] of b.polygon) acc(wx, wy);
  for (const r of world.roads) for (const [wx, wy] of r.points) acc(wx, wy);
  setIsoBounds({ x0: x0 - 60, y0: y0 - 160, x1: x1 + 60, y1: y1 + 60 });

  // Ground vector layers. Each carries a tag so render can skip the ones the
  // active ground image replaces (imagery: disk/parks/water; hillshade: disk).
  const L = ground.layers;
  L.length = 0;
  const disk = new Path2D();
  const R = world.radius_m * 1.12;
  for (let k = 0; k <= 64; k++) {
    const a = k / 64 * Math.PI * 2;
    const x = isoX(Math.cos(a) * R, Math.sin(a) * R);
    const y = isoY(Math.cos(a) * R, Math.sin(a) * R);
    k ? disk.lineTo(x, y) : disk.moveTo(x, y);
  }
  disk.closePath();
  L.push({ tag: 'disk', path: disk, fill: '#84bb68' });
  for (const poly of world.parks) L.push({ tag: 'park', path: isoPath(poly, true), fill: '#79b563' });
  for (const poly of world.water) L.push({ tag: 'water', path: isoPath(poly, true), fill: '#4f8fd0' });
  const w2px = m => m * (HW + HH);
  for (const r of world.roads) {
    if (!r.drivable) L.push({ tag: 'road', path: isoPath(r.points, false), stroke: '#cdc9bd', width: w2px(r.width) });
  }
  for (const r of world.roads) {
    if (r.drivable) L.push({ tag: 'road', path: isoPath(r.points, false), stroke: '#4a4c52', width: w2px(r.width) });
  }
  for (const r of world.roads) {
    if (r.drivable && r.width >= 5) {
      L.push({ tag: 'road', path: isoPath(r.points, false), stroke: 'rgba(240,220,130,0.65)', width: 1.6, dash: [9, 9] });
    }
  }

  for (const b of world.buildings) {
    // One lift per building (at its center) so the prism stays rigid on slopes.
    b.zpx = groundLift(b.center[0], b.center[1]);
    b.iso = b.polygon.map(([wx, wy]) => [isoX(wx, wy), isoY(wx, wy) - b.zpx]);
    b.H = b.floors * FLOOR_H;
    b.depth = Math.max(...b.polygon.map(([wx, wy]) => wx + wy));
    const xs = b.iso.map(p => p[0]), ys = b.iso.map(p => p[1]);
    b.bb = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys) - b.H, y1: Math.max(...ys) };
    b.palette = PALETTES[b.type][b.id % PALETTES[b.type].length];
    b.walls = [];
    const n = b.polygon.length;
    for (let i = 0; i < n; i++) {
      const [ax, ay] = b.polygon[i], [bx, by] = b.polygon[(i + 1) % n];
      const ex = bx - ax, ey = by - ay;
      const len = Math.hypot(ex, ey);
      if (len < 0.5) continue;
      let nx = ey / len, ny = -ex / len;
      const mx = (ax + bx) / 2 + nx * 0.3, my = (ay + by) / 2 + ny * 0.3;
      if (pointInPoly(mx, my, b.polygon)) { nx = -nx; ny = -ny; }
      if (nx + ny <= 0) continue;
      b.walls.push({ i, len, u: nx / (Math.abs(nx) + Math.abs(ny)) });
    }
    b.roofPath = null;
  }
  world.buildings.sort((a, b) => a.depth - b.depth);

  world.props = [];
  for (const [wx, wy] of world.lamps) {
    world.props.push({ kind: 'lamp', wx, wy, depth: wx + wy,
                       ix: isoX(wx, wy), iy: isoY(wx, wy) - groundLift(wx, wy) });
  }
  for (const s of world.signals) {
    world.props.push({
      kind: 'signal', wx: s.x, wy: s.y, phase: s.phase_offset,
      depth: s.x + s.y, ix: isoX(s.x, s.y), iy: isoY(s.x, s.y) - groundLift(s.x, s.y),
    });
  }
}
