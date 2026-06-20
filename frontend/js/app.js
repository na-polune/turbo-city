import { resize, fitCamera, cam, worldToScreen } from './camera.js';
import { fetchWorld, pollState } from './api.js';
import { startRenderLoop } from './render.js';
import { setupInput } from './input.js';
import { setupToolbar } from './ui/toolbar.js';
import { setupPopup, openDetail } from './ui/popup.js';
import { setupTimeControls } from './ui/time-controls.js';
import { appState } from './state.js';

resize();
setupInput();
setupToolbar();
setupPopup();
setupTimeControls();
fetchWorld().then(() => { fitCamera(); pollState(); startRenderLoop(); });
setTimeout(() => document.getElementById('toast').classList.add('hide'), 9000);

window.cityDebug = {
  cam,
  worldToScreen,
  openDetail,
  get world() { return appState.world; },
  get state() { return appState.cur; },
};
