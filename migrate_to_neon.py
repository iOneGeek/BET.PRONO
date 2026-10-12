"""Migration ponctuelle : transfère les données de la base SQLite locale
vers la base PostgreSQL (Neon) en préservant les identifiants, afin de ne
pas casser les relations entre tables (user_id, author_id, etc.).

Usage :
    python migrate_to_neon.py
"""
import os

import psycopg

SQLITE_PATH = "instance/bankroll.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def main():
    if not DATABASE_URL.startswith("postgres"):
        print("ERREUR : variable DATABASE_URL manquante.")
        return 1

    import sqlite3

    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row
    dst = psycopg.connect(DATABASE_URL, connect_timeout=25)

    def fetch_all(sql, *args):
        return src.execute(sql, args).fetchall()

    def wipe(conn):
        """Ne supprime JAMAIS les données cibles : la migration refuse de
        s'exécuter si la base de destination contient déjà des enregistrements
        (protège la production d'un effacement accidentel)."""
        with conn.cursor() as c:
            for table in ("users", "bets", "picks", "pick_follows"):
                c.execute(f"SELECT COUNT(*) FROM {table}")
                n = c.fetchone()[0]
                if n:
                    raise SystemExit(
                        f"[SÉCURITÉ] La table {table} de destination contient déjà "
                        f"{n} ligne(s). Migration abandonnée pour ne rien perdre."
                    )

    wipe(dst)

    # ---- users ----
    users = fetch_all(
        "SELECT id, username, password_hash, initial_bankroll, is_admin, created_at, email FROM users"
    )
    with dst.cursor() as c:
        for u in users:
            c.execute(
                """INSERT INTO users
                   (id, username, password_hash, initial_bankroll, is_admin, created_at, email)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (username) DO NOTHING""",
                (u["id"], u["username"], u["password_hash"], u["initial_bankroll"],
                 u["is_admin"], u["created_at"], u["email"]),
            )
    print(f"users : {len(users)}")

    # ---- bets ----
    bets = fetch_all(
        "SELECT id, user_id, date, sport, type, stake, odds, result, bonus, created_at FROM bets"
    )
    with dst.cursor() as c:
        for b in bets:
            c.execute(
                """INSERT INTO bets
                   (id, user_id, date, sport, type, stake, odds, result, bonus, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (b["id"], b["user_id"], b["date"], b["sport"], b["type"], b["stake"],
                 b["odds"], b["result"], b["bonus"], b["created_at"]),
            )
    print(f"bets : {len(bets)}", "| (74 attendus)")

    # ---- picks ----
    picks = fetch_all(
        "SELECT id, author_id, title, sport, legs, total_odds, result, image_path, created_at FROM picks"
    )
    with dst.cursor() as c:
        for p in picks:
            c.execute(
                """INSERT INTO picks
                   (id, author_id, title, sport, legs, total_odds, result, image_path, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (p["id"], p["author_id"], p["title"], p["sport"], p["legs"], p["total_odds"],
                 p["result"], p["image_path"], p["created_at"]),
            )
    print(f"picks : {len(picks)}")

    # ---- pick_follows ----
    follows = fetch_all(
        "SELECT id, pick_id, user_id, bet_id, stake, created_at FROM pick_follows"
    )
    with dst.cursor() as c:
        for f in follows:
            c.execute(
                """INSERT INTO pick_follows (id, pick_id, user_id, bet_id, stake, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (f["id"], f["pick_id"], f["user_id"], f["bet_id"], f["stake"], f["created_at"]),
            )
    print(f"pick_follows : {len(follows)}")

    # ---- resynchronise les séquences (IDENTITY) ----
    with dst.cursor() as c:
        for table in ("users", "bets", "picks", "pick_follows"):
            c.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id),1) FROM {table}))"
            )
    dst.commit()
    dst.close()
    print("MIGRATION TERMINÉE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
