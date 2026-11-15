"""Experimental read-only adapter for the public 365Scores web service.

No credentials, browser impersonation, redirects, odds or predictions. The web
schema is not a documented partner contract: unexpected data fails explicitly.
"""
from collections import OrderedDict, deque
from datetime import datetime, timezone
import json
import math
import re
import threading
import time
import unicodedata
from zoneinfo import ZoneInfo

import requests


class SportsDataError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def text(value, limit=160):
    return value[:limit] if isinstance(value, str) else ''


def search_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value).casefold()
                   if not unicodedata.combining(c))


def positive_id(value):
    return type(value) is int and 0 < value < 10**12


SPORTS = {1: 'Football', 4: 'Hockey sur glace'}

# French labels for the provider's English competition names.
COMPETITION_LABELS = {
    'UEFA Champions League': 'Ligue des champions',
    'UEFA Europa League': 'Ligue Europa',
    'UEFA Conference League': 'Ligue Europa Conférence',
    'UEFA Europa Conference League': 'Ligue Europa Conférence',
    'UEFA Nations League': 'Ligue des nations',
    'Friendly International': 'Matchs amicaux internationaux',
    'World Cup Qualification UEFA': 'Qualifications Coupe du monde (Europe)',
}
# Shown first, in this order, whatever the provider popularity says.
FEATURED_COMPETITIONS = ('Ligue 1', 'Ligue 2', 'Coupe de France', 'Ligue des champions', 'Ligue Europa',
                         'Ligue Europa Conférence', 'Ligue des nations')


def competition_label(name):
    name = ' '.join(name.split())
    return COMPETITION_LABELS.get(name, name)


def competition_list(data, games):
    """Competitions present in the given games, featured first, then by provider popularity."""
    counts = {}
    for game in games:
        if game['competition_id']:
            counts[game['competition_id']] = counts.get(game['competition_id'], 0) + 1
    countries = {country['id']: text(country.get('name'), 60) for country in data.get('countries', [])[:400]
                 if isinstance(country, dict) and positive_id(country.get('id'))}
    known = {comp['id']: comp for comp in data.get('competitions', [])[:600]
             if isinstance(comp, dict) and positive_id(comp.get('id'))}
    items = []
    for comp_id, count in counts.items():
        comp = known.get(comp_id, {})
        name = competition_label(text(comp.get('name'), 80))
        if not name:
            name = competition_label(next(g['competition'] for g in games if g['competition_id'] == comp_id))
        country = '' if comp.get('isInternational') else countries.get(comp.get('countryId'), '')
        rank = comp.get('popularityRank')
        rank = rank if type(rank) in (int, float) and math.isfinite(rank) else 0
        featured = (FEATURED_COMPETITIONS.index(name) if name in FEATURED_COMPETITIONS
                    and (comp.get('isInternational') or country in ('France', '')) else None)
        items.append(({'id': comp_id, 'name': name, 'country': country, 'count': count, 'featured': featured is not None},
                      (featured is None, featured or 0, -rank, name)))
    items.sort(key=lambda item: item[1])
    return [item[0] for item in items]


def normalize_game(raw):
    if not isinstance(raw, dict) or type(raw.get('sportId')) is not int or raw['sportId'] not in SPORTS or not positive_id(raw.get('id')):
        return None
    sides = []
    for key in ('homeCompetitor', 'awayCompetitor'):
        team = raw.get(key)
        if not isinstance(team, dict) or not positive_id(team.get('id')) or not text(team.get('name')):
            return None
        score = team.get('score')
        if type(score) not in (int, float) or not 0 <= score <= 1000000 or raw.get('statusGroup') == 2:
            score = None
        sides.append({'id': team['id'], 'name': text(team['name']), 'score': score})
    try:
        start = datetime.fromisoformat(raw.get('startTime', '').replace('Z', '+00:00'))
        if start.tzinfo is None:
            return None
    except (ValueError, TypeError, AttributeError):
        return None
    competition_id = raw.get('competitionId')
    return {'id': raw['id'], 'sport': SPORTS[raw['sportId']],
            'competition_id': competition_id if positive_id(competition_id) else None, 'competition': text(raw.get('competitionDisplayName')) or 'Compétition non précisée',
            'starts_at': start.isoformat(), 'status': text(raw.get('statusText')) or 'Statut non précisé',
            'scheduled': raw.get('statusGroup') == 2,
            'live': raw.get('statusGroup') == 3,
            'home': sides[0], 'away': sides[1], **decision(raw, sides)}


