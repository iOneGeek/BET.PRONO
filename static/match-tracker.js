(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const panel = el('matchTracker');
  let selected = null;
  let pending = null;
  let timer;
  const labels = new Map(Object.entries({
    '1st Intermission': 'Fin du premier tiers', '2nd Intermission': 'Fin du deuxième tiers',
    '1st Period': 'Premier tiers', '2nd Period': 'Deuxième tiers', '3rd Period': 'Troisième tiers',
    Scheduled: 'À venir', Ended: 'Terminé', Penalty: 'Pénalité', Goal: 'But', Overtime: 'Prolongation'
  }));
  const translate = value => labels.get(value) || value;

  function board(game) {
    el('trackerCompetition').textContent = game.competition;
    el('trackerTeams').textContent = game.home.name + ' · ' + game.away.name;
    el('trackerPhase').textContent = translate(game.status);
    el('trackerScore').textContent = game.home.score == null || game.away.score == null
      ? '—' : game.home.score + ' : ' + game.away.score;
    el('trackerBoard').classList.toggle('rink', game.sport === 'Hockey sur glace');
  }

  function stop() {
    clearTimeout(timer);
    if (pending) pending.abort();
    pending = null;
    el('trackerRefresh').disabled = false;
  }
  function clear() {
    stop();
    selected = null;
    panel.open = false;
    el('trackerPeriods').replaceChildren();
    el('trackerEvents').replaceChildren();
    el('trackerUpdate').textContent = '';
  }
  function schedule() {
    clearTimeout(timer);
    if (selected?.live && panel.open) timer = setTimeout(() => {
      if (!document.hidden && panel.getClientRects().length) refresh();
      else schedule();
    }, 61000);
  }
  async function refresh() {
    if (!selected || !panel.open || pending) return;
    const controller = new AbortController();
    pending = controller;
    const timeout = setTimeout(() => controller.abort(), 16000);
    el('trackerRefresh').disabled = true;
    el('trackerUpdate').textContent = 'Actualisation en cours…';
    try {
      const response = await fetch('/api/ai/matches/' + selected.id + '/tracker', {signal: controller.signal});
      if (response.status === 401) { location.href = '/login'; return; }
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (pending !== controller) return;
      if (data.match?.id !== selected.id || !Array.isArray(data.periods) || !Array.isArray(data.events)) throw new Error();
      selected = data.match;
      board(selected);
      el('trackerPeriods').replaceChildren(...data.periods.map(period => {
        const cell = document.createElement('div');
        const title = document.createElement('b');
        title.textContent = period.label;
        if (period.current) cell.setAttribute('aria-current', 'true');
        cell.append(title, document.createTextNode(period.home == null || period.away == null ? '—' : period.home + ' : ' + period.away));
        return cell;
      }));
      const rows = data.events.map(event => {
        const row = document.createElement('li');
        const clock = document.createElement('b');
        clock.textContent = [event.period, event.time].filter(Boolean).join(' · ');
        row.append(clock, document.createTextNode(translate(event.label) + ' · ' + event.team));
        return row;
      });
      if (!rows.length) {
        const row = document.createElement('li');
        row.textContent = 'Aucun événement communiqué.';
        rows.push(row);
      }
      el('trackerEvents').replaceChildren(...rows);
      const time = new Date(data.fetched_at).toLocaleTimeString('fr-FR', {timeZone: 'Europe/Paris'});
      el('trackerUpdate').textContent = '365Scores · Relevé à ' + time + ' (Paris)' + (selected.live ? ' · Actualisation chaque minute.' : '.');
    } catch (_) {
      if (pending === controller) el('trackerUpdate').textContent = 'Suivi indisponible. Les dernières données affichées peuvent être différées.';
    } finally {
      clearTimeout(timeout);
      if (pending === controller) {
        pending = null;
        el('trackerRefresh').disabled = false;
        schedule();
      }
    }
  }
  panel.addEventListener('toggle', () => panel.open ? refresh() : stop());
  el('trackerRefresh').addEventListener('click', refresh);
  window.betTracker = {clear, select(game) {
    clear();
    selected = game;
    board(game);
    panel.open = game.live || game.sport === 'Hockey sur glace';
    if (panel.open) refresh();
  }};
})();
