/* Sports snapshots with an automatic, separately loaded explanatory analysis. */
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
  let analysisActive = null;
  const dateLabel = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Horaire non disponible' : date.toLocaleString('fr-FR', {timeZone: 'Europe/Paris', dateStyle: 'short', timeStyle: 'short'}) + ' (Paris)';
  };
  const freshness = data => `365Scores · Récupéré le ${dateLabel(data.fetched_at)} · ${data.cached ? 'Réponse en cache' : 'Consultation effectuée'} (cache maximal : 60 s).`;
  const score = game => game.home.score == null || game.away.score == null
    ? 'Score indisponible' : `${game.home.score} — ${game.away.score}`;
  function element(tag, content, className) {
    const node = document.createElement(tag);
    node.textContent = content;
    if (className) node.className = className;
    return node;
  }
  function phase(game) {
    if (game.scheduled) return 'À venir';
    if (game.live) return 'En cours';
    return game.status === 'Ended' ? 'Terminé' : game.status;
  }

  const frenchNames = new Map([['Wales', 'Pays de Galles'], ['Denmark', 'Danemark'], ['Norway', 'Norvège']]);
  const teamName = team => frenchNames.get(team.name) || team.name;
  function emblem(team, host) {
    const initials = element('span', teamName(team).split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase());
    host.replaceChildren(initials);
    if (!Number.isSafeInteger(team.id) || team.id <= 0) return;
    const img = new Image();
    img.alt = '';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('load', () => {
      if (initials.parentNode === host) host.replaceChildren(img);
    }, {once:true});
    img.src = 'https://imagecache.365scores.com/image/upload/w_96,h_96,c_limit,f_png/Competitors/' + team.id;
  }
  function highlights(game, history) {
    const rows = [];
    const add = (team, title, description, date) => {
      const row = document.createElement('li');
      const mark = element('span', '⇄', 'mini-emblem');
      mark.setAttribute('aria-hidden', 'true');
      if (team) emblem(team, mark);
      const caption = document.createElement('span');
      caption.append(element('b', title), ' · ' + description);
      const stamp = element('time', new Intl.DateTimeFormat('fr-FR', {day:'2-digit', month:'2-digit', timeZone:'Europe/Paris'}).format(new Date(date)));
      stamp.dateTime = date;
      row.append(mark, caption, stamp);
      rows.push(row);
    };
    for (const side of ['home', 'away']) {
      const latest = history?.[side]?.[0];
      if (!latest) continue;
      const team = game[side];
      const home = latest.home.id === team.id;
      const own = home ? latest.home : latest.away;
      const other = home ? latest.away : latest.home;
      const outcome = own.score > other.score ? 'Victoire' : own.score < other.score ? 'Défaite' : 'Nul';
      add(team, teamName(team), outcome + ' contre ' + teamName(other), latest.starts_at);
    }
    const duel = history?.home?.find(match => history.away?.some(other => other.id === match.id)
      && [match.home.id, match.away.id].includes(game.home.id) && [match.home.id, match.away.id].includes(game.away.id));
    if (duel) add(null, 'Confrontation directe', teamName(duel.home) + ' ' + score(duel) + ' ' + teamName(duel.away), duel.starts_at);
    if (!rows.length) rows.push(element('li', 'Aucun résultat récent disponible.'));
    el('recentHighlights').replaceChildren(...rows);
  }
  function setFormView(expanded) {
    el('overviewView').setAttribute('aria-pressed', String(!expanded));
    el('formView').setAttribute('aria-pressed', String(expanded));
    el('reportColumns').classList.toggle('form-expanded', expanded);
    el('liveAnalysis').hidden = expanded;
  }
  el('overviewView').addEventListener('click', () => setFormView(false));
  el('formView').addEventListener('click', () => setFormView(true));
  document.querySelectorAll('.dossier-nav a').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    if (link.id === 'jumpResults') setFormView(true);
    const target = document.querySelector(link.hash);
    target.tabIndex = -1;
    target.focus({preventScroll:true});
    target.scrollIntoView({block:'start'});
  }));

  function recentRow(result, teamId) {
    const atHome = result.home.id === teamId;
    const opponent = atHome ? result.away : result.home;
    const ownGoals = atHome ? result.home.score : result.away.score;
    const otherGoals = opponent.score;
    const outcome = ownGoals > otherGoals ? 'Victoire' : ownGoals === otherGoals ? 'Nul' : 'Défaite';
    const row = document.createElement('li');
    const info = element('span', '', 'result-info');
    const label = element('strong', opponent.name);
    const metadata = element('time', dateLabel(result.starts_at).split(' ')[0]);
    metadata.dateTime = result.starts_at;
    const decided = {overtime: 'après prolongation', shootout: 'aux tirs au but', extra_time: 'après prolongation', penalties: 'aux tirs au but'}[result.decided];
    info.append(label, element('small', (atHome ? 'Domicile' : 'Extérieur') + ' · ' + result.competition + (decided ? ' · ' + decided : '')));
    const tally = element('abbr', ownGoals + ' — ' + otherGoals, 'result-score');
    tally.dataset.outcome = outcome;
    tally.title = outcome;
    tally.setAttribute('aria-label', outcome + ', ' + ownGoals + ' à ' + otherGoals);
    row.append(metadata, info, tally);
    return row;
  }

  const percent = value => Math.round(value * 100) + ' %';
  const decimal = value => String(value).replace('.', ',');

  function showModel(data) {
    const game = data.match;
    const model = data.model;
    el('liveModel').hidden = true;
    if (!game.scheduled || !model || !model.probabilities || !model.expected_goals) return;
    const p = model.probabilities;
    if (![p.home, p.draw, p.away].every(v => typeof v === 'number' && v >= 0 && v <= 1)) return;
    const hockey = game.sport === 'Hockey sur glace';
    el('liveModelIntro').textContent = `Calcul sur ${model.sample.home} et ${model.sample.away} résultats récents`
      + (hockey ? ', au temps réglementaire (le match nul est possible à 60 minutes).' : '.');
    const parts = [['home', teamName(game.home)], ['draw', 'Nul'], ['away', teamName(game.away)]];
    el('liveModelBar').replaceChildren(...parts.map(([key, label]) => {
      const part = element('span', percent(p[key]), 'model-' + key);
      part.style.flexGrow = String(Math.max(p[key], 0.04));
      part.title = label + ' : ' + percent(p[key]);
      return part;
    }));
    el('liveModelBar').setAttribute('aria-label', parts.map(([key, label]) => label + ' ' + percent(p[key])).join(', '));
    el('liveModelLegend').replaceChildren(...parts.map(([key, label]) => {
      const item = element('li', label + ' · ' + percent(p[key]));
      item.dataset.part = key;
      return item;
    }));
    el('liveModelXg').textContent = `${decimal(model.expected_goals.home)} — ${decimal(model.expected_goals.away)}`;
    el('liveModelScore').textContent = `${model.likely_score.home} — ${model.likely_score.away} (${percent(model.likely_score.probability)})`;
    el('liveModelOverLabel').textContent = `Plus de ${decimal(model.over.line)} buts`;
    el('liveModelOver').textContent = percent(model.over.probability);
    el('liveModelBoth').textContent = percent(model.both_score);
    el('liveModel').hidden = false;
  }

  function showForm(data) {
    const game = data.match;
    const form = data.form || {};
    el('liveFormPanel').hidden = true;
    if (!game.scheduled || (!form.home && !form.away)) return;
    const record = r => r && r.played ? `${r.wins}-${r.draws}-${r.losses}` : '—';
    el('liveFormBody').replaceChildren(...['home', 'away'].map(side => {
      const row = document.createElement('tr');
      const head = element('th', teamName(game[side]));
      head.scope = 'row';
      const f = form[side];
      row.append(head, ...(f ? [record(f), decimal(f.scored_avg), decimal(f.conceded_avg), record(f.home), record(f.away)]
        : ['—', '—', '—', '—', '—']).map(value => element('td', value)));
      return row;
    }));
    el('liveFormNote').textContent = 'Calcul sur les dix derniers résultats au plus, les plus récents comptant davantage'
      + (game.sport === 'Hockey sur glace' ? ', au score de fin de temps réglementaire.' : '.');
    const meetings = Array.isArray(data.head_to_head) ? data.head_to_head : [];
    const summary = data.head_to_head_summary;
    el('liveH2hSummary').textContent = summary
      ? `${summary.played} dernière(s) confrontation(s) : ${summary.home_wins} victoire(s) de ${teamName(game.home)}, ${summary.draws} nul(s), ${summary.away_wins} victoire(s) de ${teamName(game.away)}.`
      : 'Aucune confrontation directe récente trouvée par la source.';
    el('liveH2hList').replaceChildren(...meetings.map(result => recentRow(result, game.home.id)));
    el('liveFormPanel').hidden = false;
  }

  let trackLoaded = false;
  async function loadTrackRecord() {
    trackLoaded = true;
    loadFollows();
    el('aiTrackRefresh').disabled = true;
    el('aiTrackStatus').textContent = 'Chargement du bilan…';
    try {
      const response = await fetch('/api/ai/track-record', {credentials: 'same-origin'});
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json();
      if (!response.ok || !data.ai) throw new Error('Track record unavailable');
      const show = (id, stat) => {
        el(id).textContent = stat.total ? percent(stat.rate) : '—';
        el(id + 'N').textContent = stat.total ? `${stat.hits} sur ${stat.total}` : 'Pas encore de match';
      };
      show('trackAiWinner', data.ai.winner);
      show('trackAiExact', data.ai.exact_score);
      show('trackAiScorer', data.ai.scorer);
      el('aiTrackRecent').replaceChildren(...(data.recent.length ? data.recent.map(item => {
        const row = document.createElement('li');
        const when = element('time', dateLabel(item.starts_at).split(' ')[0]);
        when.dateTime = item.starts_at;
        const info = element('span', '', 'result-info');
        info.append(element('strong', `${item.home} — ${item.away}`),
          element('small', `${item.competition} · Prono ${item.predicted.replace('-', ' — ')} · Réel ${item.actual ? item.actual.replace('-', ' — ') : (item.actual_winner === 'draw' ? 'nul à 90 min' : '—')}`
            + (item.scorer ? ` · Buteur ${item.scorer} ${item.scorer_hit ? '✓' : '✗'}` : '')));
        const tally = element('abbr', item.winner_hit ? '✓' : '✗', 'result-score');
        tally.dataset.outcome = item.winner_hit ? 'Victoire' : 'Défaite';
        tally.title = item.winner_hit ? 'Bon vainqueur' : 'Mauvais vainqueur';
        row.append(when, info, tally);
        return row;
      }) : [element('li', 'Aucun pronostic vérifié pour l’instant.')]));
      el('aiTrackNotice').textContent = data.notice + (data.pending ? ` ${data.pending} pronostic(s) en attente du résultat.` : '');
      el('aiTrackStatus').textContent = data.settled
        ? `${data.settled} pronostic(s) vérifié(s) après le match.`
        : 'Les pronostics sont enregistrés automatiquement. Le bilan se remplit quand les matchs sont terminés.';
      el('aiTrackContent').hidden = false;
    } catch (_) {
      el('aiTrackStatus').textContent = 'Bilan momentanément indisponible. Réessaie dans un instant.';
    } finally {
      el('aiTrackRefresh').disabled = false;
    }
  }
  el('aiTrackRefresh').addEventListener('click', loadTrackRecord);
  // Load once, the first time the AI view is opened (not on every dashboard visit).
  const aiView = el('viewAI');
  const loadWhenOpen = () => { if (!trackLoaded && (!aiView || aiView.classList.contains('active'))) loadTrackRecord(); };
  if (aiView) new MutationObserver(loadWhenOpen).observe(aiView, {attributes: true, attributeFilter: ['class']});
  loadWhenOpen();

  function clearSelection() {
    setFormView(false);
    el('liveModel').hidden = true;
    el('liveFormPanel').hidden = true;
    el('forecastSources').hidden = true;
    el('jumpPrediction').hidden = true;
    window.betTracker.clear();
    if (analysisActive) analysisActive.abort();
    analysisActive = null;
    el('liveAnalysis').removeAttribute('aria-busy');
    el('liveAnalysisStatus').classList.remove('is-loading');
    el('liveAnalysisContent').hidden = true;
    el('livePrediction').hidden = true;
    el('livePredictionStatus').hidden = true;
    el('liveAnalysisStatus').textContent = '';
    el('liveReport').querySelectorAll('.report-disclosure[open]').forEach(detail => { detail.open = false; });
    el('liveReport').hidden = true;
    el('liveError').hidden = true;
    el('liveMatches').querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', 'false'));
  }

  // ---- Pronos suivis -------------------------------------------------------
  const followed = new Set();
  let currentPick = null;

  function setFollowButton(on) {
    const button = el('followPick');
    button.setAttribute('aria-pressed', String(on));
    button.replaceChildren(element('span', on ? '★' : '☆'), on ? ' Prono suivi' : ' Suivre ce prono');
    button.firstChild.setAttribute('aria-hidden', 'true');
    button.classList.toggle('is-on', on);
  }

  function followRow(item) {
    const row = document.createElement('li');
    const when = element('time', dateLabel(item.starts_at).split(' ')[0]);
    when.dateTime = item.starts_at;
    const info = element('span', '', 'result-info');
    const prono = `Prono ${item.predicted.replace('-', ' — ')}` + (item.scorer ? ` · Buteur ${item.scorer}` : '');
    let detail = prono;
    if (item.status === 'settled') {
      detail += ` · Réel ${item.actual ? item.actual.replace('-', ' — ') : 'nul à 90 min'}`;
      if (item.exact_hit) detail += ' · Score exact ✓';
      if (item.scorer_hit != null) detail += item.scorer_hit ? ' · Buteur ✓' : ' · Buteur ✗';
    }
    info.append(element('strong', `${item.home} — ${item.away}`), element('small', `${item.competition} · ${detail}`));
    const label = item.status === 'pending' ? '…' : item.status === 'void' ? '—' : item.winner_hit ? '✓' : '✗';
    const tally = element('abbr', label, 'result-score');
    tally.dataset.outcome = item.status === 'settled' ? (item.winner_hit ? 'Victoire' : 'Défaite') : 'Nul';
    tally.title = item.status === 'pending' ? 'En attente du résultat' : item.status === 'void' ? 'Match non vérifiable'
      : item.winner_hit ? 'Bon vainqueur' : 'Mauvais vainqueur';
    const remove = element('button', 'Retirer', 'follow-remove');
    remove.type = 'button';
    remove.setAttribute('aria-label', `Ne plus suivre ${item.home} — ${item.away}`);
    remove.addEventListener('click', () => toggleFollow(item.game_id, false));
    row.append(when, info, tally, remove);
    return row;
  }

  async function loadFollows() {
    try {
      const response = await fetch('/api/ai/follows', {credentials: 'same-origin'});
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.items)) throw new Error('Follows unavailable');
      followed.clear();
      data.items.forEach(item => followed.add(item.game_id));
      if (currentPick) setFollowButton(followed.has(currentPick.id));
      el('aiFollowsList').replaceChildren(...data.items.map(followRow));
      const s = data.summary;
      el('aiFollowsStatus').textContent = data.items.length
        ? `${s.followed} prono(s) suivi(s) · ${s.pending} en attente` + (s.settled ? ` · ${s.winner.hits} bon(s) vainqueur(s) sur ${s.settled}` : '') + '.'
        : 'Clique sur « Suivre ce prono » dans la fiche d’un match pour le retrouver ici avec son résultat.';
      el('trackMine').textContent = s.settled ? percent(s.winner.rate) : (s.followed ? String(s.followed) : '—');
      el('trackMineN').textContent = s.settled ? `${s.winner.hits} sur ${s.settled} · bon vainqueur` : (s.followed ? 'en attente' : 'Aucun prono suivi');
    } catch (_) {
      el('aiFollowsStatus').textContent = 'Tes pronos suivis sont momentanément indisponibles.';
    }
  }

  async function toggleFollow(gameId, on, confidence) {
    const button = el('followPick');
    if (currentPick && currentPick.id === gameId) button.disabled = true;
    try {
      const response = await fetch(`/api/ai/follows/${gameId}`, {
        method: on ? 'POST' : 'DELETE', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: on ? JSON.stringify({confidence}) : undefined});
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Action impossible pour le moment.');
      if (on) followed.add(gameId); else followed.delete(gameId);
      if (currentPick && currentPick.id === gameId) {
        setFollowButton(on);
        el('followStatus').textContent = on ? 'Ajouté à « Mes pronos suivis ». Le résultat s’affichera après le match.' : 'Prono retiré de ta liste.';
      }
      loadFollows();
    } catch (error) {
      if (currentPick && currentPick.id === gameId) el('followStatus').textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }
  el('followPick').addEventListener('click', () => {
    if (currentPick) toggleFollow(currentPick.id, !followed.has(currentPick.id), currentPick.confidence);
  });

  function showPrediction(prediction, snapshot) {
    const game = snapshot.match;
    currentPick = null;
    el('followStatus').textContent = '';
    if (!game.scheduled || new Date(game.starts_at) <= new Date()) return;
    if (prediction == null) {
      el('livePredictionStatus').textContent = 'Pronostic indisponible pour cette rencontre. Il nécessite au moins trois résultats récents vérifiés par équipe.';
      el('livePredictionStatus').hidden = false;
      return;
    }
    const {home_goals: home, away_goals: away} = prediction;
    if (![home, away].every(value => Number.isInteger(value) && value >= 0 && value <= 10)
        || !Array.isArray(prediction.evidence)) throw new Error('Invalid prediction');
    const winner = home === away ? 'draw' : home > away ? 'home' : 'away';
    if (prediction.winner !== winner) throw new Error('Inconsistent prediction');
    const hockey = game.sport === 'Hockey sur glace';
    el('livePredictionWinner').textContent = winner === 'draw' ? 'Match nul envisagé' : teamName(game[winner]);
    el('livePredictionScore').replaceChildren(
      element('span', game.home.name, 'ai-sr-only'), ' ',
      element('strong', home + ' — ' + away), ' ',
      element('span', game.away.name, 'ai-sr-only')
    );
    const model = snapshot.model;
    const confidence = typeof prediction.confidence === 'number' ? prediction.confidence : null;
    const parts = [];
    if (confidence != null) parts.push(`${winner === 'draw' ? 'Nul' : teamName(game[winner])} : ${percent(confidence)}`);
    if (model && model.double_chance && winner !== 'draw') {
      const dc = winner === 'home' ? model.double_chance.home_or_draw : model.double_chance.away_or_draw;
      parts.push(`${teamName(game[winner])} ou nul : ${percent(dc)}`);
    }
    if (typeof prediction.score_probability === 'number') parts.push(`score exact : ${percent(prediction.score_probability)}`);
    el('livePredictionConfidence').textContent = parts.length ? 'Selon le modèle · ' + parts.join(' · ') : '';
    el('livePredictionScorer').textContent = 'Non proposé';
    el('livePredictionScorerNote').textContent = (prediction.scorer_options || []).length
      ? 'Aucun joueur assez probable dans l’équipe qui marque selon le score estimé.'
      : 'Pas assez de données joueurs pour ce match.';
    if (prediction.scorer != null) {
      const player = (snapshot.scorer_candidates || []).find(candidate => candidate.id === prediction.scorer.id);
      if (!player || (player.side === 'home' ? home : away) === 0) throw new Error('Invalid scorer');
      el('livePredictionScorer').textContent = `${player.name} · ${player.team_name}`;
      const chance = typeof prediction.scorer.probability === 'number' ? `${percent(prediction.scorer.probability)} de chances de marquer. ` : '';
      el('livePredictionScorerNote').textContent = chance + `${player.goals} buts`
        + (player.appearances ? ` en ${player.appearances} matchs` : '') + ' selon 365Scores. '
        + (player.lineup_confirmed ? 'Présence annoncée par la source.' : 'Composition à confirmer.');
    }
    el('livePredictionEvidence').replaceChildren(...prediction.evidence.map(text => {
      const item = document.createElement('li'); item.textContent = text; return item;
    }));
    el('livePredictionTitle').textContent = hockey ? 'Pronostic avant-match · temps réglementaire' : 'Pronostic avant-match';
    el('forecastScoreLabel').textContent = hockey ? 'Score estimé · temps réglementaire' : 'Score estimé';
    currentPick = {id: game.id, confidence};
    setFollowButton(followed.has(game.id));
    el('followPick').disabled = false;
    el('forecastSources').hidden = false;
    el('jumpPrediction').hidden = false;
    el('livePrediction').hidden = false;
  }

  async function loadAnalysis(snapshot) {
    const controller = new AbortController();
    analysisActive = controller;
    el('liveAnalysis').setAttribute('aria-busy', 'true');
    el('liveAnalysisStatus').textContent = 'L’IA analyse le match (jusqu’à 30 secondes)';
    el('liveAnalysisStatus').classList.add('is-loading');
    const timer = setTimeout(() => controller.abort(), 55000);
    try {
      const response = await fetch(`/api/ai/matches/${snapshot.match.id}/analysis`, {
        method: 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({snapshot_id: snapshot.snapshot_id})
      });
      if (analysisActive !== controller) return;
      if (response.status === 401) { location.href = '/login'; return; }
      const result = await response.json().catch(() => ({}));
      if (analysisActive !== controller) return;
      if (!response.ok) throw new Error('Analysis unavailable');
      if (['unavailable', 'insufficient_data', 'outdated'].includes(result.status) && typeof result.message === 'string') {
        el('liveAnalysisStatus').textContent = result.message;
        return;
      }
      if (result.status !== 'ready' || result.snapshot_id !== snapshot.snapshot_id || typeof result.summary !== 'string'
          || !Array.isArray(result.observations) || !Array.isArray(result.limitations)) throw new Error('Invalid analysis');
      const points = result.observations.map(point => {
        if (typeof point.text !== 'string' || !Array.isArray(point.evidence)) throw new Error('Invalid evidence');
        const item = document.createElement('li');
        const explanation = document.createElement('p'); explanation.textContent = point.text;
        const evidence = document.createElement('details'); evidence.className = 'report-disclosure';
        evidence.append(element('summary', 'Données citées'));
        const cited = document.createElement('ul');
        cited.append(...point.evidence.map(fact => element('li', fact)));
        evidence.append(cited);
        item.append(explanation, evidence);
        return item;
      });
      el('liveAnalysisSummary').textContent = result.summary;
      el('liveAnalysisPoints').replaceChildren(...points);
      el('liveAnalysisLimits').replaceChildren(...result.limitations.map(text => {
        const item = document.createElement('li'); item.textContent = text; return item;
      }));
      el('liveAnalysisDate').textContent = 'Synthèse générée par IA le ' + dateLabel(result.generated_at);
      el('liveAnalysisStatus').textContent = '';
      el('liveAnalysisContent').hidden = false;
    } catch (_) {
      if (analysisActive === controller) el('liveAnalysisStatus').textContent = 'L’analyse automatique est momentanément indisponible. Les statistiques restent consultables.';
    } finally {
      clearTimeout(timer);
      if (analysisActive === controller) {
        analysisActive = null;
        el('liveAnalysis').removeAttribute('aria-busy');
        el('liveAnalysisStatus').classList.remove('is-loading');
      }
    }
  }
  function setCompetitions(list, selected) {
    const all = document.createElement('option');
    all.value = ''; all.textContent = 'Toutes les compétitions';
    const options = [all];
    const featured = list.filter(comp => comp.featured);
    const others = list.filter(comp => !comp.featured);
    const option = comp => {
      if (!Number.isSafeInteger(comp.id) || typeof comp.name !== 'string') throw new Error('Compétition non reconnue.');
      const item = document.createElement('option');
      item.value = String(comp.id);
      item.textContent = `${comp.name}${comp.country ? ' · ' + comp.country : ''} (${comp.count})`;
      item.selected = comp.id === selected;
      return item;
    };
    for (const [label, group] of [['À la une', featured], ['Toutes les compétitions du jour', others]]) {
      if (!group.length) continue;
      const optgroup = document.createElement('optgroup');
      optgroup.label = label;
      optgroup.append(...group.map(option));
      options.push(optgroup);
    }
    el('liveCompetition').replaceChildren(...options);
    el('liveCompetitionHelp').textContent = list.length
      ? `${list.length} compétition(s) ce jour-là. Choisis-en une pour filtrer les matchs.`
      : 'Aucune compétition trouvée pour ce jour.';
  }

  el('liveCompetition').addEventListener('change', () => el('liveForm').requestSubmit());

  el('liveForm').addEventListener('input', event => {
    if (event.target === el('liveSport') || event.target === el('liveDate')) {
      setCompetitions([], null);
      el('liveCompetitionHelp').textContent = 'La liste se remplit avec les compétitions du jour après une recherche.';
    }
    if (active) active.abort();
    active = null;
    el('liveFields').disabled = false;
    el('liveForm').removeAttribute('aria-busy');
    clearSelection();
    el('liveMatches').replaceChildren();
    el('liveFreshness').hidden = true;
    el('liveStatus').textContent = 'Recherche modifiée. Clique sur Chercher les matchs.';
    el('liveStatus').classList.remove('is-loading');
  });

  async function load(path, render, searching) {
    if (active) active.abort();
    const controller = new AbortController();
    active = controller;
    clearSelection();
    el('liveFields').disabled = searching;
    el('liveForm').setAttribute('aria-busy', 'true');
    el('liveStatus').textContent = searching ? 'Recherche des matchs' : 'Chargement de la fiche du match';
    el('liveStatus').classList.add('is-loading');
    const timer = setTimeout(() => controller.abort(), searching ? 15000 : 25000);
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
        el('liveStatus').classList.remove('is-loading');
        el('liveFields').disabled = false;
        el('liveForm').removeAttribute('aria-busy');
      }
    }
  }

  function showMatch(id, button) {
    el('liveMatches').querySelectorAll('.is-loading').forEach(other => other.classList.remove('is-loading'));
    button.classList.add('is-loading');
    button.setAttribute('aria-busy', 'true');
    load(`/api/ai/matches/${id}`, data => {
      const game = data.match;
      if (!game || game.id !== id || !game.home || !game.away || !Array.isArray(data.statistics)) throw new Error('Rencontre non reconnue.');
      el('liveReportTitle').replaceChildren(teamName(game.home), element('em', ' vs '), teamName(game.away));
      emblem(game.home, el('homeEmblem'));
      emblem(game.away, el('awayEmblem'));
      el('liveMatchMeta').textContent = new Date(game.starts_at).toLocaleString('fr-FR', {dateStyle:'medium', timeStyle:'short', timeZone:'Europe/Paris'}) + ' (Paris)';
      el('fixturePhase').textContent = phase(game);
      el('fixtureCompetition').textContent = game.competition.replace(/UEFA Nations League/i, 'Ligue des nations');
      el('fixtureSourceId').textContent = 'Référence du match : ' + game.id + '.';
      el('liveScore').textContent = score(game);
      el('liveScore').hidden = game.scheduled;
      if (game.scheduled) el('reportColumns').after(el('reportMatchData'));
      else el('reportViews').before(el('reportMatchData'));
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
      el('liveRecent').hidden = !data.history_notice;
      el('reportViews').hidden = !data.history_notice;
      el('jumpResults').hidden = !data.history_notice;
      highlights(game, data.recent_results);
      showPrediction(data.prediction, data);
      showModel(data);
      showForm(data);
      el('liveRecentNotice').textContent = data.history_notice || '';
      el('liveRecentTeams').replaceChildren(...['home', 'away'].map(side => {
        const section = document.createElement('div');
        const heading = document.createElement('h4');
        heading.textContent = game[side].name;
        section.append(heading);
        const results = (data.recent_results?.[side] || []).slice(0, 5);
        if (!results.length) {
          const empty = document.createElement('p');
          empty.className = 'sub'; empty.textContent = 'Aucun résultat récent vérifié disponible.';
          section.append(empty);
        }
        if (results.length) {
          const list = document.createElement('ul');
          list.className = 'recent-list';
          list.append(...results.map(result => recentRow(result, game[side].id)));
          section.append(list);
        }
        return section;
      }));
      el('liveReport').hidden = false;
      window.betTracker.select(game);
      button.setAttribute('aria-pressed', 'true');
      el('liveStatus').textContent = '';
      el('liveReport').focus();
      loadAnalysis(data);
    }, false).finally(() => {
      button.classList.remove('is-loading');
      button.removeAttribute('aria-busy');
    });
  }

  el('liveForm').addEventListener('submit', event => {
    event.preventDefault();
    if (el('liveFields').disabled || !el('liveForm').reportValidity()) return;
    el('liveMatches').replaceChildren();
    el('liveFreshness').hidden = true;
    const query = new URLSearchParams({sport: el('liveSport').value, date: el('liveDate').value, q: el('liveQuery').value.trim()});
    if (el('liveCompetition').value) query.set('competition', el('liveCompetition').value);
    load('/api/ai/matches?' + query, data => {
      if (!Array.isArray(data.matches)) throw new Error('Liste de rencontres non reconnue.');
      if (Array.isArray(data.competitions)) setCompetitions(data.competitions, data.competition);
      const buttons = data.matches.map(game => {
        if (!Number.isSafeInteger(game.id) || !game.home || !game.away) throw new Error('Rencontre non reconnue.');
        const button = document.createElement('button');
        button.type = 'button'; button.setAttribute('aria-pressed', 'false');
        const title = document.createElement('strong');
        title.textContent = `${game.home.name} — ${game.away.name}`;
        const meta = document.createElement('span');
        meta.textContent = [game.competition, dateLabel(game.starts_at), phase(game), game.scheduled ? '' : score(game)].filter(Boolean).join(' · ');
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
