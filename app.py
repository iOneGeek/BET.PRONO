"""Œil du Trader en ligne — site multi-comptes (lecture seule).

Chaque personne se connecte avec Google et ne voit QUE ses propres bots.
Les bots tournent sur le PC de chacun (MetaTrader 5 = Windows) ; un « connecteur » y envoie l'état toutes les quelques
secondes avec une clé personnelle créée sur ce site. Aucun ordre ne part d'ici, aucun mot de passe MT5 ni token Telegram
n'est envoyé.

Variables d'environnement (Render) :
  DATABASE_URL          base Neon (postgres://…)            — sans elle : SQLite local (essais)
  SECRET_KEY            clé des sessions (longue, aléatoire)
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI   connexion Google (…/auth/google/callback)
  ALLOWED_EMAILS        e-mails autorisés à se connecter, séparés par des virgules
  DEV_LOGIN=1           SEULEMENT en local : connexion sans Google (refusé si le site tourne sur Render)
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

import requests
from flask import Flask, abort, jsonify, redirect, request, send_from_directory, session

import db
import notif

ICI = Path(__file__).parent
SUR_RENDER = bool(os.getenv("RENDER"))
SECRET_KEY = os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    if SUR_RENDER:
        raise RuntimeError("SECRET_KEY manquante dans les variables d'environnement Render")
    f = ICI / "instance" / "secret.key"
    f.parent.mkdir(exist_ok=True)
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    SECRET_KEY = f.read_text().strip()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
AUTORISES = {e.strip().lower() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()}
DEV_LOGIN = os.getenv("DEV_LOGIN") == "1" and not SUR_RENDER
SOURCES = {"apex", "principal", "allstar", "manuel"}
TAILLE_MAX = 512 * 1024

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(SECRET_KEY=SECRET_KEY, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=SUR_RENDER, PERMANENT_SESSION_LIFETIME=30 * 86400, MAX_CONTENT_LENGTH=TAILLE_MAX)
db.init()
notif.init()


@app.before_request
def _surveillance():
    notif.lancer_surveillance()   # alerte « PC hors ligne » (une seule fois par processus)


# ------------------------------------------------------------------ comptes
def compte_courant():
    cid = session.get("compte_id")
    if not cid:
        return None
    return db.run("SELECT id, email, nom FROM oeil_comptes WHERE id = %s", (cid,), one=True)


def connecte(f):
    @wraps(f)
    def g(*a, **k):
        if not compte_courant():
            if request.path.startswith("/api/"):
                return jsonify({"erreur": "non connecté"}), 401
            return redirect("/connexion")
        return f(*a, **k)
    return g


def ouvrir_session(email: str, nom: str):
    email = email.lower()
    c = db.run("SELECT id FROM oeil_comptes WHERE email = %s", (email,), one=True)
    if not c:
        db.run("INSERT INTO oeil_comptes (email, nom, cree, vu) VALUES (%s, %s, %s, %s)", (email, nom, time.time(), time.time()))
        c = db.run("SELECT id FROM oeil_comptes WHERE email = %s", (email,), one=True)
    else:
        db.run("UPDATE oeil_comptes SET vu = %s, nom = %s WHERE id = %s", (time.time(), nom, c["id"]))
    session.clear()
    session.permanent = True
    session["compte_id"] = c["id"]


def anti_csrf():
    """Les actions du navigateur envoient du JSON avec un en-tête maison : un autre site ne peut pas les forger."""
    if request.headers.get("X-Oeil") != "1":
        abort(403)


@app.get("/connexion")
def page_connexion():
    return send_from_directory(ICI / "static", "connexion.html")


@app.get("/auth/info")
def auth_info():
    return jsonify({"google": bool(GOOGLE_CLIENT_ID), "dev": DEV_LOGIN})


@app.get("/auth/google")
def google_debut():
    if not GOOGLE_CLIENT_ID:
        return "Connexion Google non configurée.", 503
    etat = secrets.token_urlsafe(24)
    session["oauth_etat"] = etat
    q = urlencode({"client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI, "response_type": "code",
                   "scope": "openid email profile", "state": etat, "prompt": "select_account"})
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + q)


@app.get("/auth/google/callback")
@app.get("/api/auth/google/callback")   # ancienne adresse de BET.PRONO : la console Google n'a pas besoin d'être modifiée
def google_retour():
    if not request.args.get("state") or request.args.get("state") != session.pop("oauth_etat", None):
        return redirect("/connexion?erreur=etat")
    code = request.args.get("code")
    if not code:
        return redirect("/connexion?erreur=code")
    jeton = None
    for essai in range(3):
        try:
            r = requests.post("https://oauth2.googleapis.com/token", timeout=10, data={
                "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code"})
            r.raise_for_status()
            jeton = r.json().get("id_token")
            if jeton:
                break
        except requests.RequestException:
            time.sleep(0.6 * (essai + 1))
    if not jeton:
        return redirect("/connexion?erreur=google")
    from google.auth.transport.requests import Request as GReq
    from google.oauth2.id_token import verify_oauth2_token
    try:
        info = verify_oauth2_token(jeton, GReq(), GOOGLE_CLIENT_ID, clock_skew_in_seconds=10)
    except Exception:  # noqa: BLE001
        return redirect("/connexion?erreur=jeton")
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified", False):
        return redirect("/connexion?erreur=email")
    if email not in AUTORISES:
        return redirect("/connexion?erreur=refuse")
    ouvrir_session(email, info.get("name") or email.split("@")[0])
    return redirect("/")


@app.post("/auth/dev")
def connexion_dev():
    if not DEV_LOGIN:
        abort(404)
    anti_csrf()
    email = ((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    if "@" not in email:
        return jsonify({"erreur": "e-mail invalide"}), 400
    ouvrir_session(email, email.split("@")[0])
    return jsonify({"ok": True})


@app.post("/auth/sortie")
def deconnexion():
    anti_csrf()
    session.clear()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ pages
@app.get("/")
@connecte
def accueil():
    return send_from_directory(ICI / "static", "index.html")


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(ICI / "static", "favicon.ico", max_age=86400)


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
def icone_iphone():
    return send_from_directory(ICI / "static", "apple-touch-icon.png", mimetype="image/png", max_age=86400)


@app.get("/sante")
def sante():
    try:
        db.run("SELECT 1", one=True)
        return jsonify({"ok": True})
    except Exception:  # noqa: BLE001
        return jsonify({"ok": False}), 503


# ------------------------------------------------------------------ clés des connecteurs
def empreinte(cle: str) -> str:
    return hashlib.sha256(cle.encode()).hexdigest()


@app.get("/api/moi")
@connecte
def moi():
    c = compte_courant()
    cles = db.run("SELECT id, nom, prefixe, cree, vu FROM oeil_cles WHERE compte_id = %s AND revoquee = 0 ORDER BY id",
                  (c["id"],), all=True)
    return jsonify({"email": c["email"], "nom": c["nom"], "cles": cles})


@app.post("/api/cles")
@connecte
def creer_cle():
    anti_csrf()
    c = compte_courant()
    nom = ((request.get_json(silent=True) or {}).get("nom") or "Mon PC").strip()[:40]
    n = db.run("SELECT COUNT(*) AS n FROM oeil_cles WHERE compte_id = %s AND revoquee = 0", (c["id"],), one=True)["n"]
    if n >= 5:
        return jsonify({"erreur": "5 clés au maximum : supprime d'abord une ancienne clé."}), 400
    cle = "oeil_" + secrets.token_urlsafe(32)
    db.run("INSERT INTO oeil_cles (compte_id, nom, prefixe, empreinte, cree, revoquee) VALUES (%s, %s, %s, %s, %s, 0)",
           (c["id"], nom, cle[:10], empreinte(cle), time.time()))
    return jsonify({"cle": cle, "nom": nom})   # montrée UNE seule fois


@app.delete("/api/cles/<int:cid>")
@connecte
def revoquer_cle(cid):
    anti_csrf()
    db.run("UPDATE oeil_cles SET revoquee = 1 WHERE id = %s AND compte_id = %s", (cid, compte_courant()["id"]))
    return jsonify({"ok": True})


# ------------------------------------------------------------------ connecteur (PC -> site)
@app.post("/api/connecteur/etat")
def recevoir_etat():
    entete = request.headers.get("Authorization", "")
    if not entete.startswith("Bearer oeil_"):
        return jsonify({"erreur": "clé manquante"}), 401
    k = db.run("SELECT id, compte_id FROM oeil_cles WHERE empreinte = %s AND revoquee = 0",
               (empreinte(entete[7:].strip()),), one=True)
    if not k:
        return jsonify({"erreur": "clé inconnue ou supprimée"}), 401
    corps = request.get_json(silent=True) or {}
    maintenant = time.time()
    n = 0
    for source, donnees in (corps.get("sources") or {}).items():
        if source not in SOURCES or not isinstance(donnees, dict):
            continue
        ancien = db.run("SELECT donnees FROM oeil_etats WHERE compte_id = %s AND source = %s", (k["compte_id"], source), one=True)
        try:
            for titre, texte, tag in notif.evenements(source, json.loads(ancien["donnees"]) if ancien else None, donnees):
                notif.envoyer_fond(k["compte_id"], titre, texte, tag)
        except Exception:  # noqa: BLE001
            pass
        db.upsert("oeil_etats", ("compte_id", "source"),
                  {"compte_id": k["compte_id"], "source": source, "donnees": json.dumps(donnees, ensure_ascii=False), "maj": maintenant})
        # 23/11 : point de la courbe d'équité, au plus un toutes les 5 min par bot
        if isinstance(donnees.get("equite"), (int, float)):
            dern = db.run("SELECT MAX(t) AS t FROM oeil_equite WHERE compte_id = %s AND source = %s", (k["compte_id"], source), one=True)
            if not dern or not dern["t"] or maintenant - dern["t"] >= 300:
                db.run("INSERT INTO oeil_equite (compte_id, source, t, equite, solde) VALUES (%s, %s, %s, %s, %s)",
                       (k["compte_id"], source, maintenant, float(donnees["equite"]),
                        float(donnees["solde"]) if isinstance(donnees.get("solde"), (int, float)) else None))
        bilan = donnees.get("bilan_jour")
        if isinstance(bilan, dict):
            jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            db.upsert("oeil_bilans", ("compte_id", "source", "jour"),
                      {"compte_id": k["compte_id"], "source": source, "jour": jour,
                       "donnees": json.dumps(bilan, ensure_ascii=False), "maj": maintenant})
        n += 1
    db.run("UPDATE oeil_cles SET vu = %s WHERE id = %s", (maintenant, k["id"]))
    return jsonify({"ok": True, "sources": n})


# ------------------------------------------------------------------ tableau de bord
@app.get("/api/etats")
@connecte
def etats():
    c = compte_courant()
    rows = db.run("SELECT source, donnees, maj FROM oeil_etats WHERE compte_id = %s", (c["id"],), all=True)
    return jsonify({"t": time.time(), "sources": {r["source"]: {"maj": r["maj"], **json.loads(r["donnees"])} for r in rows}})


@app.get("/api/equite")
@connecte
def courbe_equite():
    """Courbe d'équité d'un bot : au plus 600 points sur la période demandée (heures)."""
    source = request.args.get("source", "")
    if source not in SOURCES:
        return jsonify({"erreur": "bot inconnu"}), 400
    heures = min(max(float(request.args.get("heures", 168) or 168), 1), 24 * 3650)
    rows = db.run("SELECT t, equite, solde FROM oeil_equite WHERE compte_id = %s AND source = %s AND t >= %s ORDER BY t",
                  (compte_courant()["id"], source, time.time() - heures * 3600), all=True) or []
    pas = max(1, len(rows) // 600)
    pts = rows[::pas]
    if rows and pts[-1] is not rows[-1]:
        pts.append(rows[-1])
    return jsonify({"source": source, "points": [[r["t"], r["equite"], r["solde"]] for r in pts]})


@app.get("/api/historique")
@connecte
def historique():
    c = compte_courant()
    rows = db.run("SELECT source, jour, donnees FROM oeil_bilans WHERE compte_id = %s ORDER BY jour DESC LIMIT 400",
                  (c["id"],), all=True)
    return jsonify([{"source": r["source"], "jour": r["jour"], **json.loads(r["donnees"])} for r in rows])


# ------------------------------------------------------------------ notifications sur le téléphone
@app.get("/sw.js")
def service_worker():
    r = send_from_directory(ICI / "static", "sw.js", mimetype="application/javascript")
    r.headers["Service-Worker-Allowed"] = "/"
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/api/notif")
@connecte
def notif_info():
    try:
        pub = notif.cles()[1]
    except Exception:  # noqa: BLE001
        pub = None
    return jsonify({"cle": pub, "appareils": notif.nb_abonnements(compte_courant()["id"])})


@app.post("/api/notif/abonner")
@connecte
def notif_abonner():
    anti_csrf()
    d = request.get_json(silent=True) or {}
    try:
        notif.abonner(compte_courant()["id"], d.get("abonnement") or {}, d.get("appareil") or "")
    except ValueError as e:
        return jsonify({"erreur": str(e)}), 400
    return jsonify({"ok": True, "appareils": notif.nb_abonnements(compte_courant()["id"])})


@app.post("/api/notif/desabonner")
@connecte
def notif_desabonner():
    anti_csrf()
    notif.desabonner(compte_courant()["id"], (request.get_json(silent=True) or {}).get("endpoint") or "")
    return jsonify({"ok": True})


@app.post("/api/notif/essai")
@connecte
def notif_essai():
    anti_csrf()
    n = notif.envoyer(compte_courant()["id"], "👁 Œil du Trader", "Les notifications marchent ! Tu seras prévenu à chaque trade et si ton PC passe hors ligne.", "essai")
    return jsonify({"ok": n > 0, "envois": n})


@app.after_request
def entetes(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8810")), debug=False)
