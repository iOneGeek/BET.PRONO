import json
import os
import re
import sqlite3
import secrets
import sys
import uuid
import base64
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
FR_TZ = ZoneInfo("Europe/Paris")
from functools import wraps

import jwt
import requests
import time
import urllib.parse
from flask import Flask, g, jsonify, request, send_from_directory, redirect, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "bankroll.db")
SECRET_PATH = os.path.join(BASE_DIR, "instance", "secret.key")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "instance", "uploads")
def _load_local_env():
    """Charge local.env (non versionné) pour les secrets en local."""
    path = os.path.join(BASE_DIR, "local.env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_local_env()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
SPORTMONKS_TOKEN = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
COOKIE_NAME = "bp_token"
TOKEN_DAYS = 30
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,24}$")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

if os.getenv("SECRET_KEY"):
    SECRET_KEY = os.getenv("SECRET_KEY").strip()
elif os.path.exists(SECRET_PATH):
    with open(SECRET_PATH, "r") as f:
        SECRET_KEY = f.read().strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    with open(SECRET_PATH, "w") as f:
        f.write(SECRET_KEY)
    print("[AVERTISSEMENT] SECRET_KEY générée aléatoirement (instance/secret.key absent). "
          "Configurer SECRET_KEY dans les variables d'environnement Render pour des sessions stables "
          "à travers les redéploiements.", flush=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024


# ---------------------------------------------------------------------------
# Couche d'accès données : SQLite (local, par défaut) OU PostgreSQL/Neon
# (dès qu'une variable d'environnement DATABASE_URL est définie).
# Aucune requête métier ne change : un petit adaptateur gère les différences
# de placeholders, d'ID auto-générés et de rows.
# ---------------------------------------------------------------------------
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
USE_PG = DATABASE_URL.startswith("postgres")

if USE_PG:
    from psycopg_pool import ConnectionPool


class SmartRow(dict):
    """Ligne de base compatible à la fois index `row['col']` et `row[0]`."""

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return list(self.values())[key]
        return dict.__getitem__(self, key)


def _make_pg_row(cur):
    """Usine de row PostgreSQL : retourne une fonction (values) -> SmartRow."""
    cols = [d.name for d in cur.description] if cur.description else []

    def make(values):
        return SmartRow(zip(cols, values))

    return make


class Conn:
    """Enveloppe une connexion sqlite3 OU psycopg avec une API unifiée
       (execute / fetchone / fetchall / lastrowid / commit / close)."""

    def __init__(self, backend, real):
        self.backend = backend  # "sqlite" ou "pg"
        self._c = real
        self._cur = None
        self._lastid = None

    def execute(self, sql, args=()):
        args = tuple(args or ())
        if self.backend == "pg":
            sql = self._translate(sql)
            cur = self._c.cursor(row_factory=_make_pg_row)
            if sql.lstrip().upper().startswith("INSERT INTO"):
                sql = sql.rstrip(";") + " RETURNING id"
                cur.execute(sql, args)
                row = cur.fetchone()
                self._lastid = row[0] if row else None
            else:
                cur.execute(sql, args)
                self._lastid = None
        else:
            cur = self._c.cursor()
            cur.execute(sql, args)
            self._lastid = cur.lastrowid if cur.lastrowid else None
        self._cur = cur
        return self

    def fetchone(self):
        if self._cur is None:
            return None
        return self._cur.fetchone()

    def fetchall(self):
        if self._cur is None:
            return []
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        return self._lastid

    def commit(self):
        self._c.commit()

    def close(self):
        self._c.close()

    @staticmethod
    def _translate(sql):
        """Convertit les placeholders `?` de SQLite en `%s` de PostgreSQL."""
        return sql.replace("?", "%s")


POOL = None
_POOL_LOCK = None
if USE_PG:
    import threading
    _POOL_LOCK = threading.Lock()
    dsn = DATABASE_URL
    if "connect_timeout=" not in dsn:
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}connect_timeout=20"
    POOL = ConnectionPool(
        dsn,
        min_size=1,
        max_size=8,
        open=False,
        timeout=25,
    )
    POOL.open()


def _ensure_pool_open():
    """Garantit que le pool est ouvert. L'auto-reconnect règle les coupures
    temporaires (maintenances Render/Neon, pause du compute) : dès que la base
    redevient joignable, le pool se rouvre tout seul, sans erreur ni blocage."""
    if not USE_PG or POOL is None:
        return True
    if not POOL.closed:
        return True
    try:
        with _POOL_LOCK:
            if POOL.closed:
                try:
                    POOL.open()
                except Exception:
                    return False
        return not POOL.closed
    except Exception:
        return False


