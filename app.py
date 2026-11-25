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
if SUR_RENDER and GOOGLE_REDIRECT_URI.startswith("http://"):   # 25/11 : l'adresse de retour Google doit être en https
    print("ATTENTION : GOOGLE_REDIRECT_URI commence par http:// ; mets https:// dans les variables de Render", flush=True)
AUTORISES = {e.strip().lower() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()}
DEV_LOGIN = os.getenv("DEV_LOGIN") == "1" and not SUR_RENDER
SOURCES = {"apex", "principal", "allstar", "manuel"}
TAILLE_MAX = 512 * 1024

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(SECRET_KEY=SECRET_KEY, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=SUR_RENDER, PERMANENT_SESSION_LIFETIME=30 * 86400, MAX_CONTENT_LENGTH=TAILLE_MAX)
db.init()
notif.init()


# 25/11 : HTTPS partout. Render coupe le HTTPS devant l'application et lui transmet le protocole d'origine dans
# X-Forwarded-Proto. Render redirige déjà http -> https ; ceci est une sécurité de plus si ce réglage changeait.
@app.before_request
def _https_obligatoire():
    if not SUR_RENDER:
        return None   # en local (essais) : pas de HTTPS
    proto = request.headers.get("X-Forwarded-Proto", "https").split(",")[0].strip().lower()
    if proto == "http":
        url = "https://" + request.host + request.full_path.rstrip("?")
        # 301 pour une simple lecture ; 308 pour un envoi (POST…), qui garde la méthode et le contenu
        return redirect(url, code=301 if request.method in ("GET", "HEAD") else 308)
    return None


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


@app.get("/confidentialite")
def page_confidentialite():   # publique : lisible sans être connecté (lien en pied de page)
    return send_from_directory(ICI / "static", "confidentialite.html")


@app.get("/conditions")
def page_conditions():   # publique : conditions générales d'utilisation (lien en pied de page)
    return send_from_directory(ICI / "static", "conditions.html")


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


@app.get("/robots.txt")
def robots():   # 25/11 : consignes aux moteurs de recherche (doit être à la racine du site)
    return send_from_directory(ICI / "static", "robots.txt", mimetype="text/plain", max_age=86400)


@app.get("/sitemap.xml")
def plan_du_site():   # 25/11 : liste des pages publiques, annoncée dans robots.txt
    return send_from_directory(ICI / "static", "sitemap.xml", mimetype="application/xml", max_age=86400)


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
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erreur": type(e).__name__}), 503


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
    try:
        notif.verifier_risque(k["compte_id"], etats={s_: d_ for s_, d_ in (corps.get("sources") or {}).items() if isinstance(d_, dict)})
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"ok": True, "sources": n})


@app.post("/api/connecteur/trades")
def recevoir_trades():
    """22/11 : trades fermés lus dans MT5 par le connecteur (par lots), gardés pour l'historique et le bilan du soir."""
    entete = request.headers.get("Authorization", "")
    k = db.run("SELECT id, compte_id FROM oeil_cles WHERE empreinte = %s AND revoquee = 0",
               (empreinte(entete[7:].strip()),), one=True) if entete.startswith("Bearer oeil_") else None
    if not k:
        return jsonify({"erreur": "clé inconnue"}), 401
    L = []
    for t in (request.get_json(silent=True) or {}).get("trades") or []:
        if t.get("source") not in SOURCES or not isinstance(t.get("ticket"), int):
            continue
        L.append({"compte_id": k["compte_id"], "source": t["source"], "ticket": t["ticket"], "compte_mt5": t.get("compte"),
                  "symbole": str(t.get("symbole") or "")[:20], "sens": str(t.get("sens") or "")[:4], "volume": t.get("volume"),
                  "ouverture_t": t.get("ouverture_t"), "fermeture_t": t.get("fermeture_t"), "prix_ouv": t.get("prix_ouv"),
                  "prix_ferm": t.get("prix_ferm"), "net": t.get("net"), "devise": str(t.get("devise") or "")[:4],
                  "commentaire": str(t.get("commentaire") or "")[:40],
                  "brut": t.get("brut"), "commission": t.get("commission"), "swap": t.get("swap")})
    for i in range(0, len(L), 400):
        db.upsert_many("oeil_trades", ("compte_id", "source", "ticket"), L[i:i + 400])
    M = [{"compte_id": k["compte_id"], "compte_mt5": m["compte"], "ticket": m["ticket"], "t": m.get("t"), "montant": m.get("montant")}
         for m in (request.get_json(silent=True) or {}).get("mouvements") or []
         if isinstance(m.get("compte"), int) and isinstance(m.get("ticket"), int)]
    for i in range(0, len(M), 400):
        db.upsert_many("oeil_mouvements", ("compte_id", "compte_mt5", "ticket"), M[i:i + 400])
    try:
        notif.verifier_risque(k["compte_id"], sources_trades={t["source"] for t in L})
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"ok": True, "trades": len(L)})


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


