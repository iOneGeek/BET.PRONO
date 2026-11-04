"""Cash balance regression, with a disposable database and no live account."""
from datetime import date, timedelta
import unittest
from unittest.mock import patch
import copy
import test_ai


def ledger():
    old = (date.today() - timedelta(days=120)).isoformat()
    today = date.today().isoformat()
    return [
        {'d': old, 'sp': 'Foot', 'ty': 'Simple', 's': 100, 'o': 4, 'r': 'won', 'b': 0},
        {'d': old, 'sp': '-', 'ty': '-', 's': 20, 'o': 0, 'r': 'wd', 'b': 0},
        {'d': old, 'sp': 'Foot', 'ty': 'Simple', 's': 10, 'o': 2, 'r': 'pending', 'b': 0},
        {'d': today, 'sp': 'Foot', 'ty': 'Simple', 's': 5, 'o': 2, 'r': 'lost', 'b': 0},
        {'d': today, 'sp': 'Foot', 'ty': 'Simple', 's': 10, 'o': 2, 'r': 'won', 'b': 1},
        {'d': today, 'sp': 'Tennis', 'ty': 'Combiné', 's': 5, 'o': 5.93, 'r': 'pending', 'b': .49},
        {'d': today, 'sp': 'Tennis', 'ty': 'Combiné', 's': 20.29, 'o': 2.03, 'r': 'pending', 'b': 0},
        {'d': today, 'sp': 'Foot', 'ty': 'Simple', 's': 8, 'o': 3, 'r': 'void', 'b': 0},
    ]


class BankrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_ai.AIBetaTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        test_ai.AIBetaTests.tearDownClass()

    def setUp(self):
        self.fixture = test_ai.AIBetaTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.rows = [self.client.post('/api/bets', json=b).get_json() for b in ledger()]
        with self.fixture.app.app_context():
            db = self.fixture.module.get_db()
            self.uid = db.execute('SELECT id FROM users').fetchone()[0]
            db.execute('UPDATE users SET is_admin = 1 WHERE id = ?', (self.uid,))
            db.commit()

    def assert_balance(self, expected):
        detail = self.client.get(f'/api/admin/user/{self.uid}').get_json()
        listing = self.client.get('/api/admin/users').get_json()['users']
        self.assertAlmostEqual(detail['bankroll'], expected, places=2)
        self.assertAlmostEqual(next(u for u in listing if u['id'] == self.uid)['bankroll'], expected, places=2)

    def test_pending_settlement_and_user_isolation(self):
        self.assert_balance(350.71)
        bet = self.rows[6]
        for result, expected in [('lost', 350.71), ('void', 371), ('won', 391.90), ('pending', 350.71)]:
            with self.subTest(result=result):
                self.assertEqual(self.client.patch(f'/api/bets/{bet["id"]}', json={'r': result}).status_code, 200)
                self.assert_balance(expected)
        other = self.fixture.app.test_client()
        other.post('/api/register', json={'username': 'other_cash_user', 'password': 'testing123'})
        other.post('/api/bets', json={**ledger()[0], 's': 999})
        self.assert_balance(350.71)
        self.assertEqual(other.get('/api/admin/users').status_code, 403)
        self.assertEqual(self.fixture.app.test_client().get('/api/admin/users').status_code, 401)
        self.client.delete(f'/api/bets/{bet["id"]}')
        self.assert_balance(371)

    def plan(self):
        return {'version': 1, 'initial_bankroll': 100, 'before': self.client.get('/api/bets').get_json()['bets'],
                'updates': [{'id': self.rows[4]['id'], 'p': 19.98}], 'additions': [ledger()[3]], 'apply': False}

    def test_actual_payout_and_status_changes(self):
        bid = self.rows[4]['id']
        result = self.client.patch(f'/api/bets/{bid}', json={'p': 19.98}).get_json()
        self.assertEqual((result['p'], result['o'], result['b']), (19.98, 2, 1))
        self.assert_balance(349.69)
        self.client.patch(f'/api/bets/{bid}', json={'d': '2026-01-01'})
        self.assert_balance(349.69)
        self.client.patch(f'/api/bets/{bid}', json={'p': 0})
        self.assert_balance(329.71)
        result = self.client.patch(f'/api/bets/{bid}', json={'r': 'pending'}).get_json()
        self.assertIsNone(result['p'])
        self.assert_balance(329.71)
        self.client.patch(f'/api/bets/{bid}', json={'r': 'won'})
        self.assert_balance(350.71)

    def test_payout_validation_and_import_roundtrip(self):
        for invalid in [-1, float('nan'), float('inf'), 'invalid']:
            self.assertEqual(self.client.patch(f'/api/bets/{self.rows[4]["id"]}', json={'p': invalid}).status_code, 400)
        for data in [{'p': 10}, {'s': float('inf')}, {'sp': []}, ['invalid']]:
            self.assertEqual(self.client.patch(f'/api/bets/{self.rows[6]["id"]}', json=data).status_code, 400)
        items = ledger()
        items[4]['p'] = 19.98
        self.assertEqual(self.client.post('/api/bets/import', json={'bets': items}).status_code, 200)
        self.assertEqual(next(b for b in self.client.get('/api/bets').get_json()['bets'] if b.get('p') is not None)['p'], 19.98)
        self.assert_balance(349.69)

    def test_reconcile_preview_apply_replay_and_isolation(self):
        plan = self.plan()
        preview = self.client.post('/api/bets/reconcile', json=plan)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual(preview.get_json()['balance_after'], 344.69)
        self.assertEqual(preview.get_json()['backup']['bets'], plan['before'])
        self.assert_balance(350.71)
        response = self.client.post('/api/bets/reconcile', json={**plan, 'apply': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        current = self.client.get('/api/bets').get_json()['bets']
        self.assertTrue({b['id'] for b in plan['before']} <= {b['id'] for b in current})
        self.assert_balance(344.69)
        self.assertEqual(self.client.post('/api/bets/reconcile', json={**plan, 'apply': True}).status_code, 409)
        other = self.fixture.app.test_client()
        other.post('/api/register', json={'username': 'other_cash_user', 'password': 'testing123'})
        self.assertEqual(other.post('/api/bets/reconcile', json=plan).status_code, 409)
        self.assertEqual(self.fixture.app.test_client().post('/api/bets/reconcile', json=plan).status_code, 401)

    def test_reconcile_stale_invalid_and_atomic_failure(self):
        plan = self.plan()
        variants = [None, [], {**plan, 'apply': 'false'}, {**plan, 'updates': plan['updates'] * 2},
                    {**plan, 'updates': [{'id': self.rows[4]['id'], 'r': 'lost'}]},
                    {**plan, 'additions': [dict(ledger()[3], p=-1)]}]
        for data in variants:
            self.assertEqual(self.client.post('/api/bets/reconcile', json=data).status_code, 400)
        self.assert_balance(350.71)
        original = self.fixture.module.Conn.execute
        def failing(conn, sql, args=()):
            if sql.startswith('INSERT INTO bets'):
                raise RuntimeError('simulated insert failure')
            return original(conn, sql, args)
        with patch.object(self.fixture.module.Conn, 'execute', failing):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/bets/reconcile', json={**plan, 'apply': True})
        self.assert_balance(350.71)
        self.client.patch(f'/api/bets/{self.rows[0]["id"]}', json={'s': 99})
        self.assertEqual(self.client.post('/api/bets/reconcile', json={**plan, 'apply': True}).status_code, 409)

    def test_reconcile_legacy_export_and_missing_rows(self):
        plan = self.plan()
        for b in plan['before']:
            b.pop('p')
        self.assertEqual(self.client.post('/api/bets/reconcile', json=plan).status_code, 200)
        changed = copy.deepcopy(plan)
        changed['before'].pop()
        self.assertEqual(self.client.post('/api/bets/reconcile', json=changed).status_code, 409)
        changed = copy.deepcopy(plan)
        changed['initial_bankroll'] = 101
        self.assertEqual(self.client.post('/api/bets/reconcile', json=changed).status_code, 409)

    def test_migration_preserves_existing_bets(self):
        with self.fixture.app.app_context():
            db = self.fixture.module.get_db()
            db.execute('ALTER TABLE bets DROP COLUMN payout')
            db.commit()
            self.fixture.module.init_db()
            self.fixture.module.init_db()
        current = self.client.get('/api/bets').get_json()['bets']
        self.assertEqual({b['id'] for b in current}, {b['id'] for b in self.rows})
        self.assertTrue(all(b['p'] is None for b in current))
        self.assert_balance(350.71)

    def test_follow_links_survive_and_settlement_clears_payout(self):
        pick = self.client.post('/api/admin/picks', json={'title': 'Test', 'sport': 'Foot', 'legs': [{'match': 'A-B', 'pick': 'A', 'odds': 2}]}).get_json()
        with self.fixture.app.app_context():
            db = self.fixture.module.get_db()
            db.execute('INSERT INTO pick_follows (pick_id, user_id, bet_id, stake, created_at) VALUES (?, ?, ?, ?, ?)', (pick['id'], self.uid, self.rows[4]['id'], 10, '2026-01-01'))
            db.commit()
        plan = self.plan()
        blocked = copy.deepcopy(plan)
        blocked['updates'][0]['s'] = 9
        self.assertEqual(self.client.post('/api/bets/reconcile', json=blocked).status_code, 400)
        self.assertEqual(self.client.post('/api/bets/reconcile', json={**plan, 'apply': True}).status_code, 200)
        with self.fixture.app.app_context():
            self.assertEqual(self.fixture.module.get_db().execute('SELECT bet_id FROM pick_follows').fetchone()[0], self.rows[4]['id'])
        for result, payout in [('won', 19.98), ('lost', None), ('pending', None)]:
            self.assertEqual(self.client.patch(f'/api/admin/picks/{pick["id"]}', json={'result': result}).status_code, 200)
            current = self.client.get('/api/bets').get_json()['bets']
            self.assertEqual(next(b['p'] for b in current if b['id'] == self.rows[4]['id']), payout)


if __name__ == '__main__':
    unittest.main()
