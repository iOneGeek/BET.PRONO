"""Deterministic form summary, score model and pick, built from verified recent results.

The model stays small and transparent:
- weighted averages of goals scored and conceded over up to ten recent results, the most recent
  counting more, shrunk toward a sport baseline when the sample is small;
- a light home advantage;
- Poisson score probabilities, with the Dixon-Coles correction of low scores in football;
- a pick: the most likely outcome, its most likely score, and the scorer most likely to score.

It is a reference point, not a guarantee; the stored track record measures how it actually performs.
"""
import math

# Typical goals per team and per game, and a mild home advantage.
BASELINE = {'Football': 1.35, 'Hockey sur glace': 2.9}
HOME_FACTOR = {'Football': 1.10, 'Hockey sur glace': 1.04}
# Dixon-Coles dependence for low football scores (0-0 and 1-1 slightly more likely than Poisson says).
DIXON_COLES_RHO = {'Football': -0.08}
PRIOR_GAMES = 3
RECENCY = 0.85          # Weight of each older result relative to the next more recent one.
MAX_GOALS = 10
MIN_RESULTS = 3
# A player whose line-up status is unknown may not start.
AVAILABILITY = {'confirmed': 1.0, 'probable': 0.9, 'unknown': 0.8}
MIN_SCORER_PROBABILITY = 0.15
SEASON_PRIOR_GAMES = 4     # Season ratings are pulled toward average while few games are played.
SEASON_WEIGHT = 0.55       # Share of the season-strength estimate when the league table is available.
ABSENCE_IMPACT = 0.5       # Share of a missing scorer's goals assumed lost (team-mates cover the rest).
MIN_ATTACK_FACTOR = 0.75
# Below this chance for the most likely outcome, the match is flagged as too close to call.
TIGHT_THRESHOLD = {'Football': 0.45, 'Hockey sur glace': 0.42}


def _goals(result, team_id, sport):
    """Goals for/against of `team_id` in a past result. Hockey uses the end-of-regulation score."""
    score = result.get('regulation') if sport == 'Hockey sur glace' else None
    home = score['home'] if score else result['home']['score']
    away = score['away'] if score else result['away']['score']
    if home is None or away is None:
        return None
    if result['home']['id'] == team_id:
        return home, away, True
    if result['away']['id'] == team_id:
        return away, home, False
    return None


def team_form(results, team_id, sport):
    """Plain record over the given results (most recent first) plus recency-weighted goal averages."""
    games = [g for g in (_goals(r, team_id, sport) for r in results) if g]
    if not games:
        return None
    wins = sum(1 for f, a, _ in games if f > a)
    draws = sum(1 for f, a, _ in games if f == a)
    at_home = [g for g in games if g[2]]
    away = [g for g in games if not g[2]]
    weights = [RECENCY ** index for index in range(len(games))]
    total = sum(weights)

    def record(subset):
        return {'played': len(subset), 'wins': sum(1 for f, a, _ in subset if f > a),
                'draws': sum(1 for f, a, _ in subset if f == a), 'losses': sum(1 for f, a, _ in subset if f < a)}
    return {'played': len(games), 'wins': wins, 'draws': draws, 'losses': len(games) - wins - draws,
            'scored_avg': round(sum(f for f, _, _ in games) / len(games), 2),
            'conceded_avg': round(sum(a for _, a, _ in games) / len(games), 2),
            'scored_weighted': round(sum(w * f for w, (f, _, _) in zip(weights, games)) / total, 3),
            'conceded_weighted': round(sum(w * a for w, (_, a, _) in zip(weights, games)) / total, 3),
            'clean_sheets': sum(1 for _, a, _ in games if a == 0),
            'both_scored': sum(1 for f, a, _ in games if f and a),
            'home': record(at_home), 'away': record(away)}


def head_to_head_summary(meetings, home_id):
    if not meetings:
        return None
    wins = draws = losses = 0
    for result in meetings:
        if result['home']['score'] is None or result['away']['score'] is None:
            continue
        ours = result['home']['score'] if result['home']['id'] == home_id else result['away']['score']
        theirs = result['away']['score'] if result['home']['id'] == home_id else result['home']['score']
        wins += ours > theirs
        draws += ours == theirs
        losses += ours < theirs
    played = wins + draws + losses
    return {'played': played, 'home_wins': wins, 'draws': draws, 'away_wins': losses} if played else None


