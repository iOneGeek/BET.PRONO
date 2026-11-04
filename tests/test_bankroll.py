"""Cash balance regression, with a disposable database and no live account."""
from datetime import date, timedelta
import unittest
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


if __name__ == '__main__':
    unittest.main()
