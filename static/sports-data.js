/* Read-only, on-demand sports data. No model or prediction is invoked. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  if (!el('liveForm')) return;
  const parisDate = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit'});
  el('liveDate').value = parisDate.format(new Date());
  const today = new Date(el('liveDate').value + 'T12:00:00Z');
  el('liveDate').min = new Date(today.getTime() - 30 * 86400000).toISOString().slice(0, 10);
  el('liveDate').max = new Date(today.getTime() + 30 * 86400000).toISOString().slice(0, 10);
  let active = null;
  const dateLabel = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Horaire non disponible' : date.toLocaleString('fr-FR', {timeZone: 'Europe/Paris', dateStyle: 'short', timeStyle: 'short'}) + ' (Paris)';
  };
  const freshness = data => `365Scores · Récupéré le ${dateLabel(data.fetched_at)} · ${data.cached ? 'Réponse en cache' : 'Consultation effectuée'} (cache maximal : 60 s).`;
  const score = game => game.home.score == null || game.away.score == null
    ? 'Score indisponible' : `${game.home.score} — ${game.away.score}`;

  function clearSelection() {
    el('liveReport').hidden = true;
    el('liveError').hidden = true;
    el('liveMatches').querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', 'false'));
  }
  el('liveForm').addEventListener('input', () => {
    if (active) active.abort();
    active = null;
    el('liveFields').disabled = false;
    el('liveForm').removeAttribute('aria-busy');
    clearSelection();
    el('liveMatches').replaceChildren();
    el('liveFreshness').hidden = true;
    el('liveStatus').textContent = 'Recherche modifiée. Clique sur Chercher les matchs.';
  });

  async function load(path, render, searching) {
    if (active) active.abort();
    const controller = new AbortController();
    active = controller;
    clearSelection();
    el('liveFields').disabled = searching;
    el('liveForm').setAttribute('aria-busy', 'true');
    el('liveStatus').textContent = 'Consultation de 365Scores…';
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {credentials: 'same-origin', signal: controller.signal});
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json().catch(() => ({}));
      if (active !== controller) return;
      if (!response.ok) throw new Error(data.error || 'Les données sportives sont indisponibles. Réessaie plus tard.');
      if (data.mode !== 'sports_data') throw new Error('Réponse inattendue. Aucune donnée sportive affichée.');
      render(data);
    } catch (error) {
      if (active !== controller) return;
      el('liveStatus').textContent = '';
      el('liveError').textContent = error.name === 'AbortError' ? 'La consultation a expiré. Réessaie dans un instant.'
        : error instanceof TypeError ? 'Connexion impossible ou réponse non reconnue. Réessaie plus tard.' : error.message;
      el('liveError').hidden = false;
    } finally {
      clearTimeout(timer);
      if (active === controller) {
        active = null;
        el('liveFields').disabled = false;
        el('liveForm').removeAttribute('aria-busy');
      }
    }
  }

  function showMatch(id, button) {
    load(`/api/ai/matches/${id}`, data => {
      const game = data.match;
      if (!game || game.id !== id || !game.home || !game.away || !Array.isArray(data.statistics)) throw new Error('Rencontre non reconnue.');
      el('liveReportTitle').textContent = `${game.home.name} — ${game.away.name}`;
      el('liveMatchMeta').textContent = `${game.competition} · ${dateLabel(game.starts_at)} · ${game.status} · Référence 365Scores : ${game.id}`;
      el('liveScore').textContent = score(game);
      el('liveDetailFreshness').textContent = freshness(data);
      el('liveHomeTitle').textContent = game.home.name;
      el('liveAwayTitle').textContent = game.away.name;
      el('liveStatsBody').replaceChildren(...data.statistics.map(stat => {
        const row = document.createElement('tr');
        const label = document.createElement('th');
        label.scope = 'row'; label.textContent = stat.label;
        row.append(label);
        for (const side of ['home', 'away']) {
          const cell = document.createElement('td');
          cell.textContent = stat[side] == null ? 'Indisponible' : stat[side];
          row.append(cell);
        }
        return row;
      }));
      el('liveStatsWrap').hidden = !data.statistics.length;
      el('liveNoStats').hidden = !!data.statistics.length;
      el('liveReport').hidden = false;
      button.setAttribute('aria-pressed', 'true');
      el('liveStatus').textContent = 'Données du match chargées. Aucune prédiction calculée.';
      el('liveReport').focus();
    }, false);
  }

  el('liveForm').addEventListener('submit', event => {
    event.preventDefault();
    if (el('liveFields').disabled || !el('liveForm').reportValidity()) return;
    el('liveMatches').replaceChildren();
    el('liveFreshness').hidden = true;
    const query = new URLSearchParams({date: el('liveDate').value, q: el('liveQuery').value.trim()});
    load('/api/ai/matches?' + query, data => {
      if (!Array.isArray(data.matches)) throw new Error('Liste de rencontres non reconnue.');
      const buttons = data.matches.map(game => {
        if (!Number.isSafeInteger(game.id) || !game.home || !game.away) throw new Error('Rencontre non reconnue.');
        const button = document.createElement('button');
        button.type = 'button'; button.setAttribute('aria-pressed', 'false');
        const title = document.createElement('strong');
        title.textContent = `${game.home.name} — ${game.away.name}`;
        const meta = document.createElement('span');
        meta.textContent = `${game.competition} · ${dateLabel(game.starts_at)} · ${game.status} · ${score(game)}`;
        button.append(title, meta);
        button.addEventListener('click', () => showMatch(game.id, button));
        return button;
      });
      el('liveMatches').replaceChildren(...buttons);
      el('liveFreshness').textContent = freshness(data);
      el('liveFreshness').hidden = false;
      el('liveStatus').textContent = (buttons.length ? `${buttons.length} rencontre(s). Choisis le match à consulter.`
        : 'Aucune rencontre renvoyée pour cette recherche. Essaie une autre date ou un autre nom ; la couverture peut être partielle.')
        + (data.truncated ? ' Liste limitée à 200 matchs : précise ta recherche.' : '')
        + (data.omitted_invalid ? ' Certaines données incomplètes ont été omises.' : '');
    }, true);
  });
})();