def get_db():
    if "db" not in g:
        if USE_PG:
            real = None
            for attempt in range(4):
                if real is None:
                    try:
                        real = POOL.getconn()
                    except Exception:
                        if not _ensure_pool_open():
                            pass
                if real is not None:
                    # Le compute Neon peut redémarrer (maintenance, changement
                    # de réglages) : le pool renvoie alors des connexions mortes.
                    # On vérifie que la connexion est vivante avant de l'utiliser.
                    try:
                        cur = real.cursor()
                        cur.execute("SELECT 1")
                        cur.fetchone()
                        cur.close()
                        break
                    except Exception:
                        try:
                            POOL.putconn(real, close=True)
                        except Exception:
                            pass
                        real = None
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    try:
                        POOL.check()
                    except Exception:
                        pass
            if real is None:
                real = POOL.getconn()
            g._pg_conn = real
            g.db = Conn("pg", real)
        else:
            real = sqlite3.connect(DB_PATH)
            real.row_factory = sqlite3.Row
            real.execute("PRAGMA foreign_keys = ON")
            g.db = Conn("sqlite", real)
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        if USE_PG:
            POOL.putconn(g.pop("_pg_conn", db._c))
        else:
            db.close()


def _run_ddl(conn, ddl):
    """Exécute un script DDL (plusieurs statements) sur PostgreSQL."""
    cur = conn.cursor()
    for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
        cur.execute(stmt)
    conn.commit()


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if USE_PG:
        init_pg_db()
    else:
        init_sqlite_db()


