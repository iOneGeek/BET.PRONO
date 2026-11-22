"""Œil du Trader en ligne — notifications sur le téléphone (Web Push, l'icône du site sur l'écran d'accueil de l'iPhone).

- Les clés VAPID (qui signent les notifications) sont créées une seule fois par le serveur et gardées dans la base :
  aucun secret à recopier à la main.
- Chaque appareil qui active les notifications laisse un « abonnement » (adresse fournie par Apple / Google).
- Événements : trade ouvert, trade fermé (résultat), PC hors ligne depuis 2 min, PC de nouveau en ligne.
Aucune donnée personnelle n'est envoyée au service de notifications en dehors du texte de la notification.
"""
from __future__ import annotations

import base64
import json
import threading
import time

import db

SITE = "https://bet-prono.onrender.com"
HORS_LIGNE_S = 120
NOMS = {"apex": "APEX", "allstar": "ALL STAR", "principal": "Sonic", "manuel": "Bot manuel"}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS oeil_reglages (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS oeil_abonnements (
        endpoint TEXT PRIMARY KEY, compte_id INTEGER NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
        appareil TEXT, cree DOUBLE PRECISION)""",
    """CREATE TABLE IF NOT EXISTS oeil_alertes (compte_id INTEGER PRIMARY KEY, hors_ligne INTEGER DEFAULT 0, maj DOUBLE PRECISION)""",
]
_cles = None
_verrou = threading.Lock()


def init():
    for s in SCHEMA:
        db.run(s)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def cles():
    """(clé privée PEM, clé publique base64url) — créées au premier appel puis gardées dans la base."""
    global _cles
    if _cles:
        return _cles
    with _verrou:
        r = db.run("SELECT valeur FROM oeil_reglages WHERE cle = 'vapid'", one=True)
        if r:
            _cles = tuple(json.loads(r["valeur"]))
            return _cles
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        k = ec.generate_private_key(ec.SECP256R1())
        pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        pub = _b64(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        db.run("INSERT INTO oeil_reglages (cle, valeur) VALUES ('vapid', %s) ON CONFLICT (cle) DO NOTHING", (json.dumps([pem, pub]),))
        r = db.run("SELECT valeur FROM oeil_reglages WHERE cle = 'vapid'", one=True)
        _cles = tuple(json.loads(r["valeur"]))
        return _cles


def abonner(compte_id: int, sub: dict, appareil: str = ""):
    k = sub.get("keys") or {}
    if not sub.get("endpoint", "").startswith("https://") or not k.get("p256dh") or not k.get("auth"):
        raise ValueError("abonnement invalide")
    db.upsert("oeil_abonnements", ("endpoint",), {"endpoint": sub["endpoint"], "compte_id": compte_id, "p256dh": k["p256dh"],
                                                  "auth": k["auth"], "appareil": appareil[:60], "cree": time.time()})


def desabonner(compte_id: int, endpoint: str):
    db.run("DELETE FROM oeil_abonnements WHERE endpoint = %s AND compte_id = %s", (endpoint, compte_id))


def nb_abonnements(compte_id: int) -> int:
    r = db.run("SELECT COUNT(*) AS n FROM oeil_abonnements WHERE compte_id = %s", (compte_id,), one=True)
    return int(r["n"]) if r else 0


def envoyer(compte_id: int, titre: str, texte: str, tag: str = "") -> int:
    """Envoie à tous les appareils du compte. Retourne le nombre d'envois réussis. Les abonnements morts sont supprimés."""
    subs = db.run("SELECT endpoint, p256dh, auth FROM oeil_abonnements WHERE compte_id = %s", (compte_id,), all=True) or []
    if not subs:
        return 0
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush
    pem, _ = cles()
    signataire = Vapid.from_pem(pem.encode())
    ok = 0
    for s in subs:
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                    json.dumps({"titre": titre, "texte": texte, "tag": tag}, ensure_ascii=False),
                    vapid_private_key=signataire, vapid_claims={"sub": SITE}, ttl=3600, timeout=10)
            ok += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", 0)
            if code in (404, 410):   # l'appareil a retiré la permission ou supprimé l'icône
                db.run("DELETE FROM oeil_abonnements WHERE endpoint = %s", (s["endpoint"],))
        except Exception:  # noqa: BLE001
            pass
    return ok


def envoyer_fond(compte_id: int, titre: str, texte: str, tag: str = ""):
    threading.Thread(target=envoyer, args=(compte_id, titre, texte, tag), daemon=True).start()


# ------------------------------------------------------------------ événements
def eur(x, dev="EUR"):
    if x is None:
        return "—"
    s = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",")
    return ("+" if x >= 0 else "−") + s + (" $" if dev == "USD" else " €")


