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

  function clearSelection() {
    window.betTracker.clear();
    if (analysisActive) analysisActive.abort();
    analysisActive = null;
    el('liveAnalysis').removeAttribute('aria-busy');
    el('liveAnalysisContent').hidden = true;
    el('livePrediction').hidden = true;
    el('livePredictionStatus').hidden = true;
    el('liveAnalysisStatus').textContent = '';
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
    el('livePredictionWinner').textContent = winner === 'draw' ? 'Match nul envisagé' : game[winner].name;
    el('livePredictionScore').textContent = `${game.home.name} ${home} — ${away} ${game.away.name}`;
    el('livePredictionScorer').textContent = 'Aucun buteur proposé';
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
        const evidence = document.createElement('p'); evidence.className = 'sub';
        evidence.textContent = 'Données citées : ' + point.evidence.join(' · ');
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
      el('liveAnalysisStatus').textContent = 'Analyse disponible, fondée sur les données affichées.';
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
      el('liveRecent').hidden = !data.history_notice;
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
        for (const result of results) {
          const item = document.createElement('p');
          item.className = 'sub';
          item.textContent = `${dateLabel(result.starts_at)} · ${result.competition} · ${result.home.name} ${score(result)} ${result.away.name}`;
          section.append(item);
        }
        return section;
      }));
      el('liveReport').hidden = false;
      window.betTracker.select(game);
      button.setAttribute('aria-pressed', 'true');
      el('liveStatus').textContent = 'Données du match chargées. Préparation de l’analyse…';
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