def init_pg_db():
    conn = POOL.getconn()
    try:
        _run_ddl(conn, """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                initial_bankroll DOUBLE PRECISION NOT NULL DEFAULT 100,
                is_admin SMALLINT NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                email TEXT
            );
            CREATE TABLE IF NOT EXISTS bets (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                sport TEXT NOT NULL,
                type TEXT NOT NULL,
                stake DOUBLE PRECISION NOT NULL,
                odds DOUBLE PRECISION NOT NULL DEFAULT 0,
                result TEXT NOT NULL,
                bonus DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS picks (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                author_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                sport TEXT,
                legs TEXT NOT NULL,
                total_odds DOUBLE PRECISION NOT NULL,
                result TEXT NOT NULL DEFAULT 'pending',
                image_path TEXT,
                created_at TEXT NOT NULL,
                advice_profile TEXT DEFAULT 'prudent',
                link_url TEXT
            );
            CREATE TABLE IF NOT EXISTS pick_follows (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                pick_id BIGINT NOT NULL REFERENCES picks(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                bet_id BIGINT NOT NULL REFERENCES bets(id) ON DELETE CASCADE,
                stake DOUBLE PRECISION NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(pick_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(user_id);
            CREATE INDEX IF NOT EXISTS idx_picks_author ON picks(author_id);
            CREATE INDEX IF NOT EXISTS idx_follows_pick ON pick_follows(pick_id);
            CREATE INDEX IF NOT EXISTS idx_follows_user ON pick_follows(user_id);
        """)
        # Migrations : colonnes ajoutées sur des tables existantes
        _run_ddl(conn, "ALTER TABLE picks ADD COLUMN IF NOT EXISTS sport TEXT")
        _run_ddl(conn, "ALTER TABLE picks ADD COLUMN IF NOT EXISTS advice_profile TEXT DEFAULT 'prudent'")
        _run_ddl(conn, "UPDATE picks SET advice_profile = 'prudent' WHERE advice_profile IS NULL")
        _run_ddl(conn, "ALTER TABLE picks ADD COLUMN IF NOT EXISTS link_url TEXT")
        _run_ddl(conn, "ALTER TABLE picks ADD COLUMN IF NOT EXISTS image_data BYTEA")
        _run_ddl(conn, "ALTER TABLE picks ADD COLUMN IF NOT EXISTS image_mime TEXT")
        _run_ddl(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
    finally:
        POOL.putconn(conn)


def init_sqlite_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            initial_bankroll REAL NOT NULL DEFAULT 100,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            sport TEXT NOT NULL,
            type TEXT NOT NULL,
            stake REAL NOT NULL,
            odds REAL NOT NULL DEFAULT 0,
            result TEXT NOT NULL,
            bonus REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            sport TEXT,
            legs TEXT NOT NULL,
            total_odds REAL NOT NULL,
            result TEXT NOT NULL DEFAULT 'pending',
            image_path TEXT,
            created_at TEXT NOT NULL,
            advice_profile TEXT DEFAULT 'prudent',
            link_url TEXT
        );
        CREATE TABLE IF NOT EXISTS pick_follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pick_id INTEGER NOT NULL REFERENCES picks(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            bet_id INTEGER NOT NULL REFERENCES bets(id) ON DELETE CASCADE,
            stake REAL NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(pick_id, user_id)
        );
        """
    )
    # Migration for databases created before the is_admin column existed.
    cols = [r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()]
    if "is_admin" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    if "email" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN email TEXT")
    pick_cols = [r[1] for r in db.execute("PRAGMA table_info(picks)").fetchall()]
    if "image_path" not in pick_cols:
        db.execute("ALTER TABLE picks ADD COLUMN image_path TEXT")
    if "sport" not in pick_cols:
        db.execute("ALTER TABLE picks ADD COLUMN sport TEXT")
    if "advice_profile" not in pick_cols:
        db.execute("ALTER TABLE picks ADD COLUMN advice_profile TEXT DEFAULT 'prudent'")
        db.execute("UPDATE picks SET advice_profile = 'prudent' WHERE advice_profile IS NULL")
    if "link_url" not in pick_cols:
        db.execute("ALTER TABLE picks ADD COLUMN link_url TEXT")
    if "image_data" not in pick_cols:
        db.execute("ALTER TABLE picks ADD COLUMN image_data BLOB")
    if "image_mime" not in pick_cols:
        db.execute("ALTER TABLE picks ADD COLUMN image_mime TEXT")
    db.commit()
    db.close()


def make_token(user_id):
    payload = {
        "uid": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def set_auth_cookie(resp, user_id):
    resp.set_cookie(
        COOKIE_NAME,
        make_token(user_id),
        httponly=True,
        samesite="Lax",
        max_age=TOKEN_DAYS * 24 * 3600,
        path="/",
    )
    return resp


def current_user_id():
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("uid")
    except jwt.PyJWTError:
        return None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        uid = current_user_id()
        if uid is None:
            return jsonify({"error": "Non authentifié."}), 401
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if user is None:
            return jsonify({"error": "Non authentifié."}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not g.user["is_admin"]:
            return jsonify({"error": "Réservé à l'administrateur."}), 403
        return fn(*args, **kwargs)

    return wrapper


# ---------- Static pages (PWA shell) ----------

@app.errorhandler(500)
def _err500(e):
    import traceback
    traceback.print_exc()
    msg = getattr(e, "original_exception", e)
    return jsonify({"error": f"Erreur serveur: {msg}"}), 500


@app.get("/")
def root():
    return send_from_directory(STATIC_DIR, "login.html")


@app.get("/login")
def login_page():
    return send_from_directory(STATIC_DIR, "login.html")


@app.get("/app")
def app_page():
    return send_from_directory(STATIC_DIR, "app.html")


@app.get("/manifest.json")
def manifest():
    return send_from_directory(STATIC_DIR, "manifest.json")


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory(STATIC_DIR, "sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.get("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.get("/api/health")
def health():
    """Ping de maintenance : garde le compute Neon éveillé (scale-to-zero à 5 min)
    grâce à un ping régulier externe (cron-job.org / UptimeRobot).
    Ne renvoie aucune donnée sensible, juste un état."""
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"[health] {e!r}", file=sys.stderr)
        return jsonify({"status": "error"}), 503


@app.get("/api/auth/google/login")
def google_login():
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile"
    )
    return jsonify({"auth_url": auth_url})


def _google_exchange_code(code):
    """Échange le code d'autorisation contre un id_token Google.
    Réessaie plusieurs fois : les erreurs SSL/EOF vers Google sont souvent
    intermittentes côté Render et se corrigent à la tentative suivante.
    Retourne l'id_token, ou None si toutes les tentatives échouent."""
    url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    # Budget total volontairement court (bien en dessous du timeout worker Gunicorn,
    # voir Procfile) : un ancien réglage à 30s/tentative x3 pouvait dépasser les 30s
    # par défaut de Gunicorn et faire tuer le worker en plein échange -> 500 brut.
    last_err = None
    for attempt in range(3):
        try:
            with requests.Session() as s:
                resp = s.post(url, data=data, timeout=10)
                resp.raise_for_status()
            tokens = resp.json()
            id_token = tokens.get("id_token")
            if id_token:
                return id_token
            last_err = "Réponse Google sans id_token"
        except Exception as e:  # erreurs réseau/SSL/5xx
            last_err = str(e)
        time.sleep(0.6 * (attempt + 1))  # 0.6s, 1.2s entre tentatives
    return None


