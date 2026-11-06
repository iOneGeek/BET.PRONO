"""Synthetic contract fixtures; no real sporting claims or network requests."""
from copy import deepcopy
from datetime import date
import json
import unittest
from unittest.mock import patch

import requests
from sports_data import Scores365Client, SportsDataError, normalize_game


GAME = {'id': 1001, 'sportId': 1, 'competitionDisplayName': 'Test League',
        'startTime': '2026-11-04T20:00:00+01:00', 'statusGroup': 4, 'statusText': 'Ended',
        'homeCompetitor': {'id': 10, 'name': 'Test Paris', 'score': 0},
        'awayCompetitor': {'id': 20, 'name': 'Test Lyon', 'score': 2}}


class FakeResponse:
    def __init__(self, payload=None, status=200, content_type='application/json', raw=None):
        self.status_code = status
        self.headers = {'Content-Type': content_type}
        self.raw = raw if raw is not None else json.dumps(payload or {}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        for i in range(0, len(self.raw), size):
            yield self.raw[i:i + size]


class SportsClientTests(unittest.TestCase):
    def setUp(self):
        self.client = Scores365Client()

    def test_normalization_missing_and_scheduled_scores(self):
        self.assertEqual(normalize_game(GAME)['home']['score'], 0)
        game = deepcopy(GAME)
        game['homeCompetitor']['score'] = -1
        self.assertIsNone(normalize_game(game)['home']['score'])
        game['homeCompetitor']['score'] = float('nan')
        self.assertIsNone(normalize_game(game)['home']['score'])
        game['statusGroup'] = 2
        self.assertIsNone(normalize_game(game)['away']['score'])
        game['startTime'] = '2026-11-04T20:00:00'
        self.assertIsNone(normalize_game(game))
        for invalid in [None, {}, {**GAME, 'sportId': 2}, {**GAME, 'homeCompetitor': None}]:
            self.assertIsNone(normalize_game(invalid))

    def test_search_date_boundary_query_and_shared_cache(self):
        previous = {**GAME, 'id': 1002, 'startTime': '2026-11-03T20:00:00+01:00'}
        with patch('sports_data.requests.get', return_value=FakeResponse({'games': [GAME, GAME, previous, None]})) as get:
            first = self.client.matches(date(2026, 11, 4), 'páris')
            second = self.client.matches(date(2026, 11, 4), 'LYON')
            self.assertEqual(first['total'], 1)
            self.assertEqual(first['omitted_invalid'], 1)
            self.assertFalse(first['cached'])
            self.assertTrue(second['cached'])
            self.assertEqual(first['fetched_at'], second['fetched_at'])
            self.assertEqual(get.call_count, 1)
            args = get.call_args.kwargs
            self.assertEqual(args['params']['showOdds'], 'false')
            self.assertNotIn('q', args['params'])
            self.assertFalse(args['allow_redirects'])
            self.assertEqual(args['timeout'], (3.05, 6))
            key = next(iter(self.client._cache))
            _, data, fetched = self.client._cache[key]
            self.client._cache[key] = (-99999, data, fetched)
            self.client.matches(date(2026, 11, 4))
            self.assertEqual(get.call_count, 2)

    def test_detail_matches_statistics_to_team_ids_and_preserves_missing(self):
        stats = [
            {'id': 3, 'name': 'Shots', 'competitorId': 20, 'value': '8'},
            {'id': 3, 'name': 'Shots', 'competitorId': 10, 'value': '0'},
            {'id': 8, 'name': 'Corners', 'competitorId': 20, 'value': '2'},
            {'id': 8, 'name': 'Corners', 'competitorId': 10, 'value': '1', 'filterId': 1},
            {'id': 4, 'name': 'Other', 'competitorId': 999, 'value': '99'},
            {'id': 5, 'name': 'Other', 'competitorId': 10, 'value': None},
        ]
        with patch('sports_data.requests.get', return_value=FakeResponse({'games': [GAME], 'statistics': stats})):
            result = self.client.match(1001)
        self.assertEqual(result['statistics'], [{'label': 'Shots', 'home': '0', 'away': '8'}, {'label': 'Corners', 'home': None, 'away': '2'}])
        self.assertIsNone(result['prediction'])
        self.assertEqual(result['source']['name'], '365Scores')

    def test_no_stats_is_not_zero_and_wrong_match_is_rejected(self):
        with patch('sports_data.requests.get', return_value=FakeResponse({'games': [GAME]})):
            self.assertEqual(self.client.match(1001)['statistics'], [])
            with self.assertRaises(SportsDataError) as error:
                self.client.match(1002)
            self.assertEqual(error.exception.status, 404)

    def test_errors_fail_explicitly_and_do_not_retry(self):
        cases = [
            (FakeResponse(status=403), 503), (FakeResponse(status=302), 503),
            (FakeResponse(status=429), 429), (FakeResponse(content_type='text/html'), 502),
            (FakeResponse(raw=b'{invalid'), 503), (FakeResponse({'games': {}}), 502),
            (FakeResponse(raw=b'x' * (Scores365Client.MAX_BYTES + 1)), 502),
        ]
        for response, status in cases:
            with self.subTest(status=status), patch('sports_data.requests.get', return_value=response) as get:
                client = Scores365Client()
                with self.assertRaises(SportsDataError) as error:
                    client.matches(date(2026, 11, 4))
                self.assertEqual(error.exception.status, status)
                with self.assertRaises(SportsDataError):
                    client.matches(date(2026, 11, 4))
                self.assertEqual(get.call_count, 1)
        with patch('sports_data.requests.get', side_effect=requests.Timeout('private transport details')):
            with self.assertRaises(SportsDataError) as error:
                self.client.match(1001)
            self.assertNotIn('private', str(error.exception))

    def test_user_and_upstream_rate_limits(self):
        for _ in range(20):
            self.client.allow_user(1)
        with self.assertRaises(SportsDataError) as error:
            self.client.allow_user(1)
        self.assertEqual(error.exception.status, 429)
        self.client.allow_user(2)
        with patch('sports_data.requests.get', return_value=FakeResponse({'games': []})) as get:
            for day in range(1, 21):
                self.client.matches(date(2026, 11, day))
            with self.assertRaises(SportsDataError) as error:
                self.client.matches(date(2026, 11, 21))
            self.assertEqual(error.exception.status, 429)
            self.assertEqual(get.call_count, 20)
            self.assertTrue(self.client.matches(date(2026, 11, 1))['cached'])


if __name__ == '__main__':
    unittest.main()
