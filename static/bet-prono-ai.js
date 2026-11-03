/* Isolated beta: no persistence, file upload, OCR, sports feed or model calls. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const form = el('aiForm');
  if (!form) return;
  let busy = false;
  function clearReport() {
    el('aiReportContent').hidden = true;
    el('aiReportTitle').textContent = 'Le point de départ de ton analyse';
    el('aiReportNotice').textContent = 'Saisis une rencontre pour afficher les informations à vérifier. Aucun pronostic ne sera proposé dans cette bêta.';
    el('aiStatus').textContent = '';
    el('aiError').hidden = true;
  }
  form.addEventListener('input', clearReport);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    clearReport();
    busy = true;
    el('aiFields').disabled = true;
    form.setAttribute('aria-busy', 'true');
    el('aiStatus').textContent = 'Préparation du rapport de démonstration…';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/api/ai/analyze', {
        method: 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sport: el('aiSport').value, home_team: el('aiHome').value, away_team: el('aiAway').value})
      });
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Le rapport est indisponible. Réessaie dans un instant.');
      if (data.mode !== 'demo' || !data.match || !Array.isArray(data.checks)) {
        throw new Error('Réponse inattendue. Aucun rapport ne peut être affiché.');
      }
      // Never insert user-supplied team names as HTML.
      el('aiReportTitle').textContent = data.title;
      el('aiReportNotice').textContent = data.notice;
      el('aiMatch').textContent = `${data.match.home_team} — ${data.match.away_team} · ${data.match.sport}`;
      el('aiChecks').replaceChildren(...data.checks.map(check => {
        const row = document.createElement('div');
        const label = document.createElement('dt');
        const status = document.createElement('dd');
        label.textContent = check.label;
        status.textContent = check.status;
        row.append(label, status);
        return row;
      }));
      el('aiReportContent').hidden = false;
      el('aiStatus').textContent = 'Rapport de démonstration prêt. Aucune prédiction générée.';
      el('aiReport').focus();
    } catch (error) {
      el('aiStatus').textContent = '';
      el('aiError').textContent = error.name === 'AbortError'
        ? 'Le serveur met trop de temps à répondre. Réessaie dans un instant.'
        : error instanceof TypeError ? 'Connexion impossible. Vérifie ton réseau puis réessaie.' : error.message;
      el('aiError').hidden = false;
    } finally {
      clearTimeout(timeout);
      busy = false;
      el('aiFields').disabled = false;
      form.removeAttribute('aria-busy');
    }
  });

  let previewURL = null;
  let selection = 0;
  function removeCapture() {
    selection++;
    el('aiPreview').removeAttribute('src');
    el('aiPreviewArea').hidden = true;
    el('aiScreenshot').value = '';
    el('aiCaptureStatus').textContent = '';
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null;
  }
  el('aiRemoveCapture').addEventListener('click', removeCapture);
  window.addEventListener('pagehide', removeCapture);
  el('aiScreenshot').addEventListener('change', async () => {
    const file = el('aiScreenshot').files[0];
    removeCapture();
    if (!file) return;
    const version = selection;
    let url = null;
    try {
      if (!['image/png', 'image/jpeg'].includes(file.type) || !file.size || file.size > 5 * 1024 * 1024) {
        throw new Error('Choisis une image PNG ou JPEG de 5 Mo maximum.');
      }
      const bytes = new Uint8Array(await file.slice(0, 8).arrayBuffer());
      const png = [137,80,78,71,13,10,26,10].every((byte, i) => bytes[i] === byte);
      const jpeg = bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
      if (!(file.type === 'image/png' ? png : jpeg)) throw new Error('Le contenu du fichier ne correspond pas à une image PNG ou JPEG.');
      if (version !== selection) return;
      url = URL.createObjectURL(file);
      const picture = new Image();
      picture.src = url;
      await picture.decode();
      if (version !== selection) return;
      if (picture.naturalWidth * picture.naturalHeight > 16000000) throw new Error('Image trop grande : 16 mégapixels maximum.');
      previewURL = url;
      url = null;
      el('aiPreview').src = previewURL;
      el('aiPreviewArea').hidden = false;
      el('aiCaptureStatus').textContent = 'Aperçu local uniquement. Aucune équipe détectée automatiquement.';
    } catch (error) {
      if (version === selection) el('aiCaptureStatus').textContent = error.name === 'EncodingError' ? 'Image illisible. Choisis un autre fichier PNG ou JPEG.' : error.message;
    } finally {
      if (url) URL.revokeObjectURL(url);
    }
  });
})();