def _poisson(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _dixon_coles(h, a, lam_home, lam_away, rho):
    if not rho or h > 1 or a > 1:
        return 1.0
    if h == 0 and a == 0:
        return 1 - lam_home * lam_away * rho
    if h == 0 and a == 1:
        return 1 + lam_home * rho
    if h == 1 and a == 0:
        return 1 + lam_away * rho
    return 1 - rho


def _forms(data):
    game = data['match']
    history = data.get('recent_results', {})
    return {side: team_form(history.get(side, []), game[side]['id'], game.get('sport')) for side in ('home', 'away')}


def _season_expected(data, base, factor):
    """Expected goals from season strength: attack and defence relative to this competition's average."""
    table = data.get('standings')
    if not table or any(table[side]['played'] < 3 for side in ('home', 'away')):
        return None

    def rating(value, played):
        return (value / played / base * played + SEASON_PRIOR_GAMES) / (played + SEASON_PRIOR_GAMES)
    home, away = table['home'], table['away']
    home_attack, home_defence = rating(home['scored'], home['played']), rating(home['conceded'], home['played'])
    away_attack, away_defence = rating(away['scored'], away['played']), rating(away['conceded'], away['played'])
    return base * home_attack * away_defence * factor, base * away_attack * home_defence / factor


def _absence_factors(data):
    """Attack reduction for each side from missing scorers, with a readable note for each."""
    factors, notes = {'home': 1.0, 'away': 1.0}, []
    table = data.get('standings') or {}
    game = data['match']
    for side in ('home', 'away'):
        team_goals = (table.get(side) or {}).get('scored')
        for player in (data.get('absences') or {}).get(side, []):
            goals = player.get('goals')
            if player.get('status') != 'missing' or not goals:
                continue
            share = min(0.5, goals / team_goals) if team_goals else min(0.3, goals / 20)
            factors[side] *= 1 - ABSENCE_IMPACT * share
            notes.append(f"Absence de {player['name']} ({goals} buts) : attaque de {game[side]['name']} réduite")
        factors[side] = max(MIN_ATTACK_FACTOR, factors[side])
    return factors, notes


def poisson_model(data, form=None):
    """Expected goals, outcome and score probabilities, or None without three verified results per team."""
    game = data['match']
    sport = game.get('sport')
    if sport not in BASELINE:
        return None
    form = form or _forms(data)
    if any(not f or f['played'] < MIN_RESULTS for f in form.values()):
        return None
    table = data.get('standings') or {}
    # The competition's own scoring level when its table is known; the sport average otherwise.
    league = table.get('league_goals_per_team')
    base = league if isinstance(league, (int, float)) and 0.3 < league < 6 else BASELINE[sport]

    def shrink(value, played):
        return (value * played + base * PRIOR_GAMES) / (played + PRIOR_GAMES)
    home_attack = shrink(form['home']['scored_weighted'], form['home']['played'])
    home_defence = shrink(form['home']['conceded_weighted'], form['home']['played'])
    away_attack = shrink(form['away']['scored_weighted'], form['away']['played'])
    away_defence = shrink(form['away']['conceded_weighted'], form['away']['played'])
    factor = HOME_FACTOR[sport]
    lam_home = (home_attack + away_defence) / 2 * factor
    lam_away = (away_attack + home_defence) / 2 / factor
    season = _season_expected(data, base, factor)
    if season:
        lam_home = (1 - SEASON_WEIGHT) * lam_home + SEASON_WEIGHT * season[0]
        lam_away = (1 - SEASON_WEIGHT) * lam_away + SEASON_WEIGHT * season[1]
    absence, notes = _absence_factors(data)
    lam_home = max(0.2, min(6.0, lam_home * absence['home']))
    lam_away = max(0.2, min(6.0, lam_away * absence['away']))
    rho = DIXON_COLES_RHO.get(sport, 0)
    grid = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            grid[h, a] = max(0.0, _poisson(h, lam_home) * _poisson(a, lam_away) * _dixon_coles(h, a, lam_home, lam_away, rho))
    total = sum(grid.values())
    grid = {score: p / total for score, p in grid.items()}
    line = 2.5 if sport == 'Football' else 5.5
    probabilities = {'home': sum(p for (h, a), p in grid.items() if h > a),
                     'draw': sum(p for (h, a), p in grid.items() if h == a),
                     'away': sum(p for (h, a), p in grid.items() if h < a)}
    best = max(grid, key=grid.get)
    return {
        'method': 'Poisson + Dixon-Coles' if rho else 'Poisson',
        'expected_goals': {'home': round(lam_home, 2), 'away': round(lam_away, 2)},
        'probabilities': {k: round(v, 3) for k, v in probabilities.items()},
        'double_chance': {'home_or_draw': round(probabilities['home'] + probabilities['draw'], 3),
                          'away_or_draw': round(probabilities['away'] + probabilities['draw'], 3)},
        'likely_score': {'home': best[0], 'away': best[1], 'probability': round(grid[best], 3)},
        'likely_outcome': max(probabilities, key=probabilities.get),
        'over': {'line': line, 'probability': round(sum(p for (h, a), p in grid.items() if h + a > line), 3)},
        'both_score': round(sum(p for (h, a), p in grid.items() if h and a), 3),
        'sample': {side: form[side]['played'] for side in ('home', 'away')},
        'regulation_only': sport == 'Hockey sur glace',
        'inputs': {'league_average': round(base, 2), 'league_from_table': base != BASELINE[sport],
                   'season_strength': bool(season), 'absences': notes},
        '_grid': grid,
    }


def scorer_probabilities(data, model, form):
    """Chance that each candidate scores at least once, from his scoring rate and this game's expected goals."""
    out = []
    for player in data.get('scorer_candidates', []):
        apps = player.get('appearances')
        if not isinstance(apps, int) or apps < 1 or not player.get('goals'):
            continue
        rate = min(1.2, player['goals'] / apps)
        side = player['side']
        usual = max(0.3, form[side]['scored_weighted'] if form.get(side) else BASELINE.get(data['match'].get('sport'), 1.35))
        matchup = max(0.5, min(1.8, model['expected_goals'][side] / usual))
        lam = rate * matchup * AVAILABILITY.get(player.get('lineup'), 0.8)
        out.append({**player, 'probability': round(1 - math.exp(-lam), 3)})
    return sorted(out, key=lambda p: (-p['probability'], p['id']))


def predict(data):
    """The pick shown to users: most likely outcome, its most likely score, and the likeliest scorer."""
    game = data['match']
    if not game.get('scheduled'):
        return None
    form = _forms(data)
    model = poisson_model(data, form)
    if not model:
        return None
    winner = model['likely_outcome']
    grid = model['_grid']

    def same_outcome(score):
        h, a = score
        return winner == ('home' if h > a else 'away' if h < a else 'draw')
    home_goals, away_goals = max((s for s in grid if same_outcome(s)), key=grid.get)
    options = scorer_probabilities(data, model, form)
    scoring_sides = {side for side, goals in (('home', home_goals), ('away', away_goals)) if goals > 0}
    scorer = next((p for p in options if p['side'] in scoring_sides and p['probability'] >= MIN_SCORER_PROBABILITY), None)
    odds = data.get('odds') or {}
    market = odds.get('result')
    sport = game['sport']
    names = {'home': game['home']['name'], 'away': game['away']['name']}
    markets = []
    if winner != 'draw':
        key = f'{winner}_or_draw'
        markets.append({'key': key, 'label': f"{names[winner]} ou nul", 'probability': model['double_chance'][key],
                        'market': round(market[winner] + market['draw'], 3) if market else None})
    over = model['over']
    over_side = over['probability'] >= 0.5
    market_over = odds.get('over') if (odds.get('over') or {}).get('line') == over['line'] else None
    markets.append({'key': 'over' if over_side else 'under',
                    'label': f"{'Plus' if over_side else 'Moins'} de {str(over['line']).replace('.', ',')} buts",
                    'probability': round(over['probability'] if over_side else 1 - over['probability'], 3),
                    'market': None if not market_over else round(market_over['probability'] if over_side else 1 - market_over['probability'], 3)})
    both = model['both_score'] >= 0.5
    market_both = odds.get('both_score')
    markets.append({'key': 'both_score' if both else 'not_both_score',
                    'label': 'Les deux équipes marquent' if both else 'Au moins une équipe ne marque pas',
                    'probability': round(model['both_score'] if both else 1 - model['both_score'], 3),
                    'market': None if market_both is None else round(market_both if both else 1 - market_both, 3)})
    markets.sort(key=lambda m: -m['probability'])
    confidence = model['probabilities'][winner]
    return {'source': 'model', 'home_goals': home_goals, 'away_goals': away_goals, 'winner': winner,
            'confidence': confidence, 'score_probability': round(grid[home_goals, away_goals], 3),
            'tight': confidence < TIGHT_THRESHOLD.get(sport, 0.45),
            'probabilities': model['probabilities'], 'market': market,
            'markets': markets, 'adjustments': model['inputs']['absences'],
            'scorer': scorer, 'scorer_options': options[:4]}


def enrich(data):
    """Derived, server-computed figures added to a match snapshot (never sent by the browser)."""
    game = data['match']
    empty = {'form': {'home': None, 'away': None}, 'head_to_head_summary': None, 'model': None, 'prediction': None}
    if not all(isinstance(game.get(side), dict) for side in ('home', 'away')):
        return empty
    form = _forms(data)
    model = poisson_model(data, form) if game.get('scheduled') else None
    public_model = {k: v for k, v in model.items() if not k.startswith('_')} if model else None
    return {'form': form, 'head_to_head_summary': head_to_head_summary(data.get('head_to_head', []), game['home']['id']),
            'model': public_model, 'prediction': predict(data) if model else None}
