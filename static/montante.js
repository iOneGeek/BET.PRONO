/* Montante par paliers : tableau public (Paris partagés), bandeau du tableau de bord, gestion admin. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const panel = el('montantePanel');
  if (!panel) return;
  const euro = value => value == null ? '—' : value.toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' €';
  const odds = value => Number(value).toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const two = n => String(n).padStart(2, '0');
  const names = window.betNames || {team: x => x, competition: x => x};
  const kickoff = value => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const day = new Intl.DateTimeFormat('fr-CA', {timeZone: 'Europe/Paris'}).format(date);
    const today = new Intl.DateTimeFormat('fr-CA', {timeZone: 'Europe/Paris'}).format(new Date());
    const time = date.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris'});
    return (day === today ? 'Aujourd’hui ' : date.toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit', timeZone: 'Europe/Paris'}) + ' ') + time;
  };
  // Montant de tableau : sur petit écran, le symbole € passe dans l'en-tête de colonne.
  const amountCell = value => {
    const cell = node('td', value == null ? '—' : value.toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}), 'mt-num');
    if (value != null) cell.append(node('span', ' €', 'mt-cur'));
    return cell;
  };
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text != null) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  const STATUS = {active: 'EN COURS', won: 'RÉUSSIE', lost: 'PERDUE', stopped: 'ARRÊTÉE'};
  const STATE_MARK = {won: '✓', lost: '✕', void: '↺', current: '●', simulation: '', off: ''};
  let data = null;
  let follows = [];
  let timer = null;

  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, ...options});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || 'Action impossible pour le moment.');
    return body;
  }

  function liveLine(live) {
    if (!live) return null;
    if (live.unavailable) return node('span', 'Score momentanément indisponible', 'mt-live-muted');
    const home = names.team(live.home_name), away = names.team(live.away_name);
    if (live.scheduled) return node('span', `⏰ ${home} – ${away} · ${kickoff(live.starts_at)}`, 'mt-live-muted');
    const text = `${live.in_play ? '● EN DIRECT' + (live.clock ? ' · ' + live.clock : '') : live.finished ? 'Terminé' : ''} ${home} ${live.home} – ${live.away} ${away}`;
    return node('span', text.trim(), live.in_play ? 'mt-live' : 'mt-live-muted');
  }

  function stepRow(step, view, editable) {
    const tr = document.createElement('tr');
    tr.className = 'mt-' + step.state;
    const number = node('th', two(step.step_no));
    number.scope = 'row';
    const mark = STATE_MARK[step.state];
    if (mark) number.prepend(node('span', mark, 'mt-mark'));
    tr.append(number);
    const pending = step.state === 'current' || step.state === 'simulation';
    tr.append(amountCell(step.stake));
    const oddsCell = node('td', null, 'mt-num');
    if (editable && pending) {
      const input = node('input', null, 'mt-input');
      Object.assign(input, {type: 'number', step: '0.01', min: '1.01', max: '20', value: step.odds, title: 'Cote du palier'});
      input.setAttribute('aria-label', `Cote du palier ${step.step_no}`);
      input.addEventListener('change', () => patch(view.id, step.step_no, {odds: Number(input.value)}));
      oddsCell.append(input);
    } else oddsCell.textContent = odds(step.odds);
    const back = amountCell(step.return);
    back.classList.add('mt-return');
    tr.append(oddsCell, back);
    const out = node('td', null, 'mt-num');
    if (editable && pending) {
      const input = node('input', null, 'mt-input');
      Object.assign(input, {type: 'number', step: '1', min: '0', value: step.withdrawal || 0, title: 'Retrait après ce palier'});
      input.setAttribute('aria-label', `Retrait après le palier ${step.step_no}`);
      input.addEventListener('change', () => patch(view.id, step.step_no, {withdrawal: Number(input.value)}));
      out.append(input);
    } else if (step.withdrawal) out.append(node('span', euro(step.withdrawal).replace(',00', ''), 'mt-pill'));
    else out.textContent = '—';
    tr.append(out);
    const rows = [tr];
    // Ligne de détail : pari joué / en cours, score en direct, commandes de l'admin.
    if (step.pick || step.state === 'current' || (editable && step.state !== 'off')) {
      const detail = document.createElement('tr');
      detail.className = 'mt-detail mt-' + step.state;
      const cell = node('td');
      cell.colSpan = 5;
      if (step.pick) cell.append(node('span', step.pick, 'mt-pick'));
      const live = liveLine(step.live);
      if (live) cell.append(live);
      if (editable && step.state === 'current') cell.append(adminControls(view, step));
      if (editable && step.step_no === lastPlayed(view)) {
        const undo = node('button', 'Annuler ce résultat', 'mt-link');
        undo.type = 'button';
        undo.addEventListener('click', () => patch(view.id, step.step_no, {result: 'pending'}));
        cell.append(undo);
      }
      if (cell.childNodes.length) { detail.append(cell); rows.push(detail); }
    }
    return rows;
  }

  const lastPlayed = view => Math.max(0, ...view.steps.filter(s => s.state === 'won' || s.state === 'void').map(s => s.step_no));

  function adminControls(view, step) {
    const box = node('div', null, 'mt-admin');
    const pick = node('input', null, 'mt-input mt-pick-input');
    Object.assign(pick, {type: 'text', maxLength: 120, placeholder: 'Pari du palier (ex. PSG gagne)', value: step.pick || ''});
    pick.setAttribute('aria-label', 'Pari du palier en cours');
    pick.addEventListener('change', () => patch(view.id, step.step_no, {pick: pick.value}));
    const game = node('select', null, 'mt-input');
    game.setAttribute('aria-label', 'Match lié pour le score en direct');
    game.append(new Option('Match lié (score en direct) : aucun', ''));
    follows.forEach(item => game.append(new Option(`${item.home} – ${item.away} · ${new Date(item.starts_at).toLocaleString('fr-FR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'})}`, String(item.game_id))));
    game.value = step.game_id ? String(step.game_id) : '';
    if (step.game_id && game.value !== String(step.game_id)) {
      const known = step.live && step.live.home_name ? `${step.live.home_name} – ${step.live.away_name}` : `Match n° ${step.game_id}`;
      game.append(new Option(known, String(step.game_id), true, true));
    }
    game.addEventListener('change', () => patch(view.id, step.step_no, {game_id: game.value ? Number(game.value) : null}));
    const actions = node('div', null, 'mt-actions');
    for (const [result, label, className] of [['won', '✓ Gagné', 'mt-won-btn'], ['lost', '✕ Perdu', 'mt-lost-btn'], ['void', '↺ Annulé (remboursé)', '']]) {
      const button = node('button', label, className);
      button.type = 'button';
      button.addEventListener('click', () => {
        if (result === 'lost' && !confirm('Marquer ce palier perdu arrête la montante. Continuer ?')) return;
        patch(view.id, step.step_no, {result});
      });
      actions.append(button);
    }
    box.append(pick, game, actions);
    return box;
  }

  async function patch(id, stepNo, body) {
    try {
      await api(`/api/montantes/${id}/steps/${stepNo}`, {method: 'PATCH', body: JSON.stringify(body)});
      await load();
      el('montanteMsg').textContent = 'Enregistré.';
    } catch (error) {
      el('montanteMsg').textContent = error.message;
    }
  }

  function renderView(view, editable) {
    const card = node('div', null, 'mt-card');
    const head = node('div', null, 'mt-head');
    const titles = node('div');
    const brand = node('p', null, 'mt-brand');
    brand.append('BET.', node('span', 'PRONO'));
    titles.append(brand, node('h3', view.title, 'mt-title'),
      node('p', `Départ ${euro(view.start_stake)} • Cote par défaut ${odds(view.default_odds)}`, 'mt-sub'));
    head.append(titles, node('span', STATUS[view.status] || view.status, 'mt-status mt-status-' + view.status));
    card.append(head);
    const done = view.won_steps;
    const progress = node('div', null, 'mt-progress');
    const bar = node('div', null, 'mt-bar');
    bar.append(node('span'));
    bar.firstChild.style.width = `${Math.round(done / view.total_steps * 100)}%`;
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', String(view.total_steps));
    bar.setAttribute('aria-valuenow', String(done));
    const label = view.status === 'active' ? `Palier ${view.current_step} / ${view.total_steps}` :
      view.status === 'lost' ? `Perdue au palier ${view.lost_step} / ${view.total_steps}` : `${done} / ${view.total_steps} paliers validés`;
    progress.append(node('strong', label), bar);
    card.append(progress);
    const wrap = node('div', null, 'mt-table-wrap');
    const table = node('table', null, 'mt-table');
    table.append(node('caption', `${view.title} : mises, cotes, retours et retraits par palier`, 'ai-sr-only'));
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    [['Palier', ''], ['Mise', ' (€)'], ['Cote', ''], ['Retour*', ' (€)'], ['Retrait', '']].forEach(([text, unit]) => {
      const th = node('th', text);
      if (unit) th.append(node('span', unit, 'mt-unit'));
      th.scope = 'col';
      headRow.append(th);
    });
    thead.append(headRow);
    const body = document.createElement('tbody');
    view.steps.forEach(step => body.append(...stepRow(step, view, editable && view.status === 'active')));
    table.append(thead, body);
    wrap.append(table);
    card.append(wrap);
    const foot = node('div', null, 'mt-foot');
    const left = node('div');
    left.append(node('span', `Retour au palier ${view.total_steps}*`, 'mt-foot-label'), node('strong', euro(view.final_return), 'mt-foot-value'));
    const right = node('div', null, 'mt-foot-right');
    right.append(node('span', 'Retraits prévus à part', 'mt-foot-label'), node('strong', euro(view.withdrawals_planned)));
    if (view.withdrawals_banked) right.append(node('span', `dont déjà encaissés : ${euro(view.withdrawals_banked)}`, 'mt-foot-label'));
    foot.append(left, right);
    card.append(foot, node('p', '* Si tous les paliers sont gagnants. Retour brut, mise incluse. Les paliers non joués sont une simulation. Aucun gain garanti • 18+', 'mt-note'));
    if (editable && view.status === 'active') {
      const stop = node('button', 'Arrêter la montante (encaisser)', 'mt-link');
      stop.type = 'button';
      stop.addEventListener('click', async () => {
        if (!confirm('Arrêter la montante ? Elle passera dans l’historique.')) return;
        try { await api(`/api/montantes/${view.id}/stop`, {method: 'POST'}); await load(); } catch (error) { el('montanteMsg').textContent = error.message; }
      });
      card.append(stop);
    }
    return card;
  }

  function renderHistory(history) {
    const box = el('montanteHistory');
    box.replaceChildren();
    if (!history.length) return;
    box.append(node('h3', 'Montantes précédentes', 'mt-history-title'));
    const list = node('ul', null, 'mt-history');
    history.forEach(view => {
      const li = node('li');
      const when = view.ended_at ? new Date(view.ended_at).toLocaleDateString('fr-FR') : '';
      const result = view.status === 'won' ? `✓ Réussie · retour ${euro(view.final_return)}` :
        view.status === 'lost' ? `✕ Perdue au palier ${view.lost_step}` : `Arrêtée après ${view.won_steps} palier(s)`;
      li.append(node('strong', view.title), node('span', `${result}${view.withdrawals_banked ? ' · retraits ' + euro(view.withdrawals_banked) : ''} · ${when}`));
      list.append(li);
    });
    box.append(list);
  }

  function renderBanner(view) {
    const banner = el('homeMontante');
    if (!banner) return;
    if (!view || view.status !== 'active') {
      // L'admin voit le raccourci même sans montante, pour la créer (utile sur mobile).
      banner.hidden = !(data && data.can_edit);
      el('homeMontanteText').textContent = 'Aucune montante en cours · Créer ta montante →';
      el('homeMontanteLive').replaceChildren();
      el('homeMontanteBar').style.width = '0%';
      return;
    }
    const current = view.steps.find(step => step.state === 'current');
    const chips = [['Palier', `${view.current_step} / ${view.total_steps}`], ['Mise', euro(view.current_stake)], ['Cote', odds(current.odds)]]
      .map(([label, value]) => { const chip = node('span', null, 'hm-chip'); chip.append(node('small', label), node('b', value)); return chip; });
    const parts = [...chips];
    if (current.pick) parts.push(node('span', current.pick, 'hm-pick'));
    el('homeMontanteText').replaceChildren(...parts);
    const info = current.live;
    let live = null;
    if (info && !info.unavailable && info.scheduled) live = node('span', '⏰ ' + kickoff(info.starts_at), 'mt-live-muted');
    else if (info && !info.unavailable && (info.in_play || info.finished)) {
      live = node('span', `${info.in_play ? '● ' + (info.clock || 'EN DIRECT') : 'Terminé'} · ${info.home} – ${info.away}`, info.in_play ? 'mt-live' : 'mt-live-muted');
    }
    el('homeMontanteLive').replaceChildren(...(live ? [live] : []));
    el('homeMontanteBar').style.width = `${Math.round(view.won_steps / view.total_steps * 100)}%`;
    banner.hidden = false;
  }

  function renderCreate() {
    const form = node('form', null, 'mt-create');
    form.append(node('h3', 'Nouvelle montante', 'mt-history-title'));
    const fields = [['title', 'Titre', 'text', 'Les 20 paliers'], ['start_stake', 'Mise de départ (€)', 'number', '10'],
      ['steps', 'Nombre de paliers', 'number', '20'], ['default_odds', 'Cote par défaut', 'number', '1.5']];
    for (const [name, label, type, value] of fields) {
      const wrapper = node('label', label);
      const input = node('input', null, 'mt-input');
      Object.assign(input, {name, type, value, required: true});
      if (type === 'number') Object.assign(input, {step: name === 'default_odds' ? '0.01' : '1', min: name === 'steps' ? '3' : '1', max: name === 'steps' ? '30' : ''});
      wrapper.append(input);
      form.append(wrapper);
    }
    form.append(node('p', 'Ensuite, règle la cote et le retrait de chaque palier directement dans le tableau.', 'mt-note'));
    const submit = node('button', 'Créer la montante', 'primary');
    submit.type = 'submit';
    form.append(submit);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form));
      try {
        await api('/api/montantes', {method: 'POST', body: JSON.stringify({title: values.title, start_stake: Number(values.start_stake),
          steps: Number(values.steps), default_odds: Number(values.default_odds)})});
        await load();
      } catch (error) { el('montanteMsg').textContent = error.message; }
    });
    return form;
  }

  async function load() {
    clearTimeout(timer);
    try {
      data = await api('/api/montantes');
      if (data.can_edit && !follows.length) {
        try { follows = (await api('/api/ai/follows/dashboard')).items.filter(item => item.phase !== 'finished'); } catch (_) { follows = []; }
      }
      const host = el('montanteActive');
      host.replaceChildren();
      if (data.active) host.append(renderView(data.active, data.can_edit));
      else if (data.can_edit) host.append(renderCreate());
      else host.append(node('p', 'Pas de montante en cours pour le moment. Reviens bientôt !', 'sub'));
      renderHistory(data.history);
      renderBanner(data.active);
      panel.hidden = !(data.active || data.history.length || data.can_edit);
      const live = data.active && data.active.steps.some(step => step.live && step.live.in_play);
      timer = setTimeout(load, live ? 60000 : 5 * 60000);
    } catch (error) {
      el('montanteMsg').textContent = error.message;
      timer = setTimeout(load, 5 * 60000);
    }
  }

  el('homeMontante')?.addEventListener('click', () => {
    if (typeof window.navigate === 'function') window.navigate('community');
    setTimeout(() => panel.scrollIntoView({behavior: 'smooth', block: 'start'}), 150);
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  load();
})();
