import { appState } from '../state.js';

export function setTool(t) {
  appState.tool = (appState.tool === t) ? null : t;
  for (const b of document.querySelectorAll('#toolbar button'))
    b.classList.toggle('active', b.dataset.tool === appState.tool);
  document.getElementById('bldgTypes').style.display = appState.tool === 'bldg' ? 'flex' : 'none';
  document.getElementById('city').classList.toggle('placing', !!appState.tool);
}

export function setupToolbar() {
  document.querySelectorAll('#toolbar button[data-tool]').forEach(b =>
    b.addEventListener('click', () => setTool(b.dataset.tool)));
  document.getElementById('euiToggle').addEventListener('click', () => {
    appState.euiOverlay = !appState.euiOverlay;
    document.getElementById('euiToggle').classList.toggle('active', appState.euiOverlay);
    if (appState.euiOverlay) {            // EUI and heat overlays are mutually exclusive
      appState.heatOverlay = false;
      document.getElementById('heatPanel').classList.remove('open');
    }
    appState.dirty = true;
  });
  document.querySelectorAll('#bldgTypes button').forEach(b =>
    b.addEventListener('click', () => {
      appState.bldgType = b.dataset.btype;
      document.querySelectorAll('#bldgTypes button').forEach(x =>
        x.classList.toggle('active', x === b));
    }));
}
