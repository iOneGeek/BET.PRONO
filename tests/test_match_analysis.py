"""Synthetic model responses only: these tests never spend API credits."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import requests
from match_analysis import MatchAnalysis, InvalidAnalysis, snapshot_id
from sports_data import normalize_game
from test_sports_data import GAME, FakeResponse


SNAPSHOT = {'match': normalize_game(GAME), 'statistics': [{'label': 'Shots', 'home': '0', 'away': '8'}]}
ANSWER = {'summary': 'Les tirs observés sont déséquilibrés.', 'observations': [
    {'text': 'Test Lyon compte 8 tirs, contre 0 pour Test Paris.', 'fact_ids': ['stat_0']}]}


def response(answer=ANSWER, finish='STOP'):
    return FakeResponse({'candidates': [{'finishReason': finish, 'content': {'parts': [{'text': json.dumps(answer)}]}}]})


class MatchAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = MatchAnalysis()

    def analyze(self, data=None, user=1, key='test-key'):
        return self.analyzer.analyze(data or SNAPSHOT, user, key, 'gemini-3.8-flash')

    def test_missing_key_disabled_and_insufficient_data_make_no_call(self):
        with patch('match_analysis.requests.post') as post:
            self.assertEqual(self.analyze(key='')['reason'], 'missing_key')
            self.assertEqual(self.analyzer.analyze(SNAPSHOT, 1, 'key', 'gemini-3.8-flash', enabled=False)['status'], 'unavailable')
            self.assertEqual(self.analyzer.analyze(SNAPSHOT, 1, 'key', '../evil')['status'], 'unavailable')
            self.assertEqual(self.analyze({**SNAPSHOT, 'statistics': []})['status'], 'insufficient_data')
            post.assert_not_called()

    def test_generation_contract_and_cache_are_bound_to_snapshot(self):
        with patch('match_analysis.requests.post', return_value=response()) as post:
            first = self.analyze()
            second = self.analyze(user=2)
        self.assertEqual(first['status'], 'ready')
        self.assertEqual(first['snapshot_id'], snapshot_id(SNAPSHOT))
        self.assertIsNone(first['prediction'])
        self.assertIn('Test Lyon : 8', first['observations'][0]['evidence'][0])
        self.assertTrue(second['cached'])
        self.assertEqual(first['generated_at'], second['generated_at'])
        post.assert_called_once()
        url = post.call_args.args[0]
        options = post.call_args.kwargs
        self.assertNotIn('test-key', url)
        self.assertEqual(options['headers']['x-goog-api-key'], 'test-key')
        self.assertNotIn('test-key', json.dumps(options['json']))
        self.assertNotIn('test-key', json.dumps(first))
        self.assertFalse(options['allow_redirects'])
        self.assertEqual(options['json']['generationConfig']['maxOutputTokens'], 2048)
        self.assertNotIn('tools', options['json'])
        changed = deepcopy(SNAPSHOT)
        changed['match']['status'] = '2nd Half'
        with patch('match_analysis.requests.post', return_value=response()) as post:
            self.assertFalse(self.analyze(changed)['cached'])
            post.assert_called_once()

    def test_unknown_evidence_invented_numbers_and_forecasts_rejected(self):
        bad = [None, {}, {**ANSWER, 'prediction': 'home'},
               {**ANSWER, 'summary': 'Victoire à 80%'},
               {**ANSWER, 'observations': []},
               {**ANSWER, 'observations': [{'text': 'Texte', 'fact_ids': ['unknown']}]},
               {**ANSWER, 'observations': [{'text': '99 tirs', 'fact_ids': ['stat_0']}]},
               {**ANSWER, 'observations': [{'text': 'Lyon gagnera.', 'fact_ids': ['stat_0']}]},
               {**ANSWER, 'observations': [{'text': '<script>alert(1)</script>', 'fact_ids': ['stat_0']}]},
               {**ANSWER, 'observations': [{'text': 'x' * 501, 'fact_ids': ['stat_0']}]},
               {**ANSWER, 'observations': [{'text': 'texte', 'fact_ids': [None]}]}]
        facts = self.analyzer.facts(SNAPSHOT)
        for answer in bad:
            with self.subTest(answer=answer), self.assertRaises(InvalidAnalysis):
                self.analyzer.validate(answer, facts)

    def test_failures_preserve_safe_reason_and_circuit_breaker_prevents_retries(self):
        cases = [FakeResponse(status=401), FakeResponse(status=429), FakeResponse(status=302),
                 FakeResponse(content_type='text/html'), FakeResponse(raw=b'not json'),
                 FakeResponse(raw=b'x' * (128 * 1024 + 1)), FakeResponse({'candidates': []}),
                 response(finish='MAX_TOKENS'), response(finish='SAFETY'), response({'summary': 'bad'})]
        for sample in cases:
            with self.subTest(sample=sample), patch('match_analysis.requests.post', return_value=sample) as post:
                self.analyzer = MatchAnalysis()
                self.assertEqual(self.analyze()['status'], 'unavailable')
                self.assertEqual(self.analyze()['status'], 'unavailable')
                post.assert_called_once()
        self.analyzer = MatchAnalysis()
        with patch('match_analysis.requests.post', side_effect=requests.Timeout('secret-value')):
            self.assertNotIn('secret-value', json.dumps(self.analyze()))

    def test_provider_diagnostics_do_not_expose_keys_or_error_bodies(self):
        cases = [(400, 'request_rejected'), (401, 'access_denied'), (403, 'access_denied'),
                 (404, 'model_unavailable'), (429, 'quota_exceeded'), (503, 'provider_unavailable')]
        for status, reason in cases:
            sample = FakeResponse(status=status, raw=b'private-body-and-test-key')
            with self.subTest(status=status), patch('match_analysis.requests.post', return_value=sample) as post:
                self.analyzer = MatchAnalysis()
                with self.assertLogs('match_analysis', level='WARNING') as logs:
                    result = self.analyze()
                self.assertEqual(result['reason'], reason)
                self.assertEqual(self.analyze(user=2)['reason'], reason)
                post.assert_called_once()
                self.assertEqual(logs.output, [f'WARNING:match_analysis:Automatic match analysis failed: {reason}'])
                self.assertNotIn('private-body', json.dumps(result))
                self.assertNotIn('test-key', json.dumps(result))

    def test_timeout_and_incomplete_response_have_distinct_diagnostics(self):
        for sample, reason in [(response(finish='MAX_TOKENS'), 'response_truncated'),
                               (response(finish='SAFETY'), 'response_refused'),
                               (response({'summary': 'bad'}), 'invalid_response')]:
            with patch('match_analysis.requests.post', return_value=sample):
                self.analyzer = MatchAnalysis()
                self.assertEqual(self.analyze()['reason'], reason)
        for error, reason in [(requests.Timeout('private-value'), 'timeout'),
                              (requests.ConnectionError('private-value'), 'network_error')]:
            with patch('match_analysis.requests.post', side_effect=error):
                self.analyzer = MatchAnalysis()
                result = self.analyze()
                self.assertEqual(result['reason'], reason)
                self.assertNotIn('private-value', json.dumps(result))

    def test_generation_limits_and_concurrency(self):
        with patch.object(self.analyzer, '_generate', return_value=ANSWER) as generate:
            for index in range(6):
                data = deepcopy(SNAPSHOT)
                data['match']['id'] = index + 1
                self.assertEqual(self.analyze(data)['status'], 'ready')
            self.assertEqual(self.analyze()['status'], 'unavailable')
            self.assertEqual(generate.call_count, 6)
            # Different accounts share the process budget, while same-data hits are free.
            for index in range(24):
                data = deepcopy(SNAPSHOT)
                data['match']['id'] = index + 100
                self.assertEqual(self.analyze(data, user=index + 2)['status'], 'ready')
            self.assertEqual(self.analyze(user=99)['status'], 'unavailable')
            self.assertEqual(generate.call_count, 30)
        self.analyzer._lock.acquire()
        try:
            self.assertEqual(self.analyze()['status'], 'unavailable')
        finally:
            self.analyzer._lock.release()

    def test_snapshot_ignores_fetch_time_and_model_thoughts(self):
        self.assertEqual(snapshot_id(SNAPSHOT), snapshot_id({**SNAPSHOT, 'fetched_at': 'different'}))
        payload = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
            {'thought': True, 'text': 'internal reasoning must not be exposed'}, {'text': json.dumps(ANSWER)}]}}]}
        with patch('match_analysis.requests.post', return_value=FakeResponse(payload)):
            result = self.analyze()
        self.assertEqual(result['status'], 'ready')
        self.assertNotIn('internal reasoning', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
