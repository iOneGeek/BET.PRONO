"""V2.5.0: standings, odds, absences, markets, pick explanation and percentage quality. No network."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from match_analysis import InvalidAnalysis, MatchAnalysis
from match_model import poisson_model, predict
from sports_data import Scores365Client, absences
from test_match_model import STRONG, WEAK, snapshot
from test_sports_data import FakeResponse

GAME = {'id': 5, 'sport': 'Football', 'home': {'id': 1, 'name': 'Home FC'}, 'away': {'id': 2, 'name': 'Away FC'}}


class ProviderTests(unittest.TestCase):
    def test_standings_need_both_teams_and_give_league_average(self):
        rows = [{'competitor': {'id': i}, 'gamePlayed': 10, 'for': 10 + i, 'against': 12, 'position': i} for i in range(1, 7)]
        with patch('sports_data.requests.get', return_value=FakeResponse({'standings': [{'rows': rows}]})):
            table = Scores365Client()._standings(GAME, 35, None)
        self.assertEqual(table['home'], {'played': 10, 'scored': 11, 'conceded': 12, 'position': 1, 'points': None})
        self.assertAlmostEqual(table['league_goals_per_team'], sum(10 + i for i in range(1, 7)) / 60, places=3)
        cup = deepcopy(GAME)
        cup['away']['id'] = 99
        with patch('sports_data.requests.get', return_value=FakeResponse({'standings': [{'rows': rows}]})):
            self.assertIsNone(Scores365Client()._standings(cup, 35, None))

    def test_odds_remove_the_bookmaker_margin(self):
        def line(kind, options, value=None):
            return {'gameId': 5, 'lineTypeId': kind, 'lineType': {'id': kind}, 'internalOptionValue': value,
                    'options': [{'name': n, 'rate': {'decimal': r}} for n, r in options]}
        payload = {'lastUpdateId': 1, 'requestedUpdateId': -1, 'ttl': 30, 'lines': [
            line(1, [('1', 1.5), ('X', 4.0), ('2', 6.0)]), line(3, [('Under', 1.9), ('Over', 1.9)], '3.5'),
            line(3, [('Under', 2.2), ('Over', 1.65)], '2.5'), line(12, [('Yes', 1.8), ('No', 1.95)]),
            line(1, [('1', 9.9), ('X', 9.9), ('2', 9.9)])]}
        with patch('sports_data.requests.get', return_value=FakeResponse(payload)) as get:
            odds = Scores365Client()._odds(GAME, None)
        self.assertEqual(get.call_args.kwargs['params']['userCountryId'], 1)
        self.assertAlmostEqual(sum(odds['result'].values()), 1, places=2)
        self.assertGreater(odds['result']['home'], 0.6)
        self.assertEqual(odds['over']['line'], 2.5)
        self.assertAlmostEqual(odds['over']['probability'], (1 / 1.65) / (1 / 1.65 + 1 / 2.2), places=3)
        self.assertAlmostEqual(odds['both_score'], (1 / 1.8) / (1 / 1.8 + 1 / 1.95), places=3)

    def test_optional_data_failures_do_not_pause_the_main_access(self):
        client = Scores365Client()
        with patch('sports_data.requests.get', return_value=FakeResponse(status=503)):
            with self.assertRaises(Exception):
                client._odds(GAME, None)
        self.assertEqual(client._blocked_until, 0)

    def test_absences_list_missing_and_doubtful_players_with_goals(self):
        raw = {'members': [{'id': 7, 'name': 'Injured Striker'}],
               'topPerformers': {'categories': [{'awayPlayer': {'id': 7, 'stats': [{'type': 1, 'name': 'Goals', 'value': '6'}]}}]},
               'homeCompetitor': {'lineups': {'members': [{'id': 3, 'status': 1}, {'id': 4, 'status': 1, 'isDoubtful': True}]}},
               'awayCompetitor': {'lineups': {'members': [{'id': 7, 'status': 3, 'position': {'name': 'Forward'}}]}}}
        out = absences(raw, GAME)
        self.assertEqual(out['away'], [{'id': 7, 'name': 'Injured Striker', 'status': 'missing', 'position': 'Forward', 'goals': 6}])
        self.assertEqual([p['status'] for p in out['home']], ['doubtful'])


class ModelTests(unittest.TestCase):
    def test_season_strength_and_league_average_move_the_estimate(self):
        data = snapshot(STRONG, WEAK)
        plain = poisson_model(data)
        data['standings'] = {'home': {'played': 10, 'scored': 8, 'conceded': 15}, 'away': {'played': 10, 'scored': 25, 'conceded': 6},
                             'league_goals_per_team': 1.4}
        seasoned = poisson_model(data)
        self.assertTrue(seasoned['inputs']['season_strength'])
        self.assertEqual(seasoned['inputs']['league_average'], 1.4)
        self.assertLess(seasoned['probabilities']['home'], plain['probabilities']['home'])

    def test_missing_scorer_reduces_his_team_attack(self):
        data = snapshot(STRONG, WEAK)
        data['standings'] = {'home': {'played': 10, 'scored': 20, 'conceded': 8}, 'away': {'played': 10, 'scored': 10, 'conceded': 15},
                             'league_goals_per_team': 1.4}
        before = poisson_model(data)['expected_goals']['home']
        data['absences'] = {'home': [{'name': 'Star', 'status': 'missing', 'goals': 10}], 'away': []}
        after = poisson_model(data)
        self.assertLess(after['expected_goals']['home'], before * 0.8)
        self.assertGreaterEqual(after['expected_goals']['home'], before * 0.74)
        self.assertIn('Absence de Star (10 buts)', after['inputs']['absences'][0])

    def test_markets_compare_with_bookmakers_and_close_games_are_flagged(self):
        data = snapshot(STRONG, WEAK)
        data['odds'] = {'result': {'home': 0.7, 'draw': 0.2, 'away': 0.1}, 'over': {'line': 2.5, 'probability': 0.6}, 'both_score': 0.45}
        pick = predict(data)
        self.assertFalse(pick['tight'])
        self.assertEqual(pick['market'], data['odds']['result'])
        keys = {m['key']: m for m in pick['markets']}
        self.assertAlmostEqual(keys['home_or_draw']['market'], 0.9, places=3)
        self.assertEqual(sorted(m['probability'] for m in pick['markets'])[::-1], [m['probability'] for m in pick['markets']])
        def draws(rows):
            return [{**r, 'home': {**r['home'], 'score': 1}, 'away': {**r['away'], 'score': 1}, 'regulation': {'home': 1, 'away': 1}} for r in rows]
        self.assertTrue(predict(snapshot(draws(STRONG), draws(WEAK)))['tight'])


class ExplanationTests(unittest.TestCase):
    def setUp(self):
        self.data = snapshot(STRONG, WEAK)
        self.data['statistics'] = []
        self.data['pick'] = predict(self.data)
        self.facts = MatchAnalysis.facts(self.data)

    def answer(self, text, refs=('pick_model', 'form_home')):
        return {'summary': 'Les résultats récents donnent un contexte.', 'observations': [
            {'text': 'Home FC a gagné ses derniers matchs.', 'fact_ids': ['home_recent_0']}],
            'pick_explanation': {'text': text, 'fact_ids': list(refs)}}

    def test_pick_fact_and_valid_explanation(self):
        self.assertIn('Pronostic du modèle — victoire de Home FC', self.facts['pick_model'])
        pct = round(self.data['pick']['confidence'] * 100)
        result = MatchAnalysis.validate(self.answer(f'Le modèle voit Home FC devant ({pct} %), porté par une attaque efficace récemment.'), self.facts)
        self.assertTrue(result['pick_explanation']['text'].startswith('Le modèle voit Home FC'))
        self.assertEqual(len(result['pick_explanation']['evidence']), 2)

    def test_explanation_rejects_advice_certainty_invented_numbers_and_missing_pick(self):
        for text in ('Misez sur Home FC, victoire très probable selon le modèle.', 'Victoire garantie pour Home FC selon le modèle.',
                     'Le modèle voit Home FC gagner à 99 % sur ce match, sans hésiter.'):
            with self.subTest(text=text), self.assertRaises(InvalidAnalysis):
                MatchAnalysis.validate(self.answer(text), self.facts)
        with self.assertRaises(InvalidAnalysis):
            MatchAnalysis.validate(self.answer('Le modèle voit Home FC devant, porté par sa forme.', refs=('form_home', 'form_away')), self.facts)
        missing = self.answer('x' * 30)
        del missing['pick_explanation']
        with self.assertRaises(InvalidAnalysis):
            MatchAnalysis.validate(missing, self.facts)

    def test_schema_asks_for_the_explanation_only_with_a_pick(self):
        self.assertIn('pick_explanation', MatchAnalysis()._schema(self.facts)['required'])
        del self.data['pick']
        self.assertNotIn('pick_explanation', MatchAnalysis()._schema(MatchAnalysis.facts(self.data))['required'])


if __name__ == '__main__':
    unittest.main()
