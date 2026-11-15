"""Pool de connexions PostgreSQL (simulé) et cache navigateur des fichiers statiques."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


class FakeCursor:
    def execute(self, *args):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.rolled_back = 0
        self.closed = False

    def cursor(self, row_factory=None):
        return FakeCursor()

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True


class FakePool:
    def __init__(self):
        self.out, self.back = [], []

    def getconn(self):
        conn = FakeConnection()
        self.out.append(conn)
        return conn

    def putconn(self, conn):
        self.back.append(conn)


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        shutil.copyfile(root / 'app.py', Path(cls.temp.name) / 'app.py')
        with patch.dict(os.environ, {'DATABASE_URL': '', 'SECRET_KEY': 'test-only-secret', 'AUTO_SETTLE': '0', 'GEMINI_API_KEY': ''}):
            spec = importlib.util.spec_from_file_location('isolated_perf_app', Path(cls.temp.name) / 'app.py')
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
        cls.module.STATIC_DIR = str(root / 'static')
        cls.app = cls.module.app
        cls.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_postgres_connections_are_reused_through_the_pool(self):
        pool = FakePool()
        with patch.object(self.module, 'USE_PG', True), patch.object(self.module, '_get_pg_pool', return_value=pool), \
                patch.object(self.module, 'psycopg', create=True) as fake_psycopg:
            direct = fake_psycopg.connect
            client = self.app.test_client()
            for _ in range(3):
                response = client.post('/api/widget/pair', json={'code': 'ABCDEFGHJKLMNPQR'})
                self.assertEqual(response.status_code, 401)
        direct.assert_not_called()
        self.assertEqual(len(pool.out), 3)
        self.assertEqual(pool.back, pool.out)                       # Chaque connexion est rendue au pool…
        self.assertTrue(all(conn.rolled_back and not conn.closed for conn in pool.back))  # …propre, jamais fermée.

    def test_pool_failure_falls_back_to_a_direct_connection(self):
        conn = FakeConnection()
        with patch.object(self.module, 'USE_PG', True), patch.object(self.module, '_get_pg_pool', side_effect=RuntimeError('down')), \
                patch.object(self.module, 'psycopg', create=True) as fake_psycopg:
            fake_psycopg.connect.return_value = conn
            self.app.test_client().post('/api/widget/pair', json={'code': 'ABCDEFGHJKLMNPQR'})
        self.assertTrue(conn.closed)

    def test_versioned_static_files_are_cached_for_a_year(self):
        client = self.app.test_client()
        versioned = client.get('/static/app.js?v=9.9.9')
        self.assertEqual(versioned.headers['Cache-Control'], 'public, max-age=31536000, immutable')
        self.assertIn('max-age=86400', client.get('/static/logo.png').headers['Cache-Control'])
        self.assertIn('max-age=0', client.get('/static/downloads/BET.PRONO Widget.pyw').headers['Cache-Control'])
        for response in (versioned,):
            response.close()


if __name__ == '__main__':
    unittest.main()
