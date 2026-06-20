export function flashToast(msg) {
  const t = document.getElementById('toast');
  t.querySelector('span:last-child').textContent = msg;
  t.classList.remove('hide');
  clearTimeout(flashToast._timer);
  flashToast._timer = setTimeout(() => t.classList.add('hide'), 3500);
}