def debut_jour_paris(t=None) -> float:
    from zoneinfo import ZoneInfo
    d = datetime.fromtimestamp(t or time.time(), ZoneInfo("Europe/Paris"))
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


@app.get("/api/trades")
@connecte
def liste_trades():
    """Trades fermés (exacts, lus dans MT5) : totaux par bot (aujourd'hui, 7 j, 30 j, tout) + liste filtrée."""
    cid = compte_courant()["id"]
    source = request.args.get("source", "")
    jours = min(max(float(request.args.get("jours", 7) or 7), 1), 3650)
    j0 = debut_jour_paris()
    stats = {}
    for nom, t in (("jour", j0), ("semaine", j0 - 6 * 86400), ("mois", j0 - 29 * 86400), ("tout", 0)):
        for r in db.run("SELECT source, COUNT(*) AS n, SUM(net) AS net, SUM(CASE WHEN net > 0 THEN 1 ELSE 0 END) AS g, MAX(devise) AS devise "
                        "FROM oeil_trades WHERE compte_id = %s AND fermeture_t >= %s GROUP BY source", (cid, t), all=True) or []:
            stats.setdefault(r["source"], {})[nom] = {"n": int(r["n"]), "net": round(float(r["net"] or 0), 2), "gagnants": int(r["g"] or 0),
                                                      "devise": r["devise"]}
    rows = _trades_filtre(cid, source, jours, request.args.get("symbole", "").strip(), request.args.get("res", ""))[::-1][:500]
    return jsonify({"stats": stats, "trades": [{k2: r[k2] for k2 in ("source", "ticket", "symbole", "sens", "volume", "ouverture_t", "fermeture_t",
                                                                     "prix_ouv", "prix_ferm", "net", "devise", "brut", "commission", "swap")} for r in rows]})


@app.get("/api/alertes")
@connecte
def alertes_lire():
    return jsonify(notif.reglages_alertes(compte_courant()["id"]))


@app.post("/api/alertes")
@connecte
def alertes_ecrire():
    anti_csrf()
    return jsonify(notif.enregistrer_alertes(compte_courant()["id"], request.get_json(silent=True) or {}))


def _trades_filtre(cid, source, jours, symbole="", res=""):
    sql, par = "SELECT * FROM oeil_trades WHERE compte_id = %s AND fermeture_t >= %s", [cid, time.time() - jours * 86400]
    if source in SOURCES:
        sql += " AND source = %s"; par.append(source)
    if symbole:
        sql += " AND UPPER(symbole) LIKE %s"; par.append("%" + symbole.upper()[:20] + "%")
    if res == "g":
        sql += " AND net > 0"
    elif res == "p":
        sql += " AND net < 0"
    return db.run(sql + " ORDER BY fermeture_t", tuple(par), all=True) or []