def evenements(source: str, avant: dict | None, apres: dict) -> list[tuple[str, str, str]]:
    """Compare l'ancien et le nouvel état d'un bot : [(titre, texte, tag)] pour chaque trade ouvert ou fermé."""
    if avant is None:
        return []   # premier envoi : on ne notifie pas toutes les positions déjà ouvertes
    nom, dev = NOMS.get(source, source), apres.get("devise") or "EUR"
    av = {str(p.get("ticket")): p for p in avant.get("positions") or [] if p.get("ticket") is not None}
    ap = {str(p.get("ticket")): p for p in apres.get("positions") or [] if p.get("ticket") is not None}
    out = []
    for t, p in ap.items():
        if t not in av:
            sens = p.get("sens") or ""
            out.append((f"{'📈' if sens == 'BUY' else '📉' if sens == 'SELL' else '🔔'} {nom} : trade ouvert",
                        f"{sens} {p.get('symbole') or ''}{' · ' + str(p.get('volume')) + ' lot' if p.get('volume') else ''} à {p.get('prix')}".strip(),
                        f"{source}-{t}"))
    for t, p in av.items():
        if t not in ap:
            pr = p.get("profit")
            out.append((f"{'✅' if (pr or 0) >= 0 else '❌'} {nom} : trade fermé",
                        f"{p.get('sens') or ''} {p.get('symbole') or ''} · environ {eur(pr, dev)}".strip(), f"{source}-{t}"))
    return out[:6]


def verifier_hors_ligne():
    """Toutes les 60 s : un compte dont le PC n'envoie plus depuis 2 min reçoit UNE alerte, puis une autre au retour."""
    rows = db.run("SELECT compte_id, MAX(maj) AS maj FROM oeil_etats GROUP BY compte_id", all=True) or []
    now = time.time()
    for r in rows:
        cid, maj = r["compte_id"], r["maj"] or 0
        a = db.run("SELECT hors_ligne FROM oeil_alertes WHERE compte_id = %s", (cid,), one=True)
        etait = bool(a and a["hors_ligne"])
        hors = now - maj > HORS_LIGNE_S
        if hors and not etait:
            envoyer(cid, "⚠️ PC hors ligne", "Ton PC n'envoie plus rien depuis 2 min : veille, coupure ou internet ? Tes bots ne tournent sans doute plus.", "hors-ligne")
        elif etait and not hors:
            envoyer(cid, "✅ PC de nouveau en ligne", "Le site reçoit à nouveau l'état de tes bots.", "hors-ligne")
        if hors != etait or not a:
            db.upsert("oeil_alertes", ("compte_id",), {"compte_id": cid, "hors_ligne": int(hors), "maj": now})


HEURE_BILAN = 23   # heure de Paris


def texte_bilan(cid: int, debut: float) -> tuple[str, str] | None:
    """Bilan des trades fermés depuis `debut` (minuit, heure de Paris), par bot. None s'il n'y a rien à dire."""
    rows = db.run("SELECT source, COUNT(*) AS n, SUM(net) AS net, SUM(CASE WHEN net > 0 THEN 1 ELSE 0 END) AS g, MAX(devise) AS devise "
                  "FROM oeil_trades WHERE compte_id = %s AND fermeture_t >= %s GROUP BY source", (cid, debut), all=True) or []
    if not rows:
        return "📊 Bilan du jour", "Aucun trade fermé aujourd'hui."
    ordre = ["apex", "allstar", "principal", "manuel"]
    rows.sort(key=lambda r: ordre.index(r["source"]) if r["source"] in ordre else 9)
    parts, tot, n = [], 0.0, 0
    for r in rows:
        net = float(r["net"] or 0)
        parts.append(f"{NOMS.get(r['source'], r['source'])} {eur(net, r['devise'] or 'EUR')} ({int(r['n'])})")
        if (r["devise"] or "EUR") == "EUR":
            tot += net
        n += int(r["n"])
    return f"📊 Bilan du jour : {eur(tot)}", " · ".join(parts) + f" — {n} trades"