class _TimedSession(requests.Session):
    """Session requests avec timeout obligatoire : google-auth fait des appels
    HTTPS sans timeout par défaut, ce qui peut faire dépasser le budget du worker."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 10)
        return super().request(method, url, **kwargs)


@app.get("/api/auth/google/callback")
def google_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Pas de code d'autorisation."}), 400

    id_token = _google_exchange_code(code)
    if id_token is None:
        return jsonify({"error": "Échec de l'échange avec Google (erreur réseau/SSL). Réessaie dans un instant."}), 502

    try:
        user_info = verify_oauth2_token(id_token, Request(session=_TimedSession()), GOOGLE_CLIENT_ID, clock_skew_in_seconds=10)
    except Exception as e:
        print(f"[google_callback] verify_oauth2_token: {e!r}", file=sys.stderr)
        return jsonify({"error": "La vérification du jeton Google a échoué. Réessaie dans un instant."}), 502

    email = user_info.get("email")
    if not email:
        return jsonify({"error": "Email manquant."}), 400
    name = user_info.get("name") or email.split("@")[0]

    try:
        db = get_db()
        user = db.execute("SELECT id, is_admin FROM users WHERE email = ?", (email,)).fetchone()

        admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        if not user:
            # Premier passage : créer le compte. L'email admin désigné devient admin,
            # sinon le tout premier compte, sinon simple utilisateur.
            is_admin = 1 if (admin_email and email.lower() == admin_email) else 0
            if not is_admin:
                user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                is_admin = 1 if user_count == 0 else 0
            username = name.replace(" ", "_").lower()[:24]
            username_base = username
            counter = 1
            while db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
                username = f"{username_base}{counter}"
                counter += 1

            now = datetime.now(timezone.utc).isoformat()
            cur = db.execute(
                "INSERT INTO users (username, email, password_hash, is_admin, initial_bankroll, created_at) VALUES (?, ?, ?, ?, 100, ?)",
                (username, email, generate_password_hash("google_oauth"), is_admin, now),
            )
            db.commit()
            user_id = cur.lastrowid
        else:
            user_id = user["id"]
            is_admin = user["is_admin"]
            if admin_email and email.lower() == admin_email and not is_admin:
                db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
                db.commit()
                is_admin = 1
    except Exception as e:
        print(f"[google_callback] base de données: {e!r}", file=sys.stderr)
        return jsonify({"error": "Base de données momentanément indisponible (réveil de l'hébergeur). Réessaie dans un instant."}), 503

    token = jwt.encode(
        {"uid": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)},
        SECRET_KEY,
        algorithm="HS256",
    )

    response = redirect("/app")
    response.set_cookie(COOKIE_NAME, token, max_age=TOKEN_DAYS * 86400, httponly=True, samesite="Lax")
    return response


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not USERNAME_RE.match(username):
        return jsonify({"error": "Identifiant invalide (3-24 caracteres: lettres, chiffres, _ . -)"}), 400
    if len(password) < 6:
        return jsonify({"error": "Mot de passe trop court (6 caracteres minimum)."}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        return jsonify({"error": "Cet identifiant est deja utilise."}), 409

    admin_username = os.getenv("ADMIN_USERNAME", "").strip().lower()
    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if admin_username:
        # Admin designe explicitement : lui seul peut devenir admin
        is_admin = 1 if username.lower() == admin_username else 0
    else:
        is_admin = 1 if user_count == 0 else 0

    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "INSERT INTO users (username, password_hash, is_admin, initial_bankroll, created_at) VALUES (?, ?, ?, 100, ?)",
        (username, generate_password_hash(password), is_admin, now),
    )
    db.commit()
    user_id = cur.lastrowid
    resp = jsonify({"username": username, "initial_bankroll": 100.0, "is_admin": bool(is_admin)})
    return set_auth_cookie(resp, user_id)


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Identifiant ou mot de passe incorrect."}), 401

    resp = jsonify({"username": user["username"], "initial_bankroll": user["initial_bankroll"], "is_admin": bool(user["is_admin"])})
    return set_auth_cookie(resp, user["id"])


@app.post("/api/logout")
def logout():
    resp = jsonify({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
@login_required
def me():
    return jsonify({
        "username": g.user["username"],
        "email": dict(g.user).get("email"),
        "initial_bankroll": g.user["initial_bankroll"],
        "is_admin": bool(g.user["is_admin"]),
    })


@app.patch("/api/settings")
@login_required
def update_settings():
    data = request.get_json(silent=True) or {}
    if "initial_bankroll" in data:
        try:
            value = float(data["initial_bankroll"])
        except (TypeError, ValueError):
            return jsonify({"error": "Montant invalide."}), 400
        if value < 0:
            return jsonify({"error": "Montant invalide."}), 400
        db = get_db()
        db.execute("UPDATE users SET initial_bankroll = ? WHERE id = ?", (value, g.user["id"]))
        db.commit()
    return jsonify({"ok": True})


@app.patch("/api/profile")
@login_required
def update_profile():
    data = request.get_json(silent=True) or {}
    db = get_db()
    user_id = g.user["id"]
    cur_username = g.user["username"]

    new_username = (data.get("username") or "").strip()
    new_email = (data.get("email") or "").strip().lower()
    new_password = data.get("password") or ""

    if "username" in data:
        if not USERNAME_RE.match(new_username) or not new_username:
            return jsonify({"error": "Identifiant invalide (3-24 caracteres: lettres, chiffres, _ . -)."}), 400
        existing = db.execute("SELECT id FROM users WHERE username = ? AND id != ?", (new_username, user_id)).fetchone()
        if existing:
            return jsonify({"error": "Cet identifiant est deja utilise."}), 409
        db.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user_id))
        cur_username = new_username

    if "email" in data:
        if new_email == "":
            new_email = None
        elif "@" not in new_email or "." not in new_email:
            return jsonify({"error": "Adresse e-mail invalide."}), 400
        else:
            existing = db.execute("SELECT id FROM users WHERE email = ? AND id != ?", (new_email, user_id)).fetchone()
            if existing:
                return jsonify({"error": "Cet e-mail est deja utilise."}), 409
        db.execute("UPDATE users SET email = ? WHERE id = ?", (new_email, user_id))

    if "password" in data:
        if len(new_password) < 6:
            return jsonify({"error": "Mot de passe trop court (6 caracteres minimum)."}), 400
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_password), user_id))

    db.commit()
    return jsonify({"ok": True, "username": cur_username})



# ---------- Bets API ----------

RESULTS = {"won", "lost", "void", "pending", "wd"}


def serialize_bet(row):
    return {
        "id": row["id"],
        "d": row["date"],
        "sp": row["sport"],
        "ty": row["type"],
        "s": row["stake"],
        "o": row["odds"],
        "r": row["result"],
        "b": row["bonus"],
    }


@app.get("/api/bets")
@login_required
def list_bets():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM bets WHERE user_id = ? ORDER BY date ASC, id ASC", (g.user["id"],)
    ).fetchall()
    return jsonify({
        "bets": [serialize_bet(r) for r in rows],
        "initial_bankroll": g.user["initial_bankroll"],
    })


def validate_bet_payload(data):
    date = (data.get("d") or "").strip()
    sport = (data.get("sp") or "").strip()[:20]
    btype = (data.get("ty") or "").strip()[:20]
    result = data.get("r")
    try:
        stake = float(data.get("s"))
        odds = float(data.get("o") or 0)
        bonus = float(data.get("b") or 0)
    except (TypeError, ValueError):
        return None, "Valeurs numériques invalides."
    if not date or result not in RESULTS or stake <= 0 or odds < 0 or bonus < 0:
        return None, "Données de pari invalides."
    if result != "wd" and not sport:
        sport = "-"
    return {
        "date": date, "sport": sport or "-", "type": btype or "-",
        "stake": stake, "odds": odds, "result": result, "bonus": bonus,
    }, None


@app.post("/api/bets")
@login_required
def create_bet():
    data = request.get_json(silent=True) or {}
    bet, err = validate_bet_payload(data)
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "INSERT INTO bets (user_id, date, sport, type, stake, odds, result, bonus, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (g.user["id"], bet["date"], bet["sport"], bet["type"], bet["stake"], bet["odds"], bet["result"], bet["bonus"], now),
    )
    db.commit()
    row = db.execute("SELECT * FROM bets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(serialize_bet(row)), 201


@app.patch("/api/bets/<int:bet_id>")
@login_required
def update_bet(bet_id):
    data = request.get_json(silent=True) or {}
    result = data.get("r")
    if result not in RESULTS:
        return jsonify({"error": "Résultat invalide."}), 400
    db = get_db()
    row = db.execute("SELECT * FROM bets WHERE id = ? AND user_id = ?", (bet_id, g.user["id"])).fetchone()
    if not row:
        return jsonify({"error": "Pari introuvable."}), 404
    db.execute("UPDATE bets SET result = ? WHERE id = ?", (result, bet_id))
    db.commit()
    row = db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
    return jsonify(serialize_bet(row))


@app.delete("/api/bets/<int:bet_id>")
@login_required
def delete_bet(bet_id):
    db = get_db()
    row = db.execute("SELECT id FROM bets WHERE id = ? AND user_id = ?", (bet_id, g.user["id"])).fetchone()
    if not row:
        return jsonify({"error": "Pari introuvable."}), 404
    db.execute("DELETE FROM bets WHERE id = ?", (bet_id,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/bets/import")
@login_required
def import_bets():
    data = request.get_json(silent=True) or {}
    items = data.get("bets")
    if not isinstance(items, list) or len(items) > 2000:
        return jsonify({"error": "Données d'import invalides."}), 400

    parsed = []
    for item in items:
        bet, err = validate_bet_payload(item)
        if err:
            return jsonify({"error": f"Pari invalide dans l'import : {err}"}), 400
        parsed.append(bet)

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    db.execute("DELETE FROM bets WHERE user_id = ?", (g.user["id"],))
    for bet in parsed:
        db.execute(
            "INSERT INTO bets (user_id, date, sport, type, stake, odds, result, bonus, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (g.user["id"], bet["date"], bet["sport"], bet["type"], bet["stake"], bet["odds"], bet["result"], bet["bonus"], now),
        )
    db.commit()
    return jsonify({"ok": True, "count": len(parsed)})


@app.post("/api/bets/reset")
@login_required
def reset_bets():
    db = get_db()
    db.execute("DELETE FROM bets WHERE user_id = ?", (g.user["id"],))
    db.commit()
    return jsonify({"ok": True})


# ---------- Pronostics (admin) & suivi ----------

PICK_RESULTS = {"pending", "won", "lost", "void"}


# ==========================================================================
def validate_legs(legs):
    if not isinstance(legs, list) or not (1 <= len(legs) <= 6):
        return None, "Un prono doit contenir entre 1 et 6 paris."
    clean = []
    total_odds = 1.0
    for leg in legs:
        match = (leg.get("match") or "").strip()[:80]
        pick = (leg.get("pick") or "").strip()[:80]
        try:
            odds = float(str(leg.get("odds")).replace(",", "."))
        except (TypeError, ValueError):
            return None, "Cote invalide dans un des paris."
        if not match or not pick or odds <= 1:
            return None, "Chaque pari doit avoir un match, une sélection et une cote supérieure à 1."
        clean.append({"match": match, "pick": pick, "odds": odds, "score": (leg.get("score") or "").strip()[:20]})
        total_odds *= odds
    return {"legs": clean, "total_odds": round(total_odds, 4)}, None


def clean_pick_link(raw):
    """Valide le lien du pari (Winamax, Betclic...). Retourne (url|None, erreur|None)."""
    u = (raw or "").strip()
    if not u:
        return None, None
    if len(u) > 500:
        return None, "Lien trop long (500 caractères maximum)."
    if not (u.startswith("http://") or u.startswith("https://")):
        return None, "Le lien doit commencer par http:// ou https:// (ex. https://www.winamax.fr/...)."
    return u, None


def serialize_pick(row, follow=None):
    image_path = row["image_path"] if "image_path" in row.keys() else None
    image_data = row["image_data"] if ("image_data" in row.keys() and row["image_data"]) else None
    image_mime = row["image_mime"] if ("image_mime" in row.keys() and row["image_mime"]) else None
    sport = row["sport"] if ("sport" in row.keys() and row["sport"]) else "Pronostic"
    advice_profile = row["advice_profile"] if ("advice_profile" in row.keys() and row["advice_profile"]) else "prudent"
    link_url = (row["link_url"] or None) if "link_url" in row.keys() else None
    legs = row["legs"]
    try:
        legs_parsed = json.loads(legs) if legs else []
    except (TypeError, ValueError):
        legs_parsed = []
    image_url = None
    if image_data:
        b = image_data if isinstance(image_data, (bytes, bytearray)) else bytes(image_data)
        image_url = f"data:{image_mime or 'image/jpeg'};base64,{base64.b64encode(b).decode('ascii')}"
    elif image_path:
        image_url = f"/uploads/{image_path}"
    return {
        "id": row["id"],
        "title": row["title"],
        "sport": sport,
        "advice_profile": advice_profile,
        "link_url": link_url,
        "legs": legs_parsed,
        "total_odds": row["total_odds"],
        "result": row["result"],
        "created_at": row["created_at"],
        "author": row["username"],
        "followed": bool(follow),
        "follow_stake": follow["stake"] if follow else None,
        "image_url": image_url,
    }


@app.get("/api/picks")
@login_required
def list_picks():
    db = get_db()
    rows = db.execute(
        "SELECT picks.*, users.username FROM picks "
        "JOIN users ON users.id = picks.author_id "
        "ORDER BY picks.created_at DESC"
    ).fetchall()
    follows = {
        r["pick_id"]: r
        for r in db.execute(
            "SELECT * FROM pick_follows WHERE user_id = ?", (g.user["id"],)
        ).fetchall()
    }
    return jsonify({"picks": [serialize_pick(r, follows.get(r["id"])) for r in rows]})


@app.post("/api/admin/picks")
@login_required
@admin_required
def create_pick():
    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    if is_multipart:
        title = (request.form.get("title") or "").strip()[:60] or "Prono"
        sport = (request.form.get("sport") or "").strip()[:20] or "Pronostic"
        advice_profile = (request.form.get("advice_profile") or "prudent").strip().lower()
        link_raw = request.form.get("link_url")
        try:
            legs_raw = json.loads(request.form.get("legs") or "[]")
        except ValueError:
            legs_raw = []
    else:
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()[:60] or "Prono"
        sport = (data.get("sport") or "").strip()[:20] or "Pronostic"
        advice_profile = (data.get("advice_profile") or "prudent").strip().lower()
        link_raw = data.get("link_url")
        legs_raw = data.get("legs") or []

    if advice_profile not in ("fun", "prudent", "confiance", "maxi"):
        advice_profile = "prudent"

    link_url, link_err = clean_pick_link(link_raw)
    if link_err:
        return jsonify({"error": link_err}), 400

    if legs_raw:
        legs_data, err = validate_legs(legs_raw)
        if err:
            return jsonify({"error": err}), 400
    else:
        return jsonify({"error": "Ajoute au moins un pari."}), 400

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "INSERT INTO picks (author_id, title, sport, legs, total_odds, result, created_at, advice_profile, link_url) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
        (g.user["id"], title, sport, json.dumps(legs_data["legs"]), legs_data["total_odds"], now, advice_profile, link_url),
    )
    db.commit()
    row = db.execute(
        "SELECT picks.*, users.username FROM picks JOIN users ON users.id = picks.author_id WHERE picks.id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return jsonify(serialize_pick(row)), 201


@app.patch("/api/admin/picks/<int:pick_id>")
@login_required
@admin_required
def update_pick(pick_id):
    data = request.get_json(silent=True) or {}
    result = data.get("result")
    if result and result not in PICK_RESULTS:
        return jsonify({"error": "Résultat invalide."}), 400
    db = get_db()
    pick = db.execute("SELECT * FROM picks WHERE id = ? AND author_id = ?", (pick_id, g.user["id"])).fetchone()
    if not pick:
        return jsonify({"error": "Prono introuvable."}), 404
    if result:
        db.execute("UPDATE picks SET result = ? WHERE id = ?", (result, pick_id))
        if result in ("won", "lost", "void"):
            bet_ids = [r["bet_id"] for r in db.execute(
                "SELECT bet_id FROM pick_follows WHERE pick_id = ?", (pick_id,)
            ).fetchall()]
            for bet_id in bet_ids:
                db.execute("UPDATE bets SET result = ? WHERE id = ?", (result, bet_id))
    if "advice_profile" in data:
        adv = (data.get("advice_profile") or "prudent").strip().lower()
        if adv in ("fun", "prudent", "confiance", "maxi"):
            db.execute("UPDATE picks SET advice_profile = ? WHERE id = ?", (adv, pick_id))
    if "scores" in data and data.get("scores") is not None:
        scores = data.get("scores")
        if not isinstance(scores, list):
            return jsonify({"error": "Scores invalides."}), 400
        try:
            legs = json.loads(pick["legs"] or "[]")
        except ValueError:
            legs = []
        for i, sc in enumerate(scores[:len(legs)]):
            if sc is None or str(sc).strip() == "":
                legs[i].pop("score", None)
            else:
                legs[i]["score"] = str(sc).strip()[:20]
        db.execute("UPDATE picks SET legs = ? WHERE id = ?", (json.dumps(legs), pick_id))
    db.commit()
    row = db.execute(
        "SELECT picks.*, users.username FROM picks JOIN users ON users.id = picks.author_id WHERE picks.id = ?",
        (pick_id,),
    ).fetchone()
    return jsonify(serialize_pick(row))


@app.delete("/api/admin/picks/<int:pick_id>")
@login_required
@admin_required
def delete_pick(pick_id):
    db = get_db()
    row = db.execute("SELECT * FROM picks WHERE id = ? AND author_id = ?", (pick_id, g.user["id"])).fetchone()
    if not row:
        return jsonify({"error": "Prono introuvable."}), 404
    db.execute("DELETE FROM picks WHERE id = ?", (pick_id,))
    db.commit()
    if row["image_path"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["image_path"]))
        except OSError:
            pass
    return jsonify({"ok": True})


@app.post("/api/picks/<int:pick_id>/follow")
@login_required
def follow_pick(pick_id):
    data = request.get_json(silent=True) or {}
    try:
        stake = float(data.get("stake"))
    except (TypeError, ValueError):
        return jsonify({"error": "Mise invalide."}), 400
    if stake <= 0:
        return jsonify({"error": "La mise doit être supérieure à 0."}), 400
    # Sport choisi par le compte qui suit (sinon sport du prono, sinon générique)
    sport = (data.get("sport") or "").strip()[:20] or "Pronostic"
    bet_type = (data.get("type") or "").strip()[:20] or "Simple"

    db = get_db()
    pick = db.execute("SELECT * FROM picks WHERE id = ?", (pick_id,)).fetchone()
    if not pick:
        return jsonify({"error": "Prono introuvable."}), 404
    existing = db.execute(
        "SELECT id FROM pick_follows WHERE pick_id = ? AND user_id = ?", (pick_id, g.user["id"])
    ).fetchone()
    if existing:
        return jsonify({"error": "Tu suis déjà ce prono."}), 409

    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    result = pick["result"] if pick["result"] != "pending" else "pending"
    cur = db.execute(
        "INSERT INTO bets (user_id, date, sport, type, stake, odds, result, bonus, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (g.user["id"], today, sport, bet_type, stake, pick["total_odds"], result, now),
    )
    bet_id = cur.lastrowid
    db.execute(
        "INSERT INTO pick_follows (pick_id, user_id, bet_id, stake, created_at) VALUES (?, ?, ?, ?, ?)",
        (pick_id, g.user["id"], bet_id, stake, now),
    )
    db.commit()
    return jsonify({"ok": True, "bet_id": bet_id, "sport": sport}), 201


@app.delete("/api/picks/<int:pick_id>/follow")
@login_required
def unfollow_pick(pick_id):
    db = get_db()
    follow = db.execute(
        "SELECT * FROM pick_follows WHERE pick_id = ? AND user_id = ?", (pick_id, g.user["id"])
    ).fetchone()
    if not follow:
        return jsonify({"error": "Tu ne suis pas ce prono."}), 404
    db.execute("DELETE FROM pick_follows WHERE id = ?", (follow["id"],))
    db.execute("DELETE FROM bets WHERE id = ? AND user_id = ?", (follow["bet_id"], g.user["id"]))
    db.commit()
    return jsonify({"ok": True})


# ---------- SportMonks : matchs du jour (affichage limité, lecture seule) ----------
# Appel externe avec cache en mémoire (5 min), timeout court et dégradation propre :
# si l'API est lente ou inaccessible, on renvoie une liste vide sans jamais bloquer
# le worker ni lever d'erreur 500.

_FIXTURES_CACHE = {"ts": 0, "data": None}
_FIXTURES_LOCK = None
_FIXTURES_TTL = 300  # 5 minutes


def _fixtures_lock():
    global _FIXTURES_LOCK
    if _FIXTURES_LOCK is None:
        import threading
        _FIXTURES_LOCK = threading.Lock()
    return _FIXTURES_LOCK


def _sportmonks_day(day):
    """Récupère les fixtures d'une journée via SportMonks. Ne lève pas s'échoue :
    renvoie (list, error_flag)."""
    if not SPORTMONKS_TOKEN:
        return [], True
    qs = urllib.parse.urlencode({
        "api_token": SPORTMONKS_TOKEN,
        "include": "sport;league;participants;state;scores;league.country;round",
        "locale": "fr",
    })
    url = f"https://api.sportmonks.com/v3/football/fixtures/date/{day}?{qs}"
    try:
        with requests.get(url, timeout=6, headers={"Accept": "application/json"}) as r:
            if r.status_code != 200:
                return [], False
            payload = r.json()
    except Exception:
        return [], True
    out = []
    for m in payload.get("data") or []:
        parts = (m.get("participants") or []) if isinstance(m.get("participants"), list) else []
        names = [p.get("name", "?") for p in parts]
        st = m.get("state") or {}
        state = st.get("name") if isinstance(st, dict) else "?"
        lg = m.get("league") or {}
        league = lg.get("name") if isinstance(lg, dict) else "?"
        # Pays de la ligue (via include league.country)
        _country = (lg.get("country") or {}) if isinstance(lg, dict) else {}
        country = _country.get("name") if isinstance(_country, dict) else ""
        # Tour / journée (via include round)
        _round = m.get("round") or {}
        round_no = _round.get("name") if isinstance(_round, dict) else (str(_round) if _round else "")
        # Heure de coup d'envoi : on préfère l'horodatage (-> heure locale),
        # sinon on retombe sur la chaîne fournie.
        start = m.get("starting_at") or ""
        ts = m.get("starting_at_timestamp")
        dt = None
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts), timezone.utc).astimezone(FR_TZ)
            except Exception:
                dt = None
        if dt is None and start:
            try:
                dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S").astimezone(FR_TZ)
            except Exception:
                dt = None
        kickoff = dt.strftime("%d/%m à %H:%M") if dt else ""
        # Le champ scores est une liste ; certains plans renvoient le score sous
        # une structure légèrement différente. On se limite à l'état et au nom.
        out.append({
            "id": m.get("id"),
            "match": m.get("name") or (" vs ".join(names) if names else "?"),
            "state": state,
            "kickoff": kickoff,
            "league": league or "?",
            "country": country,
            "round": round_no,
            "teams": [{"name": p.get("name", "?"), "logo": p.get("image_path") or ""} for p in parts],
        })
    return out, False


@app.get("/api/fixtures")
@login_required
def fixtures():
    day = (request.args.get("date") or "").strip()
    if not day:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = time.time()
    if _FIXTURES_CACHE["data"] is not None and (now - _FIXTURES_CACHE["ts"]) < _FIXTURES_TTL:
        return jsonify({"matches": _FIXTURES_CACHE["data"], "cached": True})
    with _fixtures_lock():
        # Re-vérification sous verrou (une seule requête réseau max toutes les 5 min)
        if _FIXTURES_CACHE["data"] is not None and (time.time() - _FIXTURES_CACHE["ts"]) < _FIXTURES_TTL:
            return jsonify({"matches": _FIXTURES_CACHE["data"], "cached": True})
        data, err = _sportmonks_day(day)
        # On ne met en cache que si l'appel a réussi (évite de servir du vide périmé)
        if not err:
            _FIXTURES_CACHE["ts"] = time.time()
            _FIXTURES_CACHE["data"] = data
        else:
            # Si pas encore de cache sain, on renvoie vide avec un indicateur
            return jsonify({"matches": [], "error": True, "cached": False})
    return jsonify({"matches": data, "cached": False, "error": err})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    init_db()
