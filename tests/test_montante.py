"""Montante par paliers : calcul exact au centime et API (admin / membres)."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from montante import build_steps, compute

MOCKUP = {1: 1.45, 2: 1.45, 3: 1.52, 4: 1.48}
WITHDRAWALS = {5: 10, 10: 150, 15: 500}


def table(results=()):
    steps = build_steps(20, 1.5, MOCKUP, WITHDRAWALS)
    for step, result in zip(steps, results):
        step['result'] = result
    return compute({'start_stake': 10, 'default_odds': 1.5, 'status': 'active'}, steps)


class CalculationTests(unittest.TestCase):
    def test_stakes_returns_and_withdrawals_to_the_cent(self):
        view = table(('won', 'won', 'won'))
        rows = {row['step_no']: row for row in view['steps']}
        self.assertEqual((rows[1]['stake'], rows[1]['return']), (10.0, 14.5))
        self.assertEqual(rows[2]['return'], 21.03)            # 14,50 × 1,45 = 21,025 → arrondi commercial
        self.assertEqual(rows[5]['stake'], round(rows[4]['return'], 2))
        self.assertEqual(rows[6]['stake'], round(rows[5]['return'] - 10, 2))
        self.assertEqual(rows[11]['stake'], round(rows[10]['return'] - 150, 2))
        self.assertEqual([r['state'] for r in view['steps'][:5]], ['won', 'won', 'won', 'current', 'simulation'])
        self.assertEqual(view['current_step'], 4)
        self.assertEqual(view['withdrawals_planned'], 660.0)
        self.assertEqual(view['withdrawals_banked'], 0.0)
        self.assertEqual(view['final_return'], view['steps'][-1]['return'])

    def test_lost_step_stops_the_montante_and_void_keeps_the_stake(self):
        lost = table(('won', 'lost'))
        self.assertEqual(lost['status'], 'lost')
        self.assertEqual(lost['lost_step'], 2)
        self.assertIsNone(lost['final_return'])
        self.assertTrue(all(row['state'] == 'off' and row['stake'] is None for row in lost['steps'][2:]))
        void = table(('won', 'void'))
        self.assertEqual(void['steps'][1]['return'], void['steps'][1]['stake'])
        self.assertEqual(void['steps'][2]['stake'], void['steps'][1]['stake'])

    def test_all_won_and_banked_withdrawals(self):
        view = table(['won'] * 20)
        self.assertEqual(view['status'], 'won')
        self.assertEqual(view['withdrawals_banked'], 660.0)
        self.assertIsNone(view['current_step'])


class MontanteApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        for name in ('app.py',):
            shutil.copyfile(root / name, Path(cls.temp.name) / name)
        with patch.dict(os.environ, {'DATABASE_URL': '', 'SECRET_KEY': 'test-only-secret', 'ADMIN_USERNAME': 'boss',
                                     'GEMINI_API_KEY': '', 'AUTO_SETTLE': '0'}):
            spec = importlib.util.spec_from_file_location('isolated_montante_app', Path(cls.temp.name) / 'app.py')
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
        cls.app = cls.module.app
        cls.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        with self.app.app_context():
            db = self.module.get_db()
            for table_name in ('montante_steps', 'montantes', 'users'):
                db.execute(f'DELETE FROM {table_name}')
            db.commit()
        self.admin = self.app.test_client()
        self.member = self.app.test_client()
        with patch.dict(os.environ, {'ADMIN_USERNAME': 'boss'}):
            self.assertEqual(self.admin.post('/api/register', json={'username': 'boss', 'password': 'testing123'}).status_code, 200)
            self.assertEqual(self.member.post('/api/register', json={'username': 'fan', 'password': 'testing123'}).status_code, 200)

    def create(self, client=None, **changes):
        body = {'title': 'Les 20 paliers', 'start_stake': 10, 'steps': 20, 'default_odds': 1.5,
                'odds': {str(k): v for k, v in MOCKUP.items()}, 'withdrawals': {str(k): v for k, v in WITHDRAWALS.items()}}
        body.update(changes)
        return (client or self.admin).post('/api/montantes', json=body)

    def test_only_admin_manages_but_every_member_sees(self):
        self.assertEqual(self.create(self.member).status_code, 403)
        created = self.create()
        self.assertEqual(created.status_code, 201)
        montante_id = created.get_json()['id']
        seen = self.member.get('/api/montantes').get_json()
        self.assertFalse(seen['can_edit'])
        self.assertEqual(seen['active']['total_steps'], 20)
        self.assertEqual(seen['active']['steps'][3]['odds'], 1.48)
        self.assertTrue(self.admin.get('/api/montantes').get_json()['can_edit'])
        self.assertEqual(self.member.patch(f'/api/montantes/{montante_id}/steps/1', json={'result': 'won'}).status_code, 403)
        self.assertEqual(self.app.test_client().get('/api/montantes').status_code, 401)
        self.assertEqual(self.create().status_code, 409)

    def test_results_in_order_edits_on_future_steps_and_history(self):
        montante_id = self.create().get_json()['id']
        url = f'/api/montantes/{montante_id}/steps/'
        self.assertEqual(self.admin.patch(url + '2', json={'result': 'won'}).status_code, 400)
        view = self.admin.patch(url + '1', json={'result': 'won', 'pick': 'PSG gagne'}).get_json()
        self.assertEqual((view['current_step'], view['steps'][0]['pick']), (2, 'PSG gagne'))
        self.assertEqual(self.admin.patch(url + '1', json={'odds': 2.0}).status_code, 400)
        self.assertEqual(self.admin.patch(url + '3', json={'odds': 1.7, 'withdrawal': 5, 'game_id': 4735202}).status_code, 200)
        self.assertEqual(self.admin.patch(url + '3', json={'odds': 50}).status_code, 400)
        undone = self.admin.patch(url + '1', json={'result': 'pending'}).get_json()
        self.assertEqual(undone['current_step'], 1)
        self.admin.patch(url + '1', json={'result': 'won'})
        lost = self.admin.patch(url + '2', json={'result': 'lost'}).get_json()
        self.assertEqual(lost['status'], 'lost')
        data = self.member.get('/api/montantes').get_json()
        self.assertIsNone(data['active'])
        self.assertEqual(data['history'][0]['lost_step'], 2)
        self.assertEqual(self.create().status_code, 201)

    def test_live_score_of_the_current_step_and_stop(self):
        montante_id = self.create().get_json()['id']
        self.admin.patch(f'/api/montantes/{montante_id}/steps/1', json={'game_id': 99})
        live = {'match': {'home': {'name': 'A', 'score': 1}, 'away': {'name': 'B', 'score': 0}, 'live': True},
                'clock': "55'", 'finished': False}
        with patch.object(self.module.sports_client, 'tracker', return_value=live):
            current = self.member.get('/api/montantes').get_json()['active']['steps'][0]
        self.assertEqual((current['live']['home'], current['live']['clock']), (1, "55'"))
        self.assertEqual(self.member.post(f'/api/montantes/{montante_id}/stop').status_code, 403)
        self.assertEqual(self.admin.post(f'/api/montantes/{montante_id}/stop').get_json()['status'], 'stopped')

    def test_invalid_creation(self):
        for changes in ({'start_stake': 0}, {'steps': 2}, {'steps': 31}, {'default_odds': 1.0}, {'odds': {'4': 25}},
                        {'odds': {'99': 1.5}}, {'withdrawals': {'5': -1}}, {'steps': '20'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 400)


if __name__ == '__main__':
    unittest.main()