def decision(raw, sides):
    """How a finished game was decided, and the score at the end of regulation when it can be derived.

    Overtime is sudden death and a shootout adds one goal to the winner, so a hockey game decided after
    regulation was tied at the loser's score. A football game that needed extra time was a draw after 90
    minutes, but its exact 90-minute score is not in the list payload.
    """
    if raw.get('statusGroup') != 4:
        return {'decided': None, 'regulation': None}
    status = ' '.join(text(raw.get(key), 60) for key in ('statusText', 'shortStatusText'))
    if re.search(r'\bSO\b|shoot.?out|penalt', status, re.I):
        decided = 'shootout' if raw.get('sportId') == 4 else 'penalties'
    elif re.search(r'\bOT\b|overtime|extra.?time|\bAET\b', status, re.I):
        decided = 'overtime' if raw.get('sportId') == 4 else 'extra_time'
    else:
        decided = 'regulation'
    home, away = sides[0]['score'], sides[1]['score']
    regulation = None
    if home is not None and away is not None and float(home).is_integer() and float(away).is_integer():
        if decided == 'regulation':
            regulation = {'home': int(home), 'away': int(away)}
        elif raw.get('sportId') == 4 and home != away:
            regulation = {'home': int(min(home, away)), 'away': int(min(home, away))}
    return {'decided': decided, 'regulation': regulation}


def absences(raw_game, game):
    """Players the source lists as missing or doubtful before the match, per side."""
    members = raw_game.get('members', [])
    names = {m['id']: text(m.get('name')) for m in members[:100] if isinstance(m, dict) and positive_id(m.get('id'))} \
        if isinstance(members, list) else {}
    # Goals of the club's top performers, to weigh what an absence costs.
    goals = {}
    categories = (raw_game.get('topPerformers') or {}).get('categories') if isinstance(raw_game.get('topPerformers'), dict) else None
    for category in (categories or [])[:10] if isinstance(categories, list) else []:
        for key in ('homePlayer', 'awayPlayer'):
            player = category.get(key) if isinstance(category, dict) else None
            if not isinstance(player, dict) or not positive_id(player.get('id')) or not isinstance(player.get('stats'), list):
                continue
            value = next((stat.get('value') for stat in player['stats'][:20] if isinstance(stat, dict)
                          and stat.get('type') == 1 and stat.get('name') == 'Goals'), None)
            if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 3:
                goals[player['id']] = int(value)
            if not names.get(player['id']) and text(player.get('name')):
                names[player['id']] = text(player['name'])
    out = {'home': [], 'away': []}
    for side, raw_side in (('home', 'homeCompetitor'), ('away', 'awayCompetitor')):
        lineup = (raw_game.get(raw_side) or {}).get('lineups')
        listed = lineup.get('members') if isinstance(lineup, dict) else None
        for member in (listed or [])[:60]:
            if not isinstance(member, dict) or not positive_id(member.get('id')):
                continue
            missing, doubtful = member.get('status') == 3, bool(member.get('isDoubtful'))
            if not (missing or doubtful):
                continue
            position = member.get('position') if isinstance(member.get('position'), dict) else {}
            out[side].append({'id': member['id'], 'name': names.get(member['id']) or 'Joueur non nommé',
                              'status': 'missing' if missing else 'doubtful',
                              'position': text(position.get('name'), 30), 'goals': goals.get(member['id'])})
    return out


