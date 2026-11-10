"""Deterministic model and pick: synthetic results only, no network."""
from datetime import datetime, timedelta, timezone
import unittest

from match_model import enrich, poisson_model, predict, scorer_probabilities, team_form


def result(index, home_goals, away_goals, home_id=1, away_id=2, sport='Football', decided='regulation', regulation=None):
    return {'id': 1000 + index, 'sport': sport, 'competition': 'Test',
            'starts_at': (datetime(2026, 10, 30, tzinfo=timezone.utc) - timedelta(days=7 * index)).isoformat(),
            'home': {'id': home_id, 'name': 'H', 'score': home_goals}, 'away': {'id': away_id, 'name': 'A', 'score': away_goals},
            'decided': decided, 'regulation': regulation if regulation is not None else {'home': home_goals, 'away': away_goals}}


def snapshot(home_results, away_results, sport='Football', candidates=()):
    return {'match': {'id': 1, 'sport': sport, 'scheduled': True,
                      'starts_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                      'home': {'id': 1, 'name': 'Home FC', 'score': None}, 'away': {'id': 2, 'name': 'Away FC', 'score': None}},
            'recent_results': {'home': home_results, 'away': away_results}, 'scorer_candidates': list(candidates)}


STRONG = [result(i, 3, 0, home_id=1, away_id=50 + i) for i in range(10)]
WEAK = [result(i, 2, 0, home_id=60 + i, away_id=2) for i in range(10)]


class MatchModelTests(unittest.TestCase):
    def test_recent_results_weigh_more(self):
        old_good = [result(0, 0, 1, home_id=1, away_id=9)] + [result(i, 3, 0, home_id=1, away_id=9) for i in range(1, 5)]
        recent_good = [result(0, 3, 0, home_id=1, away_id=9)] + [result(i, 0, 1, home_id=1, away_id=9) for i in range(1, 5)]
        old, recent = team_form(old_good, 1, 'Football'), team_form(recent_good, 1, 'Football')
        self.assertGreater(old['scored_avg'], recent['scored_avg'])
        self.assertGreater(recent['scored_weighted'] / recent['scored_avg'], old['scored_weighted'] / old['scored_avg'])

    def test_model_requires_three_results_and_probabilities_sum_to_one(self):
        self.assertIsNone(poisson_model(snapshot(STRONG[:2], WEAK)))
        model = poisson_model(snapshot(STRONG, WEAK))
        self.assertAlmostEqual(sum(model['probabilities'].values()), 1, places=2)
        self.assertEqual(model['likely_outcome'], 'home')
        self.assertEqual(model['method'], 'Poisson + Dixon-Coles')
        self.assertEqual(model['sample'], {'home': 10, 'away': 10})
        self.assertAlmostEqual(model['double_chance']['home_or_draw'],
                               model['probabilities']['home'] + model['probabilities']['draw'], places=2)

    def test_dixon_coles_raises_low_score_draws_in_football_only(self):
        even = [result(i, 1, 1, home_id=1, away_id=2) for i in range(6)]
        football = poisson_model(snapshot(even, even))
        hockey = poisson_model(snapshot(even, even, sport='Hockey sur glace'))
        self.assertEqual(hockey['method'], 'Poisson')
        self.assertGreater(football['_grid'][0, 0] * football['_grid'][1, 1], 0)
        plain = poisson_model.__globals__['_poisson']
        lam_h, lam_a = football['expected_goals']['home'], football['expected_goals']['away']
        self.assertGreater(football['_grid'][1, 1], plain(1, lam_h) * plain(1, lam_a) * 0.99)

    def test_pick_score_matches_the_most_likely_outcome(self):
        for home, away in ((STRONG, WEAK), (WEAK[:5], STRONG[:5])):
            data = snapshot([result(i, *r) for i, r in enumerate([(3, 0)] * 5)] if home is STRONG else
                            [result(i, 0, 3, home_id=1, away_id=70 + i) for i in range(5)],
                            [result(i, 0, 2, home_id=80 + i, away_id=2) for i in range(5)] if home is STRONG else
                            [result(i, 3, 0, home_id=2, away_id=90 + i) for i in range(5)])
            pick = predict(data)
            outcome = 'home' if pick['home_goals'] > pick['away_goals'] else 'away' if pick['home_goals'] < pick['away_goals'] else 'draw'
            self.assertEqual(outcome, pick['winner'])
            self.assertEqual(pick['confidence'], poisson_model(data)['probabilities'][pick['winner']])
        live = snapshot(STRONG, WEAK)
        live['match']['scheduled'] = False
        self.assertIsNone(predict(live))

    def test_scorer_probability_uses_rate_matchup_and_availability(self):
        striker = {'id': 7, 'name': 'Striker', 'side': 'home', 'team_name': 'Home FC', 'goals': 9, 'appearances': 10, 'lineup': 'unknown'}
        sure = {**striker, 'id': 8, 'lineup': 'confirmed'}
        rare = {**striker, 'id': 9, 'goals': 1, 'appearances': 10}
        no_apps = {**striker, 'id': 10, 'appearances': None}
        away = {**striker, 'id': 11, 'side': 'away', 'team_name': 'Away FC'}
        data = snapshot(STRONG, WEAK, candidates=[striker, sure, rare, no_apps, away])
        form = {side: team_form(data['recent_results'][side], data['match'][side]['id'], 'Football') for side in ('home', 'away')}
        options = {p['id']: p['probability'] for p in scorer_probabilities(data, poisson_model(data), form)}
        self.assertNotIn(10, options)
        self.assertGreater(options[8], options[7])
        self.assertGreater(options[7], options[9])
        self.assertTrue(all(0 < p < 1 for p in options.values()))
        pick = predict(data)
        self.assertEqual(pick['scorer']['id'], 8)
        self.assertEqual(len(pick['scorer_options']), 4)
        # No scorer from a team that does not score in the picked score, and none below the threshold.
        self.assertTrue(pick['home_goals'] > 0)
        only_away = predict(snapshot(STRONG, WEAK, candidates=[away]))
        if only_away['away_goals'] == 0:
            self.assertIsNone(only_away['scorer'])

    def test_hockey_uses_regulation_scores(self):
        overtime = [result(i, 4, 3, home_id=1, away_id=40 + i, sport='Hockey sur glace', decided='overtime',
                           regulation={'home': 3, 'away': 3}) for i in range(4)]
        form = team_form(overtime, 1, 'Hockey sur glace')
        self.assertEqual((form['wins'], form['draws']), (0, 4))
        self.assertEqual(form['scored_avg'], 3)

    def test_enrich_hides_internal_grid_and_handles_partial_data(self):
        out = enrich(snapshot(STRONG, WEAK))
        self.assertNotIn('_grid', out['model'])
        self.assertIsNotNone(out['prediction'])
        self.assertEqual(enrich({'match': {'id': 1}})['prediction'], None)


if __name__ == '__main__':
    unittest.main()
