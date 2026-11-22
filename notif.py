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


_garde = {"lance": False}


def lancer_surveillance():
    if _garde["lance"]:
        return
    _garde["lance"] = True

    def boucle():
        while True:
            try:
                verifier_hors_ligne()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(60)
    threading.Thread(target=boucle, daemon=True).start()