def scorer_candidates(raw_game, game):
    """Scorer candidates from the provider's top performers, checked against the team and the line-up.

    Before line-ups are published (about an hour before kick-off), the club's leading scorers are
    proposed unless the source lists them as missing, doubtful or on the bench. Once starters are
    published, only listed attacking starters remain.
    """
    members = raw_game.get('members', [])
    performers = raw_game.get('topPerformers', {})
    if not isinstance(members, list) or not isinstance(performers, dict):
        return []
    categories = performers.get('categories', [])
    if not isinstance(categories, list):
        return []
    roster = {member['id']: member for member in members[:100] if isinstance(member, dict) and positive_id(member.get('id'))}
    candidates = {}
    hockey = game['sport'] == 'Hockey sur glace'
    for side, raw_side, player_key in (('home', 'homeCompetitor', 'homePlayer'), ('away', 'awayCompetitor', 'awayPlayer')):
        team = raw_game.get(raw_side, {})
        lineup = team.get('lineups') if isinstance(team, dict) else None
        if not isinstance(lineup, dict) or not isinstance(lineup.get('members'), list):
            lineup = {'members': []}
        listed = {member['id']: member for member in lineup['members'][:60]
                  if isinstance(member, dict) and positive_id(member.get('id'))}
        announced = any(member.get('status') == 1 for member in listed.values())
        starters = {member_id for member_id, member in listed.items() if member.get('status') == 1
                    and isinstance(member.get('position'), dict) and member['position'].get('id') in (3, 4)}
        for category in categories[:10]:
            player = category.get(player_key) if isinstance(category, dict) else None
            if not isinstance(player, dict) or not positive_id(player.get('id')):
                continue
            entry = listed.get(player['id'])
            if hockey:
                if (player.get('positionName') not in ('Center', 'Left Wing', 'Right Wing', 'Forward')
                        or (entry and (entry.get('status') != 1 or entry.get('isDoubtful')))):
                    continue
            elif announced:
                if player['id'] not in starters:
                    continue
            elif entry is not None:
                # Line-up not out yet: anyone the source lists (missing, doubtful, bench) is left out.
                continue
            member = roster.get(player['id'])
            if member is not None and member.get('competitorId') != game[side]['id']:
                continue
            name = text((member or {}).get('name')) or text(player.get('name'))
            if not name:
                continue
            stats = player.get('stats', [])
            if not isinstance(stats, list):
                continue
            goals = next((stat.get('value') for stat in stats[:20] if isinstance(stat, dict)
                          and stat.get('type') == 1 and stat.get('name') == 'Goals'), None)
            if not isinstance(goals, str) or not goals.isascii() or not goals.isdigit() or len(goals) > 3 or int(goals) == 0:
                continue
            apps = next((stat.get('value') for stat in stats[:20] if isinstance(stat, dict)
                         and stat.get('type') == 5 and stat.get('name') == 'Appearances'), None)
            apps = int(apps) if isinstance(apps, str) and apps.isascii() and apps.isdigit() and 0 < len(apps) <= 3 else None
            lineup_state = ('confirmed' if lineup.get('status') == 'Confirmed' and player['id'] in listed
                            else 'probable' if player['id'] in listed else 'unknown')
            candidates[player['id']] = {'id': player['id'], 'name': name,
                'team_id': game[side]['id'], 'team_name': game[side]['name'], 'side': side,
                'goals': int(goals), 'appearances': apps,
                'lineup_confirmed': lineup_state == 'confirmed', 'lineup': lineup_state}
    return list(candidates.values())[:6]


