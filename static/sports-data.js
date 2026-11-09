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
    info.append(label, element('small', (atHome ? 'Domicile' : 'Extérieur') + ' · ' + result.competition));
    const tally = element('abbr', ownGoals + ' — ' + otherGoals, 'result-score');
    tally.dataset.outcome = outcome;
    tally.title = outcome;
    tally.setAttribute('aria-label', outcome + ', ' + ownGoals + ' à ' + otherGoals);
    row.append(metadata, info, tally);
    return row;
  }

  function clearSelection() {
    setFormView(false);
    el('forecastSources').hidden = true;
    el('jumpPrediction').hidden = true;
    window.betTracker.clear();
    if (analysisActive) analysisActive.abort();
    analysisActive = null;
    el('liveAnalysis').removeAttribute('aria-busy');
    el('liveAnalysisContent').hidden = true;
    el('livePrediction').hidden = true;
    el('livePredictionStatus').hidden = true;
    el('liveAnalysisStatus').textContent = '';
    el('liveReport').querySelectorAll('.report-disclosure[open]').forEach(detail => { detail.open = false; });
    el('liveReport').hidden = true;
    el('liveError').hidden = true;
    el('liveMatches').querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', 'false'));
  }

  function showPrediction(prediction, snapshot) {
    const game = snapshot.match;
    if (!game.scheduled || new Date(game.starts_at) <= new Date()) return;
    if (prediction == null) {
      el('livePredictionStatus').textContent = 'Pronostic indisponible pour cette rencontre. Il nécessite au moins trois résultats récents vérifiés par équipe et une estimation exploitable.';
      el('livePredictionStatus').hidden = false;
      return;
    }
    const {home_goals: home, away_goals: away} = prediction;
    if (![home, away].every(value => Number.isInteger(value) && value >= 0 && value <= 10)
        || !Array.isArray(prediction.evidence)) throw new Error('Invalid prediction');
    const winner = home === away ? 'draw' : home > away ? 'home' : 'away';
    if (prediction.winner !== winner) throw new Error('Inconsistent prediction');
    el('livePredictionWinner').textContent = winner === 'draw' ? 'Match nul envisagé' : teamName(game[winner]);
    el('livePredictionScore').replaceChildren(
      element('span', game.home.name, 'ai-sr-only'), ' ',
      element('strong', home + ' — ' + away), ' ',
      element('span', game.away.name, 'ai-sr-only')
    );
    el('livePredictionScorer').textContent = 'Non proposé';
    el('livePredictionScorerNote').textContent = '';
    if (prediction.scorer != null) {
      const player = (snapshot.scorer_candidates || []).find(candidate => candidate.id === prediction.scorer.id);
      if (!player || (player.side === 'home' ? home : away) === 0) throw new Error('Invalid scorer');
      el('livePredictionScorer').textContent = `${player.name} · ${player.team_name}`;
      el('livePredictionScorerNote').textContent = `${player.goals} buts indiqués par 365Scores (période non précisée). `
        + (player.lineup_confirmed ? 'Présence annoncée par la source.' : 'Participation possible, composition à confirmer.');
    }
    el('livePredictionEvidence').replaceChildren(...prediction.evidence.map(text => {
      const item = document.createElement('li'); item.textContent = text; return item;
    }));
    el('livePredictionTitle').textContent = game.sport === 'Hockey sur glace' ? 'Pronostic avant-match · temps réglementaire' : 'Pronostic avant-match';
    el('forecastScoreLabel').textContent = game.sport === 'Hockey sur glace' ? 'Score estimé · temps réglementaire' : 'Score estimé';
    el('forecastSources').hidden = false;
    el('jumpPrediction').hidden = false;
    el('livePrediction').hidden = false;
  }

  async function loadAnalysis(snapshot) {
    const controller = new AbortController();
    analysisActive = controller;
    el('liveAnalysis').setAttribute('aria-busy', 'true');
    el('liveAnalysisStatus').textContent = 'Préparation de l’analyse à partir des données du match…';
    const timer = setTimeout(() => controller.abort(), 35000);
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
      showPrediction(result.prediction, snapshot);
      el('liveAnalysisStatus').textContent = '';
      el('liveAnalysisContent').hidden = false;
    } catch (_) {
      if (analysisActive === controller) el('liveAnalysisStatus').textContent = 'L’analyse automatique est momentanément indisponible. Les statistiques restent consultables.';
    } finally {
      clearTimeout(timer);
      if (analysisActive === controller) {
        analysisActive = null;
        el('liveAnalysis').removeAttribute('aria-busy');
      }
    }
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
        el('liveFields').disabled = false;
        el('liveForm').removeAttribute('aria-busy');
      }
    }
  }

  function showMatch(id, button) {
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
      el('liveRecentNotice').textContent = data.history_notice || '';
      el('liveRecentTeams').replaceChildren(...['home', 'away'].map(side => {
        const section = document.createElement('div');
        const heading = document.createElement('h4');
        heading.textContent = game[side].name;
        section.append(heading);
        const results = data.recent_results?.[side] || [];
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
    }, false);
  }

  el('liveForm').addEventListener('submit', event => {
    event.preventDefault();
    if (el('liveFields').disabled || !el('liveForm').reportValidity()) return;
    el('liveMatches').replaceChildren();
    el('liveFreshness').hidden = true;
    const query = new URLSearchParams({sport: el('liveSport').value, date: el('liveDate').value, q: el('liveQuery').value.trim()});
    load('/api/ai/matches?' + query, data => {
      if (!Array.isArray(data.matches)) throw new Error('Liste de rencontres non reconnue.');
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