@app.get("/api/stats")
@connecte
def statistiques():
    """23/11 : statistiques d'un bot (ou de tous) sur la période : profit factor, creux, séries, marchés, heures, calendrier."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Paris")
    source = request.args.get("source", "")
    jours = min(max(float(request.args.get("jours", 30) or 30), 1), 3650)
    T = _trades_filtre(compte_courant()["id"], source, jours)
    nets = [float(t["net"] or 0) for t in T]
    gains, pertes = [x for x in nets if x > 0], [x for x in nets if x < 0]
    cum = sommet = creux = 0.0
    serie = pire_serie = 0
    for x in nets:
        cum += x; sommet = max(sommet, cum); creux = max(creux, sommet - cum)
        serie = serie + 1 if x < 0 else 0; pire_serie = max(pire_serie, serie)
    marches, heures, jours_net = {}, {h: [0, 0.0] for h in range(24)}, {}
    for t in T:
        m = marches.setdefault(t["symbole"], [0, 0.0, 0]); m[0] += 1; m[1] += float(t["net"] or 0); m[2] += (t["net"] or 0) > 0
        d = datetime.fromtimestamp(t["ouverture_t"] or t["fermeture_t"], tz)
        heures[d.hour][0] += 1; heures[d.hour][1] += float(t["net"] or 0)
        j = datetime.fromtimestamp(t["fermeture_t"], tz).strftime("%Y-%m-%d")
        jn = jours_net.setdefault(j, [0, 0.0]); jn[0] += 1; jn[1] += float(t["net"] or 0)
    r2 = lambda v: round(v, 2)   # noqa: E731
    brut = sum(float(t["brut"]) for t in T if t.get("brut") is not None)
    frais = sum(float(t["commission"] or 0) + float(t["swap"] or 0) for t in T if t.get("brut") is not None)
    detail = sum(1 for t in T if t.get("brut") is not None)
    return jsonify({
        "n": len(T), "net": r2(sum(nets)), "gagnants": len(gains), "taux": round(len(gains) / len(T) * 100, 1) if T else 0,
        "profit_factor": round(sum(gains) / -sum(pertes), 2) if pertes else None, "gain_moyen": r2(sum(gains) / len(gains)) if gains else 0,
        "perte_moyenne": r2(sum(pertes) / len(pertes)) if pertes else 0, "esperance": r2(sum(nets) / len(nets)) if nets else 0,
        "brut": r2(brut) if detail else None, "frais": r2(frais) if detail else None, "detail_frais": detail,
        "perdants": len(pertes),
        "meilleur": r2(max(nets)) if nets else 0, "pire": r2(min(nets)) if nets else 0, "creux": r2(creux), "pire_serie": pire_serie,
        "marches": sorted(({"symbole": k2, "n": v[0], "net": r2(v[1]), "taux": round(v[2] / v[0] * 100)} for k2, v in marches.items()), key=lambda x: -x["net"]),
        "heures": [{"h": h, "n": v[0], "net": r2(v[1])} for h, v in heures.items()],
        "jours": {k2: {"n": v[0], "net": r2(v[1])} for k2, v in jours_net.items()}})


@app.get("/api/agenda")
@connecte
def agenda():
    """23/11 : Agenda des gains. vue=annee : une case par mois ; vue=mois (mois=AAAA-MM) : une case par jour.
    Profit = somme des résultats nets ; % = profit / solde du compte au début de la case (un seul bot choisi : solde reconstitué
    à partir du solde actuel, des trades et des dépôts/retraits) ; R:R = gain moyen / perte moyenne de la case."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Paris")
    cid, source, vue = compte_courant()["id"], request.args.get("source", ""), request.args.get("vue", "annee")
    mois = request.args.get("mois", "")
    T = _trades_filtre(cid, source, 3650)
    fmt = "%Y-%m" if vue == "annee" else "%Y-%m-%d"
    cases = {}
    for t in T:
        k = datetime.fromtimestamp(t["fermeture_t"], tz).strftime(fmt)
        if vue != "annee" and not k.startswith(mois):
            continue
        c = cases.setdefault(k, {"net": 0.0, "n": 0, "g": [], "p": [], "t0": t["fermeture_t"]})
        c["t0"] = min(c["t0"], t["fermeture_t"])
        net = float(t["net"] or 0)
        c["net"] += net; c["n"] += 1
        (c["g"] if net > 0 else c["p"]).append(net)
    solde_a = None
    if source in SOURCES and T:
        comptes = {t["compte_mt5"] for t in T if t["compte_mt5"]}
        etat = db.run("SELECT donnees FROM oeil_etats WHERE compte_id = %s AND source = %s", (cid, source), one=True)
        solde_now = json.loads(etat["donnees"]).get("solde") if etat else None
        if len(comptes) == 1 and isinstance(solde_now, (int, float)):
            cpt = comptes.pop()
            tous = db.run("SELECT fermeture_t AS t, net AS v FROM oeil_trades WHERE compte_id = %s AND compte_mt5 = %s", (cid, cpt), all=True) or []
            mv = db.run("SELECT t, montant AS v FROM oeil_mouvements WHERE compte_id = %s AND compte_mt5 = %s", (cid, cpt), all=True) or []
            evts = [(float(r["t"]), float(r["v"] or 0)) for r in tous + mv if r["t"]]

            def solde_a(ts):   # solde juste avant ts = solde actuel - tout ce qui est arrivé depuis
                return solde_now - sum(v for t_, v in evts if t_ >= ts)
    out = {}
    for k, c in cases.items():
        gm = sum(c["g"]) / len(c["g"]) if c["g"] else 0.0
        pm = -sum(c["p"]) / len(c["p"]) if c["p"] else 0.0
        s0 = None
        if solde_a:
            debut = datetime.strptime(k + ("-01" if vue == "annee" else ""), "%Y-%m-%d").replace(tzinfo=tz).timestamp()
            s0 = solde_a(debut)
            if not s0 or s0 <= 0:   # compte approvisionné en cours de période : solde juste avant le 1er trade de la case
                s0 = solde_a(c["t0"])
        out[k] = {"net": round(c["net"], 2), "n": c["n"], "gagnants": len(c["g"]), "rr": round(gm / pm, 2) if pm else None,
                  "pct": round(c["net"] / s0 * 100, 2) if s0 and s0 > 0 else None}
    return jsonify({"vue": vue, "cases": out, "pct_dispo": solde_a is not None})