class Scores365Client:
    BASE = 'https://webws.365scores.com/web/'
    SOURCE = {'name': '365Scores', 'url': 'https://www.365scores.com/'}
    TTL = 60
    MAX_BYTES = 2 * 1024 * 1024

    def __init__(self):
        self._cache = OrderedDict()
        self._calls = deque()
        self._users = OrderedDict()
        self._lock = threading.RLock()
        self._blocked_until = 0

    def allow_user(self, user_id):
        with self._lock:
            now = time.monotonic()
            times = self._users.pop(user_id, deque())
            while times and now - times[0] >= 60:
                times.popleft()
            self._users[user_id] = times
            if len(self._users) > 4096:
                self._users.popitem(last=False)
            if len(times) >= 20:
                raise SportsDataError('Trop de demandes. Réessaie dans une minute.', 429)
            times.append(now)

    # Longer cache for slow-moving data; optional paths never pause the main access on failure.
    PATH_TTL = {'standings/': 1800, 'bets/lines/': 300}
    OPTIONAL_PATHS = ('standings/', 'bets/lines/')
    ODDS_COUNTRY = 1  # Odds are not served for the French locale; an international one is used, read-only.

    def _get(self, path, params, deadline=None):
        if path not in ('games/allscores/', 'game/stats/', 'game/', 'games/h2h/', 'standings/', 'bets/lines/'):
            raise ValueError('Unsupported provider path')
        ttl = self.PATH_TTL.get(path, self.TTL)
        key = (path, tuple(sorted(params.items())))
        # Serialize cache misses to prevent duplicate upstream calls from threads.
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(key)
            if cached and now - cached[0] < ttl:
                self._cache.move_to_end(key)
                return cached[1], cached[2], True
            if now < self._blocked_until:
                raise SportsDataError('365Scores est temporairement indisponible. Réessaie dans une minute.', 503)
            while self._calls and now - self._calls[0] >= 60:
                self._calls.popleft()
            if len(self._calls) >= 20:
                raise SportsDataError('Limite de consultation atteinte. Réessaie dans une minute.', 429)
            query = {'appTypeId': 5, 'langId': 1, 'timezoneName': 'Europe/Paris', **params}
            remaining = 20 if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                raise SportsDataError('Le délai de consultation des données est atteint.', 503)
            self._calls.append(now)
            try:
                with requests.get(self.BASE + path, params=query,
                                  headers={'User-Agent': 'BET.PRONO/0.1 (sports data)', 'Accept': 'application/json'},
                                  timeout=(min(3.05, remaining / 2), min(6, remaining / 2)), allow_redirects=False, stream=True) as response:
                    if response.status_code == 429:
                        self._blocked_until = time.monotonic() + 60
                        raise SportsDataError('Quota 365Scores atteint. Réessaie dans une minute.', 429)
                    if response.status_code != 200:
                        raise SportsDataError('365Scores est indisponible ou refuse cet accès.', 503)
                    if 'application/json' not in response.headers.get('Content-Type', '').lower():
                        raise SportsDataError('Réponse 365Scores non reconnue.')
                    body = bytearray()
                    for chunk in response.iter_content(16384):
                        if time.monotonic() - now > 10 or (deadline is not None and time.monotonic() > deadline):
                            raise SportsDataError('La réponse 365Scores a expiré.', 503)
                        body.extend(chunk)
                        if len(body) > self.MAX_BYTES:
                            raise SportsDataError('Réponse 365Scores trop volumineuse.')
                    data = json.loads(body)
                if not isinstance(data, dict):
                    raise SportsDataError('Le format des données 365Scores a changé.')
                if path in ('game/', 'games/h2h/'):
                    valid = isinstance(data.get('game'), dict)
                elif path == 'game/stats/' and 'games' not in data:
                    # Before kickoff the stats endpoint returns only its update envelope.
                    valid = all(type(data.get(key)) is int for key in ('lastUpdateId', 'requestedUpdateId', 'ttl'))
                elif path == 'standings/':
                    valid = isinstance(data.get('standings'), list)
                elif path == 'bets/lines/':
                    valid = isinstance(data.get('lines', []), list)
                else:
                    valid = isinstance(data.get('games'), list)
                if not valid:
                    raise SportsDataError('Le format des données 365Scores a changé.')
            except (requests.RequestException, ValueError, UnicodeError) as exc:
                if path not in self.OPTIONAL_PATHS:
                    self._blocked_until = time.monotonic() + 30
                raise SportsDataError('Impossible de récupérer les données 365Scores. Réessaie plus tard.', 503) from exc
            except SportsDataError:
                if path not in self.OPTIONAL_PATHS:
                    self._blocked_until = max(self._blocked_until, time.monotonic() + 30)
                raise
            fetched_at = datetime.now(timezone.utc).isoformat()
            self._cache[key] = (time.monotonic(), data, fetched_at)
            if len(self._cache) > 48:
                self._cache.popitem(last=False)
            return data, fetched_at, False

    def _standings(self, game, competition_id, deadline):
        """Season table of both teams and the competition's goals per team and game, if they share a table."""
        if not positive_id(competition_id):
            return None
        data, _, _ = self._get('standings/', {'competitions': competition_id}, deadline)
        rows = {}
        for table in data['standings'][:12]:
            for row in (table.get('rows') or [])[:60] if isinstance(table, dict) else []:
                team = row.get('competitor') if isinstance(row, dict) else None
                played, scored, conceded = row.get('gamePlayed'), row.get('for'), row.get('against')
                if (isinstance(team, dict) and positive_id(team.get('id')) and type(played) is int and played > 0
                        and all(type(v) in (int, float) and 0 <= v < 10000 for v in (scored, conceded))):
                    rows[team['id']] = {'played': played, 'scored': scored, 'conceded': conceded,
                                        'position': row.get('position') if type(row.get('position')) is int else None,
                                        'points': row.get('points') if type(row.get('points')) in (int, float) else None}
        if len(rows) < 4 or any(game[side]['id'] not in rows for side in ('home', 'away')):
            return None
        played = sum(r['played'] for r in rows.values())
        league = sum(r['scored'] for r in rows.values()) / played if played else None
        if not league:
            return None
        return {'home': rows[game['home']['id']], 'away': rows[game['away']['id']],
                'league_goals_per_team': round(league, 3), 'teams': len(rows)}

    def _odds(self, game, deadline):
        """Bookmaker probabilities (margin removed) for 1X2, total goals and both teams to score."""
        data, _, _ = self._get('bets/lines/', {'games': game['id'], 'userCountryId': self.ODDS_COUNTRY}, deadline)
        line_for_total = '2.5' if game['sport'] == 'Football' else '5.5'

        def implied(options, names):
            prices = {}
            for option in options if isinstance(options, list) else []:
                rate = (option.get('rate') or {}).get('decimal') if isinstance(option, dict) else None
                if option.get('name') in names and type(rate) in (int, float) and 1.0 < rate < 1000:
                    prices[option['name']] = 1 / rate
            if set(prices) != set(names):
                return None
            total = sum(prices.values())
            return {name: round(value / total, 3) for name, value in prices.items()}
        odds = {}
        for line in data.get('lines', [])[:200]:
            if not isinstance(line, dict) or line.get('gameId') != game['id'] or not isinstance(line.get('lineType'), dict):
                continue
            kind = line.get('lineTypeId')
            if kind == 1 and 'result' not in odds:
                result = implied(line.get('options'), ('1', 'X', '2'))
                if result:
                    odds['result'] = {'home': result['1'], 'draw': result['X'], 'away': result['2']}
            elif kind == 3 and str(line.get('internalOptionValue')) == line_for_total and 'over' not in odds:
                total = implied(line.get('options'), ('Under', 'Over'))
                if total:
                    odds['over'] = {'line': float(line_for_total), 'probability': total['Over']}
            elif kind == 12 and 'both_score' not in odds:
                both = implied(line.get('options'), ('Yes', 'No'))
                if both:
                    odds['both_score'] = both['Yes']
        return odds or None

    def matches(self, day, query='', sport=1, competition=None):
        data, fetched_at, cached = self._get('games/allscores/', {
            'sports': sport, 'startDate': day.strftime('%d/%m/%Y'), 'endDate': day.strftime('%d/%m/%Y'),
            'showOdds': 'false', 'onlyMajorGames': 'false'})
        games = []
        day_games = []
        skipped = 0
        seen = set()
        words = search_key(query).split()
        for raw in data['games']:
            game = normalize_game(raw)
            if not game:
                skipped += 1
                continue
            if raw['sportId'] != sport:
                continue
            # Provider day boundaries can include games from the previous day.
            if datetime.fromisoformat(game['starts_at']).astimezone(ZoneInfo('Europe/Paris')).date() != day:
                continue
            if game['id'] in seen:
                continue
            seen.add(game['id'])
            day_games.append(game)
            haystack = search_key(' '.join((game['home']['name'], game['away']['name'], game['competition'],
                                            competition_label(game['competition']))))
            if all(word in haystack for word in words) and (competition is None or game['competition_id'] == competition):
                games.append(game)
        games.sort(key=lambda game: (datetime.fromisoformat(game['starts_at']), game['id']))
        return {'mode': 'sports_data', 'matches': games[:200], 'total': len(games),
                'competitions': competition_list(data, day_games), 'competition': competition,
                'truncated': len(games) > 200, 'omitted_invalid': skipped,
                'source': self.SOURCE, 'fetched_at': fetched_at, 'cached': cached, 'cache_seconds': self.TTL}

    def _recent_results(self, raw_game, game, deadline):
        ids = set()
        for side in ('homeCompetitor', 'awayCompetitor'):
            recent = raw_game.get(side, {}).get('recentMatches', [])
            if isinstance(recent, list):
                ids.update(value for value in recent[:15] if positive_id(value) and value != game['id'])
        if not ids:
            return {'home': [], 'away': []}, None, True
        data, fetched_at, cached = self._get('games/allscores/', {
            'games': ','.join(str(value) for value in sorted(ids)), 'showOdds': 'false'}, deadline)
        cutoff = min(datetime.now(timezone.utc), datetime.fromisoformat(game['starts_at']))
        completed = {}
        for raw in data['games']:
            if not isinstance(raw, dict) or raw.get('statusGroup') != 4 or not positive_id(raw.get('id')) or raw['id'] not in ids:
                continue
            result = normalize_game(raw)
            if not result or result['sport'] != game['sport'] or datetime.fromisoformat(result['starts_at']) >= cutoff:
                continue
            if any(type(result[side]['score']) not in (int, float) or not float(result[side]['score']).is_integer()
                   for side in ('home', 'away')):
                continue
            completed[result['id']] = result
        ordered = sorted(completed.values(), key=lambda result: (datetime.fromisoformat(result['starts_at']), result['id']), reverse=True)
        history = {side: [result for result in ordered if game[side]['id'] in
                         (result['home']['id'], result['away']['id'])][:10] for side in ('home', 'away')}
        return history, fetched_at, cached

    def _head_to_head(self, game, deadline):
        """Up to five finished previous meetings of the same two teams, most recent first."""
        data, _, _ = self._get('games/h2h/', {'gameId': game['id']}, deadline)
        raw_games = data['game'].get('h2hGames', [])
        if not isinstance(raw_games, list):
            return []
        teams = {game['home']['id'], game['away']['id']}
        cutoff = datetime.fromisoformat(game['starts_at'])
        meetings = {}
        for raw in raw_games[:40]:
            if not isinstance(raw, dict) or raw.get('statusGroup') != 4:
                continue
            result = normalize_game(raw)
            if (not result or result['id'] == game['id'] or result['sport'] != game['sport']
                    or {result['home']['id'], result['away']['id']} != teams
                    or datetime.fromisoformat(result['starts_at']) >= cutoff
                    or any(result[side]['score'] is None for side in ('home', 'away'))):
                continue
            meetings[result['id']] = result
        return sorted(meetings.values(), key=lambda r: (datetime.fromisoformat(r['starts_at']), r['id']), reverse=True)[:5]

    def final_result(self, game_id):
        """Finished game with its goal scorers, to settle a stored prediction. None while not finished."""
        data, _, _ = self._get('game/', {'gameId': game_id})
        raw = data['game']
        game = normalize_game(raw)
        if not game or game['id'] != game_id:
            raise SportsDataError('Cette rencontre est introuvable.', 404)
        if raw.get('statusGroup') != 4:
            return {'match': game, 'finished': False, 'scorers': []}
        stages = {stage['id']: text(stage.get('name'), 40) for stage in raw.get('stages', [])[:24]
                  if isinstance(stage, dict) and positive_id(stage.get('id'))} if isinstance(raw.get('stages'), list) else {}
        scorers = []
        for event in raw.get('events', [])[:500] if isinstance(raw.get('events'), list) else []:
            kind = event.get('eventType') if isinstance(event, dict) else None
            if (not isinstance(kind, dict) or kind.get('name') != 'Goal' or not positive_id(event.get('playerId'))
                    or re.search(r'own', text(kind.get('subTypeName'), 40), re.I)
                    or re.search(r'shoot|penalt', stages.get(event.get('stageId'), ''), re.I)):
                continue
            scorers.append(event['playerId'])
        return {'match': game, 'finished': True, 'scorers': scorers}

    def match(self, game_id):
        deadline = time.monotonic() + 22
        data, fetched_at, cached = self._get('game/stats/', {'games': game_id}, deadline)
        raw_games = data.get('games', [])
        detail = None
        if not raw_games:
            detail, detail_fetched_at, detail_cached = self._get('game/', {'gameId': game_id}, deadline)
            raw_games = [detail['game']]
            fetched_at = min(fetched_at, detail_fetched_at)
            cached = cached and detail_cached
        raw_game = next((raw for raw in raw_games if isinstance(raw, dict) and raw.get('id') == game_id), None)
        game = normalize_game(raw_game)
        if not game:
            raise SportsDataError('Cette rencontre est introuvable ou ses données sont incomplètes.', 404)
        stats = data.get('statistics', [])
        if not isinstance(stats, list):
            raise SportsDataError('Le format des statistiques 365Scores a changé.')
        rows = OrderedDict()
        for stat in stats:
            if not isinstance(stat, dict) or not positive_id(stat.get('id')) or not text(stat.get('name')):
                continue
            # Only whole-match statistics; never mix period-specific figures.
            if stat.get('filterId', -1) != -1:
                continue
            side = next((side for side in ('home', 'away') if stat.get('competitorId') == game[side]['id']), None)
            value = stat.get('value')
            if side is None or not isinstance(value, (str, int, float)) or isinstance(value, bool):
                continue
            if isinstance(value, float) and not math.isfinite(value):
                continue
            row = rows.setdefault(stat['id'], {'label': text(stat['name']), 'home': None, 'away': None})
            row[side] = str(value)[:80]
        history = {'home': [], 'away': []}
        players = []
        head_to_head = []
        missing = {'home': [], 'away': []}
        standings = odds = None
        history_notice = ''
        if raw_game.get('statusGroup') == 2:
            try:
                if detail is None:
                    detail, detail_fetched_at, detail_cached = self._get('game/', {'gameId': game_id}, deadline)
                    verified = normalize_game(detail['game'])
                    if (not verified or verified['id'] != game_id or verified['sport'] != game['sport']
                            or not verified['scheduled'] or any(verified[s]['id'] != game[s]['id'] for s in ('home', 'away'))):
                        raise SportsDataError('Les informations du match ont changé. Actualise sa fiche.')
                    fetched_at = min(fetched_at, detail_fetched_at)
                    cached = cached and detail_cached
                players = scorer_candidates(detail['game'], game)
                missing = absences(detail['game'], game)
                missing_ids = {player['id'] for side in missing.values() for player in side if player['status'] == 'missing'}
                players = [player for player in players if player['id'] not in missing_ids]
                history, history_fetched_at, history_cached = self._recent_results(detail['game'], game, deadline)
                if history_fetched_at:
                    fetched_at = min(fetched_at, history_fetched_at)
                cached = cached and history_cached
                history_notice = 'Jusqu’à dix résultats récents disponibles par équipe. La couverture de la source peut être partielle.'
            except SportsDataError:
                history_notice = 'Les résultats récents sont temporairement indisponibles. Réessaie dans une minute.'
            try:
                head_to_head = self._head_to_head(game, deadline)
            except SportsDataError:
                head_to_head = []
            try:
                standings = self._standings(game, raw_game.get('competitionId'), deadline)
            except SportsDataError:
                standings = None
            try:
                odds = self._odds(game, deadline)
            except SportsDataError:
                odds = None
        return {'mode': 'sports_data', 'match': game, 'statistics': list(rows.values())[:40],
                'recent_results': history, 'history_notice': history_notice, 'head_to_head': head_to_head,
                'scorer_candidates': players, 'absences': missing, 'standings': standings, 'odds': odds,
                'source': self.SOURCE, 'fetched_at': fetched_at, 'cached': cached,
                'cache_seconds': self.TTL, 'prediction': None,
                'notice': 'Données fournies par 365Scores, potentiellement différées.'}

    def tracker(self, game_id):
        data, fetched_at, cached = self._get('game/', {'gameId': game_id})
        raw = data['game']
        game = normalize_game(raw)
        if not game or game['id'] != game_id:
            raise SportsDataError('Suivi indisponible pour cette rencontre.', 404)

        def records(key, limit):
            value = raw.get(key)
            return [row for row in value[:limit] if isinstance(row, dict)] if isinstance(value, list) else []

        def period_score(value):
            return int(value) if type(value) in (int, float) and 0 <= value < 1000 and int(value) == value else None

        periods = []
        stage_labels = {}
        for stage in records('stages', 24):
            label = text(stage.get('shortName'), 32) or text(stage.get('name'), 32)
            if not positive_id(stage.get('id')) or not label or label.casefold() in ('score', 'total'):
                continue
            stage_labels[stage['id']] = label
            periods.append({'label': label, 'current': stage.get('isCurrent') is True,
                            'home': period_score(stage.get('homeCompetitorScore')),
                            'away': period_score(stage.get('awayCompetitorScore'))})
        teams = {game[side]['id']: game[side]['name'] for side in ('home', 'away')}
        events = []
        for event in records('events', 500):
            kind = event.get('eventType')
            team = event.get('competitorId')
            if not isinstance(kind, dict) or not text(kind.get('name')) or not positive_id(team) or team not in teams:
                continue
            stage = event.get('stageId')
            events.append({'label': text(kind['name'], 64), 'team': teams[team],
                           'period': stage_labels.get(stage, '') if positive_id(stage) else '',
                           'time': text(event.get('gameTimeDisplay'), 16)})
        return {'match': game, 'periods': periods, 'events': events[-30:][::-1],
                'clock': text(raw.get('gameTimeDisplay'), 16), 'finished': raw.get('statusGroup') == 4,
                'fetched_at': fetched_at, 'cached': cached}
