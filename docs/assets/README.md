# Assets

Images used by the README and docs.

| File | Used by | What it is |
|---|---|---|
| `hero.svg` | README banner | Vector illustration of the app (skyline + live metric panel) |
| `ui-building.svg` | README gallery | The building-detail panel (metric tiles + load chart) |
| `ui-retrofit.svg` | README gallery | The retrofit before/after panel |
| `ui-eui.svg` | README gallery | The EUI heat-map |

These are **hand-built SVG illustrations** that faithfully mirror the live UI (same palette, same metric-tile design). They render crisply at any size and need no binary assets in the repo.

## Adding real screenshots

Want photographs of the running app instead? They make great README material.

1. Run the app (`uvicorn backend.main:app --reload`) and open <http://localhost:8000>.
2. Frame a good shot — load a dense city, open a building popup or the retrofit panel, optionally toggle the EUI heat-map. A window around **1400 px wide** looks best.
3. Capture (Windows: `Win + Shift + S`; macOS: `Cmd + Shift + 4`) and save the PNG here, e.g.:
   - `screenshot-overview.png` — the whole scene with the HUD
   - `screenshot-building.png` — a building detail popup
   - `screenshot-retrofit.png` — the retrofit scenario panel
   - `screenshot-eui.png` — the EUI heat-map
4. Point the README at them — replace the matching `docs/assets/*.svg` paths in [`../../README.md`](../../README.md) with your new `.png` files (or keep both: SVG for the hero, photos for the gallery).

> Tip: keep images reasonably compressed (a 1400 px PNG/JPEG is plenty) so the repo stays light.
