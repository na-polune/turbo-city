import { appState } from '../state.js';
import { sendSpeed, sendSeek } from '../api.js';

export function setupTimeControls() {
  const timeSlider = document.getElementById('timeSlider');
  const playBtn = document.getElementById('playBtn');
  const speedBtns = document.querySelectorAll('#speedRow button');
  let speedBeforeDrag = null;

  timeSlider.addEventListener('mousedown', () => {
    appState.sliderDragging = true;
    speedBeforeDrag = appState.cur ? appState.cur.sim_min_per_sec : 1;
    sendSpeed(0);
    playBtn.textContent = '▶';
  });
  timeSlider.addEventListener('touchstart', () => {
    appState.sliderDragging = true;
    speedBeforeDrag = appState.cur ? appState.cur.sim_min_per_sec : 1;
    sendSpeed(0);
    playBtn.textContent = '▶';
  }, { passive: true });
  timeSlider.addEventListener('input', () => {
    sendSeek(Number(timeSlider.value));
  });

  function endSliderDrag() {
    if (!appState.sliderDragging) return;
    appState.sliderDragging = false;
    const resume = speedBeforeDrag || 1;
    sendSpeed(resume);
    playBtn.textContent = resume > 0 ? '⏸' : '▶';
    for (const b of speedBtns)
      b.classList.toggle('active', Number(b.dataset.speed) === resume);
  }
  timeSlider.addEventListener('mouseup', endSliderDrag);
  timeSlider.addEventListener('touchend', endSliderDrag);

  playBtn.addEventListener('click', () => {
    const paused = appState.cur && appState.cur.sim_min_per_sec === 0;
    if (paused) {
      const resume = speedBeforeDrag || 1;
      sendSpeed(resume);
      playBtn.textContent = '⏸';
    } else {
      speedBeforeDrag = appState.cur ? appState.cur.sim_min_per_sec : 1;
      sendSpeed(0);
      playBtn.textContent = '▶';
    }
  });

  for (const b of speedBtns) {
    b.addEventListener('click', () => {
      sendSpeed(Number(b.dataset.speed));
      playBtn.textContent = '⏸';
    });
  }
}