@app.get("/api/trades.csv")
@connecte
def export_csv():
    """23/11 : tous les trades fermés de la période en CSV (séparateur ; pour Excel en français)."""
    import csv
    import io
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Paris")
    source = request.args.get("source", "")
    T = _trades_filtre(compte_courant()["id"], source, min(max(float(request.args.get("jours", 3650) or 3650), 1), 3650),
                       request.args.get("symbole", "").strip(), request.args.get("res", ""))
    f = io.StringIO()
    w = csv.writer(f, delimiter=";")
    w.writerow(["bot", "ticket", "compte", "marche", "sens", "lot", "ouverture", "fermeture", "prix_entree", "prix_sortie",
                "brut", "commission", "swap", "resultat_net", "devise"])
    nom = {"apex": "APEX", "allstar": "ALL STAR", "principal": "Sonic", "manuel": "Bot manuel"}
    for t in T:
        w.writerow([nom.get(t["source"], t["source"]), t["ticket"], t["compte_mt5"], t["symbole"], t["sens"], str(t["volume"]).replace(".", ","),
                    datetime.fromtimestamp(t["ouverture_t"], tz).strftime("%d/%m/%Y %H:%M:%S") if t["ouverture_t"] else "",
                    datetime.fromtimestamp(t["fermeture_t"], tz).strftime("%d/%m/%Y %H:%M:%S"),
                    str(t["prix_ouv"]).replace(".", ","), str(t["prix_ferm"]).replace(".", ","),
                    *[("" if t.get(c) is None else str(t[c]).replace(".", ",")) for c in ("brut", "commission", "swap")],
                    str(t["net"]).replace(".", ","), t["devise"]])
    from flask import Response
    return Response("﻿" + f.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=oeil-du-trader-trades{'-' + source if source else ''}.csv"})


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


@app.errorhandler(404)
def introuvable(_e):
    """26/11 : adresse inconnue -> page 404 du site (code 404 conservé) ; pour l'API, une réponse JSON."""
    if request.path.startswith("/api/"):
        return jsonify({"erreur": "adresse inconnue"}), 404
    resp = send_from_directory(ICI / "static", "404.html")
    resp.status_code = 404
    return resp


@app.after_request
def entetes(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if SUR_RENDER:   # 25/11 : HSTS : le navigateur n'essaie plus jamais ce site en http pendant 1 an
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8810")), debug=False)
