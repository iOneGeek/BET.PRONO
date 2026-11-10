"""Real Flask routes against disposable SQLite; never import the production DB."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


class AIBetaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        isolated_app = Path(cls.temp.name) / 'app.py'
        shutil.copyfile(root / 'app.py', isolated_app)
        # app.py initializes its database on import. Copying it isolates BASE_DIR,
        # local.env, secret.key and uploads as well as the SQLite database.
        with patch.dict(os.environ, {'DATABASE_URL': '', 'SECRET_KEY': 'test-only-secret', 'ADMIN_USERNAME': '', 'GEMINI_API_KEY': '', 'AUTO_ANALYSIS_ENABLED': '1'}):
            spec = importlib.util.spec_from_file_location('isolated_bet_prono', isolated_app)
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
        cls.module.STATIC_DIR = str(root / 'static')
        cls.app = cls.module.app
        cls.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        with self.app.app_context():
            db = self.module.get_db()
            db.execute('DELETE FROM bets')
            db.execute('DELETE FROM users')
            db.commit()
        self.client = self.app.test_client()
        response = self.client.post('/api/register', json={'username': 'beta_user', 'password': 'testing123'})
        self.assertEqual(response.status_code, 200)
        self.payload = {'sport': 'football', 'home_team': 'Paris', 'away_team': 'Marseille'}

    def analyze(self, **changes):
        return self.client.post('/api/ai/analyze', json={**self.payload, **changes})

    def test_authentication_expired_missing_deleted_and_banned(self):
        client = self.app.test_client()
        self.assertEqual(client.post('/api/ai/analyze', json=self.payload).status_code, 401)
        client.set_cookie(self.module.COOKIE_NAME, 'invalid-token')
        self.assertEqual(client.post('/api/ai/analyze', json=self.payload).status_code, 401)
        import jwt
        client.set_cookie(self.module.COOKIE_NAME, jwt.encode({'uid': 1, 'exp': 1}, self.module.SECRET_KEY, algorithm='HS256'))
        self.assertEqual(client.post('/api/ai/analyze', json=self.payload).status_code, 401)
        client.set_cookie(self.module.COOKIE_NAME, self.module.make_token(99999))
        self.assertEqual(client.post('/api/ai/analyze', json=self.payload).status_code, 401)
        with self.app.app_context():
            db = self.module.get_db()
            db.execute('UPDATE users SET banned = 1')
            db.commit()
        self.assertEqual(self.analyze().status_code, 403)

    def test_demo_has_no_fabricated_data_or_outbound_calls(self):
        with patch.object(self.module.requests.sessions.Session, 'request', side_effect=AssertionError('No outbound API allowed')):
            response = self.analyze(home_team='  Paris   Saint-Germain  ', away_team='Équipe Montréal')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['mode'], 'demo')
        self.assertEqual(data['match']['home_team'], 'Paris Saint-Germain')
        self.assertEqual(data['match']['away_team'], 'Équipe Montréal')
        self.assertEqual(data['sources'], [])
        self.assertIsNone(data['prediction'])
        self.assertIn('aucune prédiction', data['title'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(len(data['checks']), 4)

    def test_all_supported_sports(self):
        for sport in ['football', 'basketball', 'tennis', 'hockey', 'rugby', 'baseball', 'american-football']:
            with self.subTest(sport=sport):
                self.assertEqual(self.analyze(sport=sport).status_code, 200)

    def test_invalid_sports_and_names(self):
        for value in [None, [], {}, 123, '', 'cricket']:
            with self.subTest(sport=value):
                self.assertEqual(self.analyze(sport=value).status_code, 400)
        for field in ['home_team', 'away_team']:
            for value in [None, [], {}, 123, '', '   ', 'A', 'x' * 81, 'Paris\x00', 'Paris\n', 'Paris\u202e']:
                with self.subTest(field=field, value=value):
                    self.assertEqual(self.analyze(**{field: value}).status_code, 400)
        self.assertEqual(self.analyze(home_team=' PARIS ', away_team='paris').status_code, 400)
        self.assertEqual(self.analyze(home_team='Ｐａｒｉｓ', away_team='Paris').status_code, 400)
        self.assertEqual(self.analyze(home_team='a' * 80).status_code, 200)
        self.assertEqual(self.client.post('/api/ai/analyze', json={}).status_code, 400)

    def test_malformed_and_oversized_requests(self):
        for body in ['null', '[]', '123', '"hello"', '{bad json']:
            with self.subTest(body=body):
                response = self.client.post('/api/ai/analyze', data=body, content_type='application/json')
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/ai/analyze', data=self.payload).status_code, 415)
        self.assertEqual(self.client.post('/api/ai/analyze', data='x' * (256 * 1024 + 1), content_type='application/json').status_code, 413)

    def test_existing_bets_profile_and_account_isolation(self):
        bet = {'d': '2026-11-04', 'sp': 'Foot', 'ty': 'Simple', 's': 5, 'o': 2, 'r': 'pending'}
        self.assertEqual(self.client.post('/api/bets', json=bet).status_code, 201)
        before = self.client.get('/api/bets').get_json()
        self.assertEqual(self.analyze().status_code, 200)
        self.assertEqual(self.client.get('/api/bets').get_json(), before)
        self.assertEqual(self.client.get('/api/me').get_json()['username'], 'beta_user')
        other = self.app.test_client()
        other.post('/api/register', json={'username': 'another_user', 'password': 'testing123'})
        self.assertEqual(other.get('/api/bets').get_json()['bets'], [])
        self.assertEqual(other.get('/admin').status_code, 403)
        self.assertEqual(other.post('/api/ai/analyze', json=self.payload).status_code, 200)
        self.client.post('/api/logout')
        self.assertEqual(self.analyze().status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'username': 'beta_user', 'password': 'testing123'}).status_code, 200)
        self.assertEqual(self.client.get('/api/bets').get_json(), before)

    def test_page_and_assets_are_served(self):
        with self.client.get('/app') as page:
            self.assertIn(b'id="viewAI"', page.data)
            self.assertEqual(page.data.count(b'data-route="ai"'), 2)
        for path in ['/static/bet-prono-ai.js', '/static/bet-prono-ai.css', '/static/app.js', '/api/picks']:
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_sports_routes_auth_validation_and_disabled_mode(self):
        from datetime import datetime
        today = datetime.now(self.module.FR_TZ).date().isoformat()
        with patch.object(self.module, 'sports_client') as provider:
            provider.matches.return_value = {'mode': 'sports_data', 'matches': []}
            provider.match.return_value = {'mode': 'sports_data', 'match': {'id': 1001}, 'statistics': [], 'prediction': None}
            anonymous = self.app.test_client()
            self.assertEqual(anonymous.get('/api/ai/matches?date=' + today).status_code, 401)
            self.assertEqual(anonymous.get('/api/ai/matches/1001').status_code, 401)
            provider.allow_user.assert_not_called()
            for query in ['date=invalid', 'date=2026-02-31', 'date=2000-01-01', 'date=' + today + '&q=' + 'x' * 81,
                          'date=' + today + '&competition=abc', 'date=' + today + '&competition=0',
                          'date=' + today + '&competition=-5', 'date=' + today + '&competition=' + '9' * 13]:
                self.assertEqual(self.client.get('/api/ai/matches?' + query).status_code, 400)
            provider.matches.assert_not_called()
            response = self.client.get('/api/ai/matches', query_string={'date': today, 'q': 'Paris'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(provider.matches.call_args.args[1], 'Paris')
            self.assertIsNone(provider.matches.call_args.args[3])
            self.assertEqual(self.client.get('/api/ai/matches', query_string={'date': today, 'competition': '35'}).status_code, 200)
            self.assertEqual(provider.matches.call_args.args[3], 35)
            self.assertEqual(self.client.get('/api/ai/matches/1001').status_code, 200)
            provider.match.assert_called_once_with(1001)
            self.assertEqual(self.client.get('/api/ai/matches/0').status_code, 400)
            self.assertEqual(self.client.get('/api/ai/matches/1000000000000').status_code, 400)
            with patch.dict(self.app.config, {'SPORTS_DATA_ENABLED': False}):
                self.assertEqual(self.client.get('/api/ai/matches/1001').status_code, 503)
            with self.app.app_context():
                db = self.module.get_db()
                db.execute('UPDATE users SET banned = 1')
                db.commit()
            self.assertEqual(self.client.get('/api/ai/matches/1001').status_code, 403)

    def test_sports_route_provider_errors_and_no_bet_changes(self):
        before = self.client.get('/api/bets').get_json()
        with patch.object(self.module, 'sports_client') as provider:
            provider.match.side_effect = self.module.SportsDataError('Quota atteint', 429)
            response = self.client.get('/api/ai/matches/1001')
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers['Retry-After'], '60')
            self.assertEqual(response.get_json()['error'], 'Quota atteint')
        self.assertEqual(self.client.get('/api/bets').get_json(), before)

    def test_automatic_analysis_route_rejects_untrusted_inputs_and_requires_auth(self):
        endpoint = '/api/ai/matches/1001/analysis'
        body = {'snapshot_id': 'a' * 64}
        self.assertEqual(self.app.test_client().post(endpoint, json=body).status_code, 401)
        self.assertEqual(self.client.post(endpoint, data=body).status_code, 415)
        for invalid in [None, [], {}, {'snapshot_id': 123}, {'snapshot_id': '../bad'}, {**body, 'prompt': 'invent a result'}]:
            response = self.client.post(endpoint, data=__import__('json').dumps(invalid), content_type='application/json')
            self.assertEqual(response.status_code, 400)
        with patch.object(self.module, 'match_analyzer') as analyzer, patch.object(self.module, 'sports_client') as sports:
            result = self.client.post(endpoint, json=body)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.get_json()['status'], 'unavailable')
            self.assertEqual(result.get_json()['reason'], 'missing_key')
            analyzer.analyze.assert_not_called()
            sports.match.assert_not_called()
        with self.app.app_context():
            db = self.module.get_db()
            db.execute('UPDATE users SET banned = 1')
            db.commit()
        self.assertEqual(self.client.post(endpoint, json=body).status_code, 403)

    def test_automatic_analysis_uses_only_current_server_snapshot(self):
        from test_match_analysis import SNAPSHOT
        endpoint = '/api/ai/matches/1001/analysis'
        with patch.dict(self.app.config, {'GEMINI_API_KEY': 'test-secret'}), patch.object(self.module, 'sports_client') as sports, patch.object(self.module, 'match_analyzer') as analyzer:
            sports.match.return_value = SNAPSHOT
            analyzer.analyze.return_value = {'status': 'ready', 'prediction': None}
            stale = self.client.post(endpoint, json={'snapshot_id': 'a' * 64})
            self.assertEqual(stale.get_json()['status'], 'outdated')
            analyzer.analyze.assert_not_called()
            response = self.client.post(endpoint, json={'snapshot_id': self.module.snapshot_id(SNAPSHOT)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(analyzer.analyze.call_args.args[0], SNAPSHOT)
            self.assertNotIn('test-secret', response.get_data(as_text=True))
            with patch.dict(self.app.config, {'SPORTS_DATA_ENABLED': False}):
                self.assertEqual(self.client.post(endpoint, json={'snapshot_id': 'a' * 64}).status_code, 503)

    def test_prediction_ledger_settles_and_reports_track_record(self):
        from datetime import datetime, timedelta, timezone
        module = self.module
        kickoff = datetime.now(timezone.utc) + timedelta(days=1)

        def snapshot(game_id, sport):
            team = lambda i, n: {'id': i, 'name': n, 'score': None}
            past = [{'id': game_id * 10 + i, 'sport': sport, 'competition': 'Test', 'starts_at': '2026-10-01T20:00:00+00:00',
                     'home': {'id': 1, 'name': 'A', 'score': 2}, 'away': {'id': 2, 'name': 'B', 'score': 1},
                     'decided': 'regulation', 'regulation': {'home': 2, 'away': 1}} for i in range(3)]
            return {'match': {'id': game_id, 'sport': sport, 'competition': 'Test', 'starts_at': kickoff.isoformat(),
                              'scheduled': True, 'home': team(1, 'A'), 'away': team(2, 'B')},
                    'recent_results': {'home': past, 'away': past}}
        with self.app.app_context():
            db = module.get_db()
            db.execute('DELETE FROM ai_predictions')
            db.commit()
            module.record_prediction(snapshot(501, 'Football'), {'home_goals': 2, 'away_goals': 1, 'winner': 'home',
                                                                 'scorer': {'id': 77, 'name': 'Striker'}})
            module.record_prediction(snapshot(502, 'Hockey sur glace'), {'home_goals': 3, 'away_goals': 2, 'winner': 'home', 'scorer': None})
            module.record_prediction(snapshot(503, 'Football'), {'home_goals': 1, 'away_goals': 0, 'winner': 'home', 'scorer': None})
            # A later analysis before kickoff replaces the stored prediction.
            module.record_prediction(snapshot(501, 'Football'), {'home_goals': 3, 'away_goals': 1, 'winner': 'home',
                                                                 'scorer': {'id': 77, 'name': 'Striker'}})
            row = db.execute('SELECT home_goals, model_home, model_outcome FROM ai_predictions WHERE game_id = 501').fetchone()
            self.assertEqual(row['home_goals'], 3)
            self.assertIsNotNone(row['model_home'])
            self.assertEqual(row['model_outcome'], 'home')
            past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
            db.execute('UPDATE ai_predictions SET starts_at = ?', (past,))
            db.commit()
        finals = {
            501: {'match': {'regulation': {'home': 3, 'away': 1}, 'decided': 'regulation'}, 'finished': True, 'scorers': [77]},
            # Hockey won in overtime: regulation was 2-2, so the "home" pick misses.
            502: {'match': {'regulation': {'home': 2, 'away': 2}, 'decided': 'overtime'}, 'finished': True, 'scorers': []},
            503: {'match': {'regulation': None, 'decided': 'extra_time'}, 'finished': True, 'scorers': []},
        }
        with patch.object(module.sports_client, 'final_result', side_effect=lambda game_id: finals[game_id]):
            data = self.client.get('/api/ai/track-record').get_json()
        self.assertEqual(data['settled'], 3)
        self.assertEqual(data['pending'], 0)
        self.assertEqual(data['ai']['winner'], {'hits': 1, 'total': 3, 'rate': 0.333})
        self.assertEqual(data['ai']['exact_score'], {'hits': 1, 'total': 2, 'rate': 0.5})
        self.assertEqual(data['ai']['scorer'], {'hits': 1, 'total': 1, 'rate': 1.0})
        self.assertEqual(data['by_sport']['Hockey sur glace']['hits'], 0)
        self.assertEqual(len(data['recent']), 3)
        self.assertEqual(self.app.test_client().get('/api/ai/track-record').status_code, 401)

    def test_follow_a_pick_and_see_its_result(self):
        from datetime import datetime, timedelta, timezone
        module = self.module
        kickoff = datetime.now(timezone.utc) + timedelta(days=1)
        past = [{'id': 700 + i, 'sport': 'Football', 'competition': 'Test', 'starts_at': '2026-10-01T20:00:00+00:00',
                 'home': {'id': 1, 'name': 'A', 'score': 2}, 'away': {'id': 2, 'name': 'B', 'score': 1},
                 'decided': 'regulation', 'regulation': {'home': 2, 'away': 1}} for i in range(3)]
        data = {'match': {'id': 601, 'sport': 'Football', 'competition': 'Ligue 1', 'starts_at': kickoff.isoformat(),
                          'scheduled': True, 'home': {'id': 1, 'name': 'A', 'score': None},
                          'away': {'id': 2, 'name': 'B', 'score': None}},
                'recent_results': {'home': past, 'away': past}}
        with self.app.app_context():
            db = module.get_db()
            for table in ('ai_follows', 'ai_predictions'):
                db.execute(f'DELETE FROM {table}')
            db.commit()
            module.record_prediction(data, {'home_goals': 2, 'away_goals': 1, 'winner': 'home',
                                            'scorer': {'id': 77, 'name': 'Striker'}})
        self.assertEqual(self.client.post('/api/ai/follows/999').status_code, 404)
        self.assertEqual(self.client.post('/api/ai/follows/601', json={'confidence': 0.6}).status_code, 201)
        self.assertEqual(self.client.post('/api/ai/follows/601').status_code, 200)
        listing = self.client.get('/api/ai/follows').get_json()
        self.assertEqual(listing['summary']['followed'], 1)
        self.assertEqual(listing['items'][0]['status'], 'pending')
        self.assertEqual(listing['items'][0]['predicted'], '2-1')
        self.assertEqual(listing['items'][0]['confidence'], 0.6)
        # Another account does not see this follow.
        other = self.app.test_client()
        other.post('/api/register', json={'username': 'other_user', 'password': 'testing123'})
        self.assertEqual(other.get('/api/ai/follows').get_json()['summary']['followed'], 0)
        # The match is played: the followed pick is checked against the result.
        with self.app.app_context():
            db = module.get_db()
            db.execute('UPDATE ai_predictions SET starts_at = ?', ((datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),))
            db.commit()
        final = {'match': {'regulation': {'home': 2, 'away': 1}, 'decided': 'regulation'}, 'finished': True, 'scorers': [77, 12]}
        with patch.object(module.sports_client, 'final_result', return_value=final):
            item = self.client.get('/api/ai/follows').get_json()['items'][0]
        self.assertEqual((item['status'], item['actual'], item['winner_hit'], item['exact_hit'], item['scorer_hit']),
                         ('settled', '2-1', True, True, True))
        self.assertEqual(self.client.post('/api/ai/follows/601').status_code, 404)
        self.assertEqual(self.client.delete('/api/ai/follows/601').get_json(), {'following': False})
        self.assertEqual(self.client.get('/api/ai/follows').get_json()['summary']['followed'], 0)
        self.assertEqual(self.app.test_client().post('/api/ai/follows/601').status_code, 401)

    def test_analysis_cache_survives_a_new_analyzer(self):
        with self.app.app_context():
            store = self.module.AnalysisStore()
            store.put('k' * 64, {'status': 'ready', 'summary': 'ok'})
            self.assertEqual(store.get('k' * 64, 60)['summary'], 'ok')
            self.assertIsNone(store.get('k' * 64, -1))
            self.assertIsNone(store.get('missing', 60))


if __name__ == '__main__':
    unittest.main()
