# BET.PRONO - Changelog Session Actuelle

## 1. Dashboard Admin + Pronos Partagés (COMPLÉTÉ)

### Backend (app.py)
- ✅ Ajout colonne `is_admin` à la table `users`
- ✅ Ajout tables `picks` (pronos) et `pick_follows` (suivi)
- ✅ Décorateur `@admin_required` pour protéger les routes admin
- ✅ Premier compte créé = admin automatiquement
- ✅ Routes API:
  - `GET /api/picks` - liste tous les pronos (avec statut de suivi par user)
  - `POST /api/admin/picks` - créer un prono (admin only)
  - `PATCH /api/admin/picks/<id>` - régler un prono (admin only)
  - `DELETE /api/admin/picks/<id>` - supprimer un prono (admin only)
  - `POST /api/picks/<id>/follow` - suivre un prono (auto-crée un pari)
  - `DELETE /api/picks/<id>/follow` - arrêter de suivre

### Frontend (app.html, app.js)
- ✅ Panneau admin (caché pour non-admin) pour publier des pronos
- ✅ Fil de pronos visible par tous avec badges de résultat
- ✅ Bouton "Suivre ce prono" pour les non-admin
- ✅ Mise à jour automatique des paris des followers quand admin règle le prono
- ✅ Suppression de l'ancienne fonctionnalité "Partager mon prono" (image Telegram/WhatsApp)

### Testé et Vérifié
- ✅ Création de prono par admin
- ✅ Refus 403 pour non-admin
- ✅ Suivi d'un prono crée automatiquement un pari dans la bankroll
- ✅ Règlement en cascade (admin règle → tous les followers' bets se mettent à jour)
- ✅ Désabonnement supprime le pari lié
- ✅ Suppression du prono par admin

---

## 2. Upload d'Images pour Pronos (COMPLÉTÉ)

### Backend (app.py)
- ✅ Ajout colonne `image_path` à la table `picks`
- ✅ Dossier `instance/uploads/` pour stocker les images
- ✅ Fonction `save_pick_image()` avec validation:
  - Formats acceptés: PNG, JPG, JPEG, WebP, GIF
  - Taille max: 5 Mo
  - Noms de fichiers sécurisés (UUID)
- ✅ Route `GET /uploads/<filename>` (authentifiée) pour servir les images
- ✅ `POST /api/admin/picks` accepte maintenant multipart/form-data avec fichier image
- ✅ Suppression automatique du fichier image quand le prono est supprimé

### Frontend (app.html, app.js)
- ✅ Champ `<input type="file">` dans le panneau admin
- ✅ Aperçu de l'image avant publication
- ✅ Envoi en FormData (JSON + fichier)
- ✅ Affichage de l'image dans les cartes de pronos
- ✅ Pronos sans image fonctionnent toujours (rétrocompatibilité)

### Testé et Vérifié
- ✅ Upload d'une image GIF
- ✅ Accès à l'image authentifié (401 sans cookie)
- ✅ Suppression du prono supprime aussi le fichier
- ✅ Création de prono sans image fonctionne

---

## 3. Nouvelle Palette de Couleurs: Onyx + Potrion (COMPLÉTÉ)

### Couleurs Appliquées

**LIGHT MODE (par défaut):**
- `--bg`: #f1efec (beige clair)
- `--panel`: #fff (blanc)
- `--line`: #ded8d2 (gris clair)
- `--text`: #353839 (Onyx - texte principal)
- `--mute`: #6b6f70 (gris moyen)
- `--field`: #f6f4f1 (beige très clair)
- `--accent`: #ff7518 (Potrion - boutons, focus, badges)
- `--on-accent`: #1c1100 (texte sur Potrion)
- `--gain`: #0a8f65 (vert - gains financiers)
- `--loss`: #d1415a (rouge - pertes financières)

**DARK MODE:**
- `--bg`: #202223 (gris très foncé)
- `--panel`: #353839 (Onyx - panneaux)
- `--line`: #484c4d (gris foncé)
- `--text`: #f3efe9 (beige clair)
- `--mute`: #aeb2b3 (gris clair)
- `--field`: #2b2d2e (gris foncé)
- `--accent`: #ff7518 (Potrion - même en dark)
- `--gain`: #19e6a0 (vert clair)
- `--loss`: #ff7a8a (rouge clair)

### Fichiers Modifiés
- ✅ `static/app.html` - CSS variables + tous les éléments interactifs
- ✅ `static/login.html` - CSS variables + boutons
- ✅ `static/manifest.json` - theme_color + background_color

### Éléments Redessinés
- ✅ Tous les boutons primaires (`.primary`) → Potrion
- ✅ Tous les focus outlines → Potrion
- ✅ Badges admin → Potrion
- ✅ Cotes totales → Potrion
- ✅ Checkboxes → Potrion
- ✅ Onglets actifs → Potrion
- ✅ Graphique → dégradé Onyx

---

## 4. État Actuel

### Compte Admin
- **Pseudo**: iOneGeek
- **Mot de passe**: iOneLaw*06
- **Statut**: Admin (premier compte créé)

### Serveur
- **URL**: http://127.0.0.1:5000
- **Pages**:
  - `/login` - Connexion/Inscription
  - `/app` - Tableau de bord (Accueil + Bankroll)

### Base de Données
- **Fichier**: `instance/bankroll.db`
- **Tables**: users, bets, picks, pick_follows
- **Migrations**: Appliquées automatiquement au démarrage

---

## 5. Prochaines Étapes (Non Implémentées)

### Inscription avec Email (Bloqué - Attente de Configuration)
- Besoin d'un service d'envoi d'email (Gmail, Brevo, Mailgun, etc.)
- Attente de l'adresse email et du mot de passe d'application

### Fonctionnalités Optionnelles (Non Demandées)
- Filtre Historique/En cours sur le fil de pronos
- Stats publiques de l'admin (taux de réussite, etc.)
- Outils d'analyse (convertisseur cote ↔ probabilité, calculette de mise)
- Système VIP (abonnement payant)

---

## 6. Fichiers Modifiés

```
app.py                    - Backend complet (API, DB, uploads)
static/app.html          - Dashboard + CSS Onyx/Potrion
static/login.html        - Connexion + CSS Onyx/Potrion
static/app.js            - Logique pronos + upload image
static/manifest.json     - Couleurs PWA
.gitignore              - Ajout server.log
```

---

## 7. Validation

- ✅ Syntaxe Python (app.py)
- ✅ Délimiteurs HTML/JS équilibrés
- ✅ Couleurs appliquées partout
- ✅ API testée (curl)
- ✅ Base de données valide
- ✅ Rétrocompatibilité (JSON-only toujours accepté)

