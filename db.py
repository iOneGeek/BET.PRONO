"""Œil du Trader en ligne — base de données.

PostgreSQL (Neon) si DATABASE_URL commence par postgres, sinon SQLite local (instance/oeil.db) pour les essais.
Toutes les tables commencent par « oeil_ » : elles ne touchent pas aux anciennes tables de BET.PRONO.
Les requêtes s'écrivent avec %s ; ce module les adapte à SQLite.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
USE_PG = DATABASE_URL.startswith("postgres")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS oeil_comptes (
        id {pk}, email TEXT UNIQUE NOT NULL, nom TEXT, cree DOUBLE PRECISION, vu DOUBLE PRECISION)""",
    """CREATE TABLE IF NOT EXISTS oeil_cles (
        id {pk}, compte_id INTEGER NOT NULL, nom TEXT, prefixe TEXT, empreinte TEXT UNIQUE NOT NULL,
        cree DOUBLE PRECISION, vu DOUBLE PRECISION, revoquee INTEGER DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS oeil_etats (
        compte_id INTEGER NOT NULL, source TEXT NOT NULL, donnees TEXT NOT NULL, maj DOUBLE PRECISION,
        PRIMARY KEY (compte_id, source))""",
    """CREATE TABLE IF NOT EXISTS oeil_bilans (
        compte_id INTEGER NOT NULL, source TEXT NOT NULL, jour TEXT NOT NULL, donnees TEXT NOT NULL, maj DOUBLE PRECISION,
        PRIMARY KEY (compte_id, source, jour))""",
]

_local = threading.local()
_pool = None
_lock = threading.Lock()


def _sqlite():
    c = getattr(_local, "c", None)
    if c is None:
        p = Path(__file__).with_name("instance"); p.mkdir(exist_ok=True)
        c = sqlite3.connect(p / "oeil.db", timeout=10, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.c = c
    return c


def _pg_pool():
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool
                from psycopg.rows import dict_row
                _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=8, kwargs={"row_factory": dict_row, "autocommit": True},
                                       open=True, timeout=15)
    return _pool


def run(sql: str, params: tuple = (), one=False, all=False):
    """Exécute une requête ; renvoie une ligne (dict), toutes les lignes, ou rien."""
    if USE_PG:
        with _pg_pool().connection() as c:
            cur = c.execute(sql, params)
            if one:
                return cur.fetchone()
            if all:
                return cur.fetchall()
            return None
    c = _sqlite()
    cur = c.execute(sql.replace("%s", "?"), params)
    c.commit()
    if one:
        r = cur.fetchone()
        return dict(r) if r else None
    if all:
        return [dict(r) for r in cur.fetchall()]
    return None


def init():
    pk = "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    for s in SCHEMA:
        run(s.format(pk=pk))


def upsert(table: str, cles: tuple, valeurs: dict):
    """Insère ou met à jour une ligne (clé primaire = cles)."""
    cols = list(valeurs)
    maj = [c for c in cols if c not in cles]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT ({', '.join(cles)}) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in maj))
    run(sql, tuple(valeurs[c] for c in cols))
