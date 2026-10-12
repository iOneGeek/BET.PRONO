# BET.PRONO — Suivi de bankroll (multi-comptes, PWA)

Application web avec comptes séparés : chaque personne crée son identifiant/mot de passe
et ne voit que sa propre bankroll et ses propres paris. Installable comme une app
(PWA) sur téléphone ou ordinateur.

## Lancer en local

```bash
python -m pip install -r requirements.txt
python app.py
```

Puis ouvrir http://127.0.0.1:5000 dans le navigateur. Chacun peut créer son compte
depuis cette page (onglet « Créer un compte »).

Les données sont stockées dans une base de données :
- **En local**, par défaut dans `instance/bankroll.db` (SQLite), ignoré par git.
- **Dès qu'une variable d'environnement `DATABASE_URL` existe** (PostgreSQL, ex. Neon),
  l'application utilise automatiquement cette base cloud persistante (aucune perte
  à chaque redéploiement).

Ce fichier `instance/bankroll.db` ne doit jamais être partagé ni commité : il
contient les mots de passe (hashés) et les paris de tous les comptes.

## Installer l'app (PWA)

Une fois le site ouvert dans Chrome/Edge/Safari (depuis son adresse publique, voir
plus bas) :
- **Android / Chrome** : menu ⋮ → « Installer l'application ».
- **iPhone / Safari** : bouton Partager → « Sur l'écran d'accueil ».
- **Ordinateur / Chrome / Edge** : icône d'installation dans la barre d'adresse.

L'icône s'ajoute à l'écran d'accueil et l'app s'ouvre en plein écran, sans barre de
navigateur.

## Déployer pour que tout le monde y accède depuis internet

Ce dépôt est un petit serveur Flask classique : il doit tourner quelque part en
continu avec une adresse publique en HTTPS (obligatoire pour l'installation PWA).
Options simples et gratuites pour démarrer :
- **Render.com** ou **Railway.app** : déploiement direct depuis ce dépôt GitHub,
  HTTPS automatique, offre gratuite suffisante pour un usage entre proches.
- **PythonAnywhere** : hébergement Flask gratuit, un peu plus manuel.

Dans tous les cas : définir une variable d'environnement ou un volume persistant
pour le dossier `instance/` (sinon la base de données est perdue à chaque
redéploiement), et ne jamais exposer ce dossier publiquement.

## Base de données persistance (recommandé)

Pour que les paris ne soient **jamais perdus** lors d'un redéploiement, utilise
une base PostgreSQL sur **Neon** (offre gratuite) :

1. Crée un compte sur https://console.neon.tech puis un projet.
2. Copie l'**URL de connexion** (commence par `postgresql://...`).
3. Sur Render : **Settings → Environment → Environment Variable** nommée
   `DATABASE_URL` = ton URL. (Pareil en local dans `local.env`.)
4. L'application utilisera alors automatiquement Neon à la place de SQLite.

La première fois, tu peux copier les données existantes avec :

```bash
DATABASE_URL=ton-url-neon python migrate_to_neon.py
```

⚠️ L'URL de Neon contient un mot de passe : ne la mets **jamais** en clair dans un
fichier commité sur GitHub. Uniquement dans le dashboard Render et dans
`local.env` (ignoré par git).

## Structure

- `app.py` — serveur Flask : authentification (cookie + JWT), API REST des paris,
  base de données SQLite (local) ou PostgreSQL (production, via `DATABASE_URL`).
- `migrate_to_neon.py` — copie une base SQLite locale vers une base PostgreSQL.
- `static/login.html` — connexion / création de compte.
- `static/app.html` + `static/app.js` — tableau de bord (graphique, stats, paris).
- `static/manifest.json`, `static/sw.js`, `static/icons/` — fichiers PWA.

## Sécurité

- Mots de passe hachés (jamais stockés en clair).
- Chaque utilisateur ne peut lire/modifier que ses propres paris (vérifié côté
  serveur sur chaque requête).
- Cookie de session en `httpOnly` (inaccessible en JavaScript).
