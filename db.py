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
    """CREATE TABLE IF NOT EXISTS oeil_equite (
        compte_id INTEGER NOT NULL, source TEXT NOT NULL, t DOUBLE PRECISION NOT NULL, equite DOUBLE PRECISION, solde DOUBLE PRECISION,
        PRIMARY KEY (compte_id, source, t))""",
    """CREATE TABLE IF NOT EXISTS oeil_trades (
        compte_id INTEGER NOT NULL, source TEXT NOT NULL, ticket BIGINT NOT NULL, compte_mt5 BIGINT, symbole TEXT, sens TEXT,
        volume DOUBLE PRECISION, ouverture_t DOUBLE PRECISION, fermeture_t DOUBLE PRECISION, prix_ouv DOUBLE PRECISION,
        prix_ferm DOUBLE PRECISION, net DOUBLE PRECISION, devise TEXT, commentaire TEXT,
        PRIMARY KEY (compte_id, source, ticket))""",
    """CREATE INDEX IF NOT EXISTS oeil_trades_t ON oeil_trades (compte_id, fermeture_t)""",
    """CREATE TABLE IF NOT EXISTS oeil_mouvements (
        compte_id INTEGER NOT NULL, compte_mt5 BIGINT NOT NULL, ticket BIGINT NOT NULL, t DOUBLE PRECISION, montant DOUBLE PRECISION,
        PRIMARY KEY (compte_id, compte_mt5, ticket))""",
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
                # 23/11 : le site s'était figé : une connexion inactive coupée en silence entre Render et Neon faisait attendre
                # une requête pour toujours. Désormais : connexion vérifiée avant usage, recyclée souvent, TCP keepalive,
                # (le pooler de Neon refuse le paramètre « options » : pas de statement_timeout ici).
                _pool = ConnectionPool(
                    DATABASE_URL, min_size=1, max_size=10, open=True, timeout=10,
                    check=ConnectionPool.check_connection, max_idle=60, max_lifetime=900,
                    kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 10,
                            "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3})
    return _pool


derniere_erreur = ""


def reset_pool():
    """Ferme le réservoir de connexions : le prochain appel en recrée un neuf."""
    global _pool
    with _lock:
        p, _pool = _pool, None
    if p is not None:
        try:
            p.close(timeout=2)
        except Exception:  # noqa: BLE001
            pass


def run(sql: str, params: tuple = (), one=False, all=False):
    """Exécute une requête ; renvoie une ligne (dict), toutes les lignes, ou rien."""
    if USE_PG:
        try:
            with _pg_pool().connection() as c:
                cur = c.execute(sql, params)
                if one:
                    return cur.fetchone()
                if all:
                    return cur.fetchall()
                return None
        except Exception as e:  # noqa: BLE001
            # 23/11 (nuit) : le site renvoyait « erreur 500 » partout alors que Neon répondait : réservoir de connexions cassé.
            # On garde la cause pour /sante et, si c'est un souci de connexion (pas une erreur SQL), on repart d'un réservoir neuf.
            global derniere_erreur
            derniere_erreur = type(e).__name__
            import psycopg
            if not isinstance(e, psycopg.errors.Error) or isinstance(e, psycopg.OperationalError):
                reset_pool()
            raise
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
    # 23/11 : détail des frais des trades (colonnes ajoutées à une table existante)
    for col in ("brut", "commission", "swap"):
        try:
            run(f"ALTER TABLE oeil_trades ADD COLUMN {'IF NOT EXISTS ' if USE_PG else ''}{col} DOUBLE PRECISION")
        except Exception:  # noqa: BLE001  (SQLite : la colonne existe déjà)
            pass


def upsert(table: str, cles: tuple, valeurs: dict):
    """Insère ou met à jour une ligne (clé primaire = cles)."""
    cols = list(valeurs)
    maj = [c for c in cols if c not in cles]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT ({', '.join(cles)}) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in maj))
    run(sql, tuple(valeurs[c] for c in cols))


def upsert_many(table: str, cles: tuple, lignes: list[dict]):
    """Insère ou met à jour plusieurs lignes en UNE requête (beaucoup plus rapide vers Neon)."""
    if not lignes:
        return
    cols = list(lignes[0])
    maj = [c for c in cols if c not in cles]
    une = "(" + ", ".join(["%s"] * len(cols)) + ")"
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES " + ", ".join([une] * len(lignes)) +
           f" ON CONFLICT ({', '.join(cles)}) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in maj))
    run(sql, tuple(l[c] for l in lignes for c in cols))