def verifier_bilan_soir():
    """Une fois par jour, à 23 h (Paris) : bilan des trades fermés du jour à chaque compte qui a un téléphone abonné."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    maintenant = datetime.now(ZoneInfo("Europe/Paris"))
    if maintenant.hour < HEURE_BILAN:
        return
    jour = maintenant.strftime("%Y-%m-%d")
    debut = maintenant.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    for r in db.run("SELECT DISTINCT compte_id FROM oeil_abonnements", all=True) or []:
        cid, cle = r["compte_id"], f"bilan_{r['compte_id']}"
        deja = db.run("SELECT valeur FROM oeil_reglages WHERE cle = %s", (cle,), one=True)
        if deja and deja["valeur"] == jour:
            continue
        db.upsert("oeil_reglages", ("cle",), {"cle": cle, "valeur": jour})
        b = texte_bilan(cid, debut)
        if b:
            envoyer(cid, b[0], b[1], "bilan")


_garde = {"lance": False}


def lancer_surveillance():
    if _garde["lance"]:
        return
    _garde["lance"] = True

    def boucle():
        while True:
            for f in (verifier_hors_ligne, verifier_bilan_soir):
                try:
                    f()
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(60)
    threading.Thread(target=boucle, daemon=True).start()


# ------------------------------------------------------------------ 23/11 : alertes de risque (réglées par l'utilisateur)
def _lire(cle: str, defaut):
    r = db.run("SELECT valeur FROM oeil_reglages WHERE cle = %s", (cle,), one=True)
    try:
        return json.loads(r["valeur"]) if r else defaut
    except ValueError:
        return defaut


def _ecrire(cle: str, val):
    db.upsert("oeil_reglages", ("cle",), {"cle": cle, "valeur": json.dumps(val, ensure_ascii=False)})


def reglages_alertes(cid: int) -> dict:
    return _lire(f"alertes_{cid}", {})


def enregistrer_alertes(cid: int, d: dict) -> dict:
    propre = {}
    for src in NOMS:
        x = d.get(src) or {}
        r = {}
        for k in ("perte_jour", "equite_min"):
            try:
                v = float(str(x.get(k, "")).replace(",", ".")) if str(x.get(k, "")).strip() else None
            except ValueError:
                v = None
            if v is not None and v > 0:
                r[k] = round(v, 2)
        try:
            n = int(x.get("serie") or 0)
        except ValueError:
            n = 0
        if 2 <= n <= 50:
            r["serie"] = n
        if r:
            propre[src] = r
    _ecrire(f"alertes_{cid}", propre)
    return propre


def _jour_paris() -> tuple[str, float]:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    m = datetime.now(ZoneInfo("Europe/Paris"))
    return m.strftime("%Y-%m-%d"), m.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def verifier_risque(cid: int, etats: dict | None = None, sources_trades: set | None = None):
    """Vérifie les seuils choisis par l'utilisateur ; chaque alerte ne part qu'une fois (par jour, par série, par passage du seuil)."""
    cfg = reglages_alertes(cid)
    if not cfg:
        return
    jour, debut = _jour_paris()
    deja = _lire(f"risque_{cid}", {})
    if deja.get("jour") != jour:
        deja = {"jour": jour, "perte": [], "serie": deja.get("serie", {}), "eq": deja.get("eq", {})}
    change = False
    for src, c in cfg.items():
        nom = NOMS.get(src, src)
        if etats and src in etats and "equite_min" in c and isinstance(etats[src].get("equite"), (int, float)):
            sous = etats[src]["equite"] < c["equite_min"]
            if sous and not deja["eq"].get(src):
                envoyer_fond(cid, f"🛑 {nom} : équité sous {c['equite_min']:g}", f"Équité actuelle {eur(etats[src]['equite']).lstrip('+')}. Vérifie le bot.", f"eq-{src}")
            if sous != bool(deja["eq"].get(src)) and (sous or etats[src]["equite"] > c["equite_min"] * 1.005):
                deja["eq"][src] = sous; change = True
        if sources_trades and src in sources_trades:
            if "perte_jour" in c and src not in deja["perte"]:
                r = db.run("SELECT SUM(net) AS net FROM oeil_trades WHERE compte_id = %s AND source = %s AND fermeture_t >= %s", (cid, src, debut), one=True)
                net = float(r["net"] or 0) if r else 0.0
                if net <= -c["perte_jour"]:
                    envoyer_fond(cid, f"⚠️ {nom} : perte du jour {eur(net)}", f"Ton seuil de −{c['perte_jour']:g} € est atteint. Pense à arrêter le bot si besoin.", f"perte-{src}")
                    deja["perte"].append(src); change = True
            if "serie" in c:
                L = db.run("SELECT ticket, net FROM oeil_trades WHERE compte_id = %s AND source = %s ORDER BY fermeture_t DESC LIMIT %s",
                           (cid, src, c["serie"]), all=True) or []
                if len(L) == c["serie"] and all((t["net"] or 0) < 0 for t in L) and deja["serie"].get(src) != L[0]["ticket"]:
                    tot = sum(t["net"] or 0 for t in L)
                    envoyer_fond(cid, f"📉 {nom} : {c['serie']} pertes d'affilée", f"Total {eur(tot)} sur les {c['serie']} derniers trades.", f"serie-{src}")
                    deja["serie"][src] = L[0]["ticket"]; change = True
    if change or deja.get("jour") != _lire(f"risque_{cid}", {}).get("jour"):
        _ecrire(f"risque_{cid}", deja)
