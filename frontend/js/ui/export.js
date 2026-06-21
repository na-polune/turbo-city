// Download the current per-building analysis as CSV. The backend sets a
// Content-Disposition: attachment header, so a synthetic anchor click saves
// the file (with the server-chosen name) without navigating away from the app.
export function setupExport() {
  document.getElementById('exportBtn').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = '/api/export/buildings.csv';
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  });
}
