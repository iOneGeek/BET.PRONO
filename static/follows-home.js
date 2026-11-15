/* Tableau de bord : pronos suivis dans BET PRONO AI, avec le score en direct pendant les matchs. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const card = el('homeFollows');
  if (!card) return;
  const LIVE_REFRESH = 60 * 1000;
  const IDLE_REFRESH = 5 * 60 * 1000;
  let timer = null;
  let loading = false;

  const names = window.betNames || {team: x => x, competition: x => x};
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text != null) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  const score = value => (value || '').replace('-', ' – ');
  const percent = value => Math.round(value * 100) + ' %';
  const kickoff = value => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const time = date.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris'});
    const day = new Intl.DateTimeFormat('fr-CA', {timeZone: 'Europe/Paris'}).format(date);
    const today = new Intl.DateTimeFormat('fr-CA', {timeZone: 'Europe/Paris'}).format(new Date());
    const tomorrow = new Intl.DateTimeFormat('fr-CA', {timeZone: 'Europe/Paris'}).format(new Date(Date.now() + 86400000));
    if (day === today) return `Aujourd’hui ${time}`;
    if (day === tomorrow) return `Demain ${time}`;
    return date.toLocaleDateString('fr-FR', {weekday: 'short', day: '2-digit', month: '2-digit', timeZone: 'Europe/Paris'}) + ' ' + time;
  };
  const countdown = value => {
    const minutes = Math.round((new Date(value) - Date.now()) / 60000);
    if (minutes <= 0) return 'Coup d’envoi imminent';
    if (minutes < 60) return `dans ${minutes} min`;
    if (minutes < 24 * 60) return `dans ${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')}`;
    return '';
  };
  const outcome = (home, away) => home > away ? 'home' : home < away ? 'away' : 'draw';

  function row(item) {
    const li = node('li', null, 'fh-item fh-' + item.phase);
    const top = node('div', null, 'fh-top');
    if (item.phase === 'live') {
      const live = item.live && !item.live.unavailable ? item.live : null;
      const badge = node('span', '● EN DIRECT' + (live && live.clock ? ' · ' + live.clock : ''), 'fh-badge fh-badge-live');
      top.append(badge);
    } else if (item.phase === 'upcoming') {
      top.append(node('span', kickoff(item.starts_at), 'fh-badge'));
      const soon = countdown(item.starts_at);
      if (soon) top.append(node('span', soon, 'fh-soon'));
    } else {
      const mark = item.status === 'settled' ? (item.winner_hit ? '✓ Bon prono' : '✕ Raté') : item.status === 'void' ? 'Non vérifiable' : 'Terminé · vérification en cours';
      top.append(node('span', mark, 'fh-badge ' + (item.status === 'settled' ? (item.winner_hit ? 'fh-good' : 'fh-bad') : '')));
    }
    const comp = node('span', names.competition(item.competition), 'fh-comp');
    comp.title = item.competition || '';
    top.append(comp);

    const match = node('div', null, 'fh-match');
    let shown = null;
    if (item.phase === 'live' && item.live && item.live.home != null && item.live.away != null) shown = [item.live.home, item.live.away];
    else if (item.phase === 'finished' && item.actual) shown = item.actual.split('-').map(Number);
    else if (item.phase === 'finished' && item.live && item.live.home != null) shown = [item.live.home, item.live.away];
    match.append(node('span', names.team(item.home), 'fh-team'), node('strong', shown ? `${shown[0]} – ${shown[1]}` : 'vs', 'fh-score'),
      node('span', names.team(item.away), 'fh-team fh-team-away'));

    const prono = node('p', null, 'fh-prono');
    let text = `Prono ${score(item.predicted)}`;
    if (typeof item.confidence === 'number') text += ` (${percent(item.confidence)})`;
    if (item.scorer) text += ` · Buteur : ${item.scorer}` + (item.scorer_hit === true ? ' ✓' : item.scorer_hit === false ? ' ✕' : '');
    prono.textContent = text;
    if (item.phase === 'live' && shown) {
      const onTrack = outcome(shown[0], shown[1]) === item.winner;
      prono.append(' ', node('span', onTrack ? '· en bonne voie' : '· pour l’instant non', onTrack ? 'fh-good' : 'fh-bad'));
    }
    if (item.phase === 'live' && item.live && item.live.unavailable) prono.append(' ', node('span', '· score momentanément indisponible', 'fh-soon'));
    li.append(top, match, prono);
    return li;
  }

  function schedule(fast) {
    clearTimeout(timer);
    timer = setTimeout(load, fast ? LIVE_REFRESH : IDLE_REFRESH);
  }

  async function load() {
    if (loading) return;
    if (document.hidden) { schedule(false); return; }
    loading = true;
    try {
      const response = await fetch('/api/ai/follows/dashboard', {credentials: 'same-origin'});
      if (response.status === 401) { card.hidden = true; return; }
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.items)) throw new Error('unavailable');
      card.hidden = !data.items.length;
      el('homeFollowsList').replaceChildren(...data.items.map(row));
      const soon = data.items.some(item => item.phase === 'upcoming' && new Date(item.starts_at) - Date.now() < 15 * 60000);
      el('homeFollowsUpdate').textContent = `Mis à jour à ${new Date().toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}`
        + (data.has_live ? ' · score en direct actualisé chaque minute' : '');
      schedule(data.has_live || soon);
    } catch (_) {
      el('homeFollowsUpdate').textContent = 'Pronos suivis momentanément indisponibles.';
      schedule(false);
    } finally {
      loading = false;
    }
  }

  el('homeFollowsAll').addEventListener('click', () => {
    if (typeof window.navigate === 'function') window.navigate('ai');
    else document.querySelector('[data-route="ai"]')?.click();
    setTimeout(() => el('aiFollows')?.scrollIntoView({behavior: 'smooth', block: 'start'}), 150);
  });
  // Revenir sur l'onglet du navigateur relance tout de suite l'actualisation.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  // Un prono suivi ou retiré dans BET PRONO AI apparaît sans attendre.
  window.addEventListener('bet-prono-follows-changed', load);
  load();
})();
