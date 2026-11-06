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


def normalize_game(raw):
    if not isinstance(raw, dict) or raw.get('sportId') != 1 or not positive_id(raw.get('id')):
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
    return {'id': raw['id'], 'sport': 'Football', 'competition': text(raw.get('competitionDisplayName')) or 'Compétition non précisée',
            'starts_at': start.isoformat(), 'status': text(raw.get('statusText')) or 'Statut non précisé',
            'home': sides[0], 'away': sides[1]}


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

    def _get(self, path, params):
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
            self._calls.append(now)
            query = {'appTypeId': 5, 'langId': 1, 'timezoneName': 'Europe/Paris', **params}
            try:
                with requests.get(self.BASE + path, params=query,
                                  headers={'User-Agent': 'BET.PRONO/0.1 (sports data)', 'Accept': 'application/json'},
                                  timeout=(3.05, 6), allow_redirects=False, stream=True) as response:
                    if response.status_code == 429:
                        self._blocked_until = time.monotonic() + 60
                        raise SportsDataError('Quota 365Scores atteint. Réessaie dans une minute.', 429)
                    if response.status_code != 200:
                        raise SportsDataError('365Scores est indisponible ou refuse cet accès.', 503)
                    if 'application/json' not in response.headers.get('Content-Type', '').lower():
                        raise SportsDataError('Réponse 365Scores non reconnue.')
                    body = bytearray()
                    for chunk in response.iter_content(16384):
                        if time.monotonic() - now > 10:
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

    def matches(self, day, query=''):
        data, fetched_at, cached = self._get('games/allscores/', {
            'sports': 1, 'startDate': day.strftime('%d/%m/%Y'), 'endDate': day.strftime('%d/%m/%Y'),
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

    def match(self, game_id):
        data, fetched_at, cached = self._get('game/stats/', {'games': game_id})
        raw_games = data.get('games', [])
        if not raw_games:
            detail, detail_fetched_at, detail_cached = self._get('game/', {'gameId': game_id})
            raw_games = [detail['game']]
            fetched_at = min(fetched_at, detail_fetched_at)
            cached = cached and detail_cached
        game = next((normalize_game(raw) for raw in raw_games
                     if isinstance(raw, dict) and raw.get('id') == game_id), None)
        if not game:
            raise SportsDataError('Cette rencontre de football est introuvable ou ses données sont incomplètes.', 404)
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
        return {'mode': 'sports_data', 'match': game, 'statistics': list(rows.values())[:40],
                'source': self.SOURCE, 'fetched_at': fetched_at, 'cached': cached,
                'cache_seconds': self.TTL, 'prediction': None,
                'notice': 'Données fournies par 365Scores, potentiellement différées. La synthèse IA est chargée séparément ; aucune prédiction n’est calculée.'}
