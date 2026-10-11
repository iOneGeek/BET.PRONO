import json
import os
import re
import sqlite3
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import requests
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
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
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
COOKIE_NAME = "bp_token"
TOKEN_DAYS = 30
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,24}$")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

if os.path.exists(SECRET_PATH):
    with open(SECRET_PATH, "r") as f:
        SECRET_KEY = f.read().strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    with open(SECRET_PATH, "w") as f:
        f.write(SECRET_KEY)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
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
            legs TEXT NOT NULL,
            total_odds REAL NOT NULL,
            result TEXT NOT NULL DEFAULT 'pending',
            image_path TEXT,
            created_at TEXT NOT NULL
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
    db.commit()
    db.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)


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


@app.get("/api/auth/google/callback")
def google_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Pas de code d'autorisation."}), 400
    
    try:
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        tokens = token_response.json()
        id_token = tokens.get("id_token")
        
        if not id_token:
            return jsonify({"error": "Pas de token ID."}), 400
        
        user_info = verify_oauth2_token(id_token, Request(), GOOGLE_CLIENT_ID, clock_skew_in_seconds=10)
        email = user_info.get("email")
        name = user_info.get("name", email.split("@")[0])
        
        if not email:
            return jsonify({"error": "Email manquant."}), 400
        
        db = get_db()
        user = db.execute("SELECT id, is_admin FROM users WHERE email = ?", (email,)).fetchone()

        admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        admin_username = os.getenv("ADMIN_USERNAME", "").strip().lower()
        if not user and admin_email and email.lower() == admin_email:
            is_admin = 1
        elif not user:
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
            is_admin = is_admin
        else:
            user_id = user["id"]
            is_admin = user["is_admin"]
            # Promotion admin si l'email correspond à ADMIN_EMAIL
            if admin_email and email.lower() == admin_email and not is_admin:
                db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
                db.commit()
                is_admin = 1
        
        token = jwt.encode(
            {"uid": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)},
            SECRET_KEY,
            algorithm="HS256",
        )
        
        response = redirect("/app")
        response.set_cookie(COOKIE_NAME, token, max_age=TOKEN_DAYS * 86400, httponly=True, samesite="Lax")
        return response
    
    except Exception as e:
        return jsonify({"error": f"Erreur OAuth: {str(e)}"}), 400


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
    is_admin = 1 if (user_count == 0 or (admin_username and username.lower() == admin_username)) else 0

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
        clean.append({"match": match, "pick": pick, "odds": odds})
        total_odds *= odds
    return {"legs": clean, "total_odds": round(total_odds, 4)}, None


def serialize_pick(row, follow=None):
    image_path = row["image_path"] if "image_path" in row.keys() else None
    return {
        "id": row["id"],
        "title": row["title"],
        "legs": json.loads(row["legs"]),
        "total_odds": row["total_odds"],
        "result": row["result"],
        "created_at": row["created_at"],
        "author": row["username"],
        "followed": bool(follow),
        "follow_stake": follow["stake"] if follow else None,
        "image_url": f"/uploads/{image_path}" if image_path else None,
    }


def save_pick_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_IMAGE_EXT:
        return None, "Format d'image invalide (png, jpg, jpeg, webp, gif)."
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_IMAGE_BYTES:
        return None, "Image trop lourde (5 Mo maximum)."
    filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_storage.save(os.path.join(UPLOAD_DIR, filename))
    return filename, None


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
        try:
            legs_raw = json.loads(request.form.get("legs") or "[]")
        except ValueError:
            legs_raw = []
        image_file = request.files.get("image")
    else:
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()[:60] or "Prono"
        legs_raw = data.get("legs") or []
        image_file = None

    if legs_raw:
        legs_data, err = validate_legs(legs_raw)
        if err:
            return jsonify({"error": err}), 400
    elif is_multipart and image_file and image_file.filename:
        legs_data = {"legs": [], "total_odds": 1.0}
    else:
        return jsonify({"error": "Ajoute au moins un pari ou une image."}), 400

    image_path, img_err = save_pick_image(image_file) if is_multipart else (None, None)
    if img_err:
        return jsonify({"error": img_err}), 400

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "INSERT INTO picks (author_id, title, legs, total_odds, result, image_path, created_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
        (g.user["id"], title, json.dumps(legs_data["legs"]), legs_data["total_odds"], image_path, now),
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
    if result not in PICK_RESULTS:
        return jsonify({"error": "Résultat invalide."}), 400
    db = get_db()
    pick = db.execute("SELECT * FROM picks WHERE id = ? AND author_id = ?", (pick_id, g.user["id"])).fetchone()
    if not pick:
        return jsonify({"error": "Prono introuvable."}), 404
    db.execute("UPDATE picks SET result = ? WHERE id = ?", (result, pick_id))
    if result in ("won", "lost", "void"):
        bet_ids = [r["bet_id"] for r in db.execute(
            "SELECT bet_id FROM pick_follows WHERE pick_id = ?", (pick_id,)
        ).fetchall()]
        for bet_id in bet_ids:
            db.execute("UPDATE bets SET result = ? WHERE id = ?", (result, bet_id))
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
    cur = db.execute(
        "INSERT INTO bets (user_id, date, sport, type, stake, odds, result, bonus, created_at) "
        "VALUES (?, ?, 'Pronostic', ?, ?, ?, ?, 0, ?)",
        (g.user["id"], today, pick["title"][:20], stake, pick["total_odds"], pick["result"], now),
    )
    bet_id = cur.lastrowid
    db.execute(
        "INSERT INTO pick_follows (pick_id, user_id, bet_id, stake, created_at) VALUES (?, ?, ?, ?, ?)",
        (pick_id, g.user["id"], bet_id, stake, now),
    )
    db.commit()
    return jsonify({"ok": True, "bet_id": bet_id}), 201


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


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    init_db()
