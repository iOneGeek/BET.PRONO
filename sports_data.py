"""Experimental read-only adapter for the public 365Scores web service.

No credentials, browser impersonation, redirects, odds or predictions. The web
schema is not a documented partner contract: unexpected data fails explicitly.
"""
from collections import OrderedDict, deque
from datetime import datetime, timezone
import json
import math
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
    return {'id': raw['id'], 'sport': SPORTS[raw['sportId']], 'competition': text(raw.get('competitionDisplayName')) or 'Compétition non précisée',
            'starts_at': start.isoformat(), 'status': text(raw.get('statusText')) or 'Statut non précisé',
            'scheduled': raw.get('statusGroup') == 2,
            'live': raw.get('statusGroup') == 3,
            'home': sides[0], 'away': sides[1]}


def scorer_candidates(raw_game, game):
    """Join named team members, listed starters and provider goal totals by ID."""
    members = raw_game.get('members', [])
    performers = raw_game.get('topPerformers', {})
    if not isinstance(members, list) or not isinstance(performers, dict):
        return []
    categories = performers.get('categories', [])
    if not isinstance(categories, list):
        return []
    roster = {member['id']: member for member in members[:100] if isinstance(member, dict) and positive_id(member.get('id'))}
    candidates = {}
    for side, raw_side, player_key in (('home', 'homeCompetitor', 'homePlayer'), ('away', 'awayCompetitor', 'awayPlayer')):
        team = raw_game.get(raw_side, {})
        lineup = team.get('lineups', {})
        if not isinstance(lineup, dict) or not isinstance(lineup.get('members'), list):
            continue
        listed = {member['id']: member for member in lineup['members'][:60]
                  if isinstance(member, dict) and positive_id(member.get('id'))}
        hockey = game['sport'] == 'Hockey sur glace'
        starters = {member['id'] for member in lineup['members'][:40] if isinstance(member, dict)
                    and positive_id(member.get('id')) and member.get('status') == 1
                    and isinstance(member.get('position'), dict) and member['position'].get('id') in (3, 4)}
        for category in categories[:10]:
            player = category.get(player_key) if isinstance(category, dict) else None
            if not isinstance(player, dict) or not positive_id(player.get('id')):
                continue
            if hockey:
                entry = listed.get(player['id'])
                if (player.get('positionName') not in ('Center', 'Left Wing', 'Right Wing', 'Forward')
                        or (entry and (entry.get('status') != 1 or entry.get('isDoubtful')))):
                    continue
            elif player['id'] not in starters:
                continue
            member = roster.get(player['id'], {})
            if member.get('competitorId') != game[side]['id'] or not text(member.get('name')):
                continue
            stats = player.get('stats', [])
            if not isinstance(stats, list):
                continue
            goals = next((stat.get('value') for stat in stats[:20] if isinstance(stat, dict)
                          and stat.get('type') == 1 and stat.get('name') == 'Goals'), None)
            if not isinstance(goals, str) or not goals.isascii() or not goals.isdigit() or len(goals) > 3:
                continue
            candidates[player['id']] = {'id': player['id'], 'name': text(member['name']),
                'team_id': game[side]['id'], 'team_name': game[side]['name'], 'side': side,
                'goals': int(goals), 'lineup_confirmed': lineup.get('status') == 'Confirmed' and player['id'] in listed}
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

    def _get(self, path, params, deadline=None):
        if path not in ('games/allscores/', 'game/stats/', 'game/'):
            raise ValueError('Unsupported provider path')
        key = (path, tuple(sorted(params.items())))
        # Serialize cache misses to prevent duplicate upstream calls from threads.
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(key)
            if cached and now - cached[0] < self.TTL:
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
                if path == 'game/':
                    valid = isinstance(data.get('game'), dict)
                elif path == 'game/stats/' and 'games' not in data:
                    # Before kickoff the stats endpoint returns only its update envelope.
                    valid = all(type(data.get(key)) is int for key in ('lastUpdateId', 'requestedUpdateId', 'ttl'))
                else:
                    valid = isinstance(data.get('games'), list)
                if not valid:
                    raise SportsDataError('Le format des données 365Scores a changé.')
            except (requests.RequestException, ValueError, UnicodeError) as exc:
                self._blocked_until = time.monotonic() + 30
                raise SportsDataError('Impossible de récupérer les données 365Scores. Réessaie plus tard.', 503) from exc
            except SportsDataError:
                self._blocked_until = max(self._blocked_until, time.monotonic() + 30)
                raise
            fetched_at = datetime.now(timezone.utc).isoformat()
            self._cache[key] = (time.monotonic(), data, fetched_at)
            if len(self._cache) > 32:
                self._cache.popitem(last=False)
            return data, fetched_at, False

    def matches(self, day, query='', sport=1):
        data, fetched_at, cached = self._get('games/allscores/', {
            'sports': sport, 'startDate': day.strftime('%d/%m/%Y'), 'endDate': day.strftime('%d/%m/%Y'),
            'showOdds': 'false', 'onlyMajorGames': 'false'})
        games = []
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
            haystack = search_key(game['home']['name'] + ' ' + game['away']['name'] + ' ' + game['competition'])
            if all(word in haystack for word in words) and game['id'] not in seen:
                games.append(game)
                seen.add(game['id'])
        games.sort(key=lambda game: (datetime.fromisoformat(game['starts_at']), game['id']))
        return {'mode': 'sports_data', 'matches': games[:200], 'total': len(games),
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
                         (result['home']['id'], result['away']['id'])][:5] for side in ('home', 'away')}
        return history, fetched_at, cached

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
                history, history_fetched_at, history_cached = self._recent_results(detail['game'], game, deadline)
                if history_fetched_at:
                    fetched_at = min(fetched_at, history_fetched_at)
                cached = cached and history_cached
                history_notice = 'Jusqu’à cinq résultats récents disponibles par équipe. La couverture de la source peut être partielle.'
            except SportsDataError:
                history_notice = 'Les résultats récents sont temporairement indisponibles. Réessaie dans une minute.'
        return {'mode': 'sports_data', 'match': game, 'statistics': list(rows.values())[:40],
                'recent_results': history, 'history_notice': history_notice,
                'scorer_candidates': players,
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
                'fetched_at': fetched_at, 'cached': cached}
