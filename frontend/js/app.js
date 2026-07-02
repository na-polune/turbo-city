import { resize, fitCamera, cam, worldToScreen } from './camera.js';
import { fetchWorld, pollState } from './api.js';
import { startRenderLoop } from './render.js';
import { setupInput } from './input.js';
import { setupToolbar } from './ui/toolbar.js';
import { setupPopup, openDetail } from './ui/popup.js';
import { setupTimeControls } from './ui/time-controls.js';
import { setupCityLoader } from './ui/city-loader.js';
import { setupExport } from './ui/export.js';
import { setupScenario } from './ui/scenario.js';
import { setupInfoView } from './ui/infoview.js';
import { setupStyle } from './ui/style.js';
import { appState } from './state.js';

resize();
setupInput();
setupToolbar();
setupPopup();
setupTimeControls();
setupCityLoader();
setupExport();
setupScenario();
setupInfoView();
setupStyle();   // must run before fetchWorld: prepareWorld reads appState.style
fetchWorld().then(() => { fitCamera(); pollState(); startRenderLoop(); });
setTimeout(() => document.getElementById('toast').classList.add('hide'), 9000);

window.cityDebug = {
  cam,
  worldToScreen,
  openDetail,
  get world() { return appState.world; },
  get state() { return appState.cur; },
};
