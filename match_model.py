"""Deterministic form summary and a simple Poisson score model built from verified recent results.

The model is deliberately small and transparent: it averages goals scored and conceded in the
latest results, shrinks them toward a sport baseline when the sample is small, applies a light
home advantage, and turns the expected goals into score probabilities. It is a reference point,
not a validated forecast; the stored track record measures how it actually performs.
"""
import math

# Typical goals per team and per game, and a mild home advantage.
BASELINE = {'Football': 1.35, 'Hockey sur glace': 2.9}
HOME_FACTOR = {'Football': 1.10, 'Hockey sur glace': 1.04}
PRIOR_GAMES = 3
MAX_GOALS = 10
MIN_RESULTS = 3


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
    games = [g for g in (_goals(r, team_id, sport) for r in results) if g]
    if not games:
        return None
    wins = sum(1 for f, a, _ in games if f > a)
    draws = sum(1 for f, a, _ in games if f == a)
    at_home = [g for g in games if g[2]]
    away = [g for g in games if not g[2]]

    def record(subset):
        return {'played': len(subset), 'wins': sum(1 for f, a, _ in subset if f > a),
                'draws': sum(1 for f, a, _ in subset if f == a), 'losses': sum(1 for f, a, _ in subset if f < a)}
    return {'played': len(games), 'wins': wins, 'draws': draws, 'losses': len(games) - wins - draws,
            'scored_avg': round(sum(f for f, _, _ in games) / len(games), 2),
            'conceded_avg': round(sum(a for _, a, _ in games) / len(games), 2),
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


def poisson_model(data):
    """Expected goals and outcome probabilities, or None without three verified results per team."""
    game = data['match']
    sport = game.get('sport')
    if sport not in BASELINE:
        return None
    history = data.get('recent_results', {})
    form = {side: team_form(history.get(side, []), game[side]['id'], sport) for side in ('home', 'away')}
    if any(not f or f['played'] < MIN_RESULTS for f in form.values()):
        return None
    base = BASELINE[sport]

    def shrink(value, played):
        return (value * played + base * PRIOR_GAMES) / (played + PRIOR_GAMES)
    home_attack = shrink(form['home']['scored_avg'], form['home']['played'])
    home_defence = shrink(form['home']['conceded_avg'], form['home']['played'])
    away_attack = shrink(form['away']['scored_avg'], form['away']['played'])
    away_defence = shrink(form['away']['conceded_avg'], form['away']['played'])
    factor = HOME_FACTOR[sport]
    lam_home = max(0.2, min(6.0, (home_attack + away_defence) / 2 * factor))
    lam_away = max(0.2, min(6.0, (away_attack + home_defence) / 2 / factor))
    p_home = p_draw = p_away = over = both = 0.0
    best = (0, 0, -1.0)
    line = 2.5 if sport == 'Football' else 5.5
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = _poisson(h, lam_home) * _poisson(a, lam_away)
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
            if h + a > line:
                over += p
            if h and a:
                both += p
            if p > best[2]:
                best = (h, a, p)
    total = p_home + p_draw + p_away
    probabilities = {'home': p_home / total, 'draw': p_draw / total, 'away': p_away / total}
    favourite = max(probabilities, key=probabilities.get)
    return {
        'method': 'Poisson',
        'expected_goals': {'home': round(lam_home, 2), 'away': round(lam_away, 2)},
        'probabilities': {k: round(v, 3) for k, v in probabilities.items()},
        'likely_score': {'home': best[0], 'away': best[1], 'probability': round(best[2] / total, 3)},
        'likely_outcome': favourite,
        'over': {'line': line, 'probability': round(over / total, 3)},
        'both_score': round(both / total, 3),
        'sample': {side: form[side]['played'] for side in ('home', 'away')},
        'regulation_only': sport == 'Hockey sur glace',
    }


def enrich(data):
    """Derived, server-computed figures added to a match snapshot (never sent by the browser)."""
    game = data['match']
    if not all(isinstance(game.get(side), dict) for side in ('home', 'away')):
        return {'form': {'home': None, 'away': None}, 'head_to_head_summary': None, 'model': None}
    sport = game.get('sport')
    history = data.get('recent_results', {})
    form = {side: team_form(history.get(side, []), game[side]['id'], sport) for side in ('home', 'away')}
    return {'form': form, 'head_to_head_summary': head_to_head_summary(data.get('head_to_head', []), game['home']['id']),
            'model': poisson_model(data) if game.get('scheduled') else None}
