# BET PRONO AI — Bêta

La page est accessible depuis la navigation du tableau de bord, sur ordinateur
et mobile. Elle utilise la session existante et ne modifie ni les paris, ni la
bankroll, ni les statistiques. Aucune migration de base de données n'est requise.

## Ce qui fonctionne

- Choix du sport et saisie de deux équipes ou joueurs (2 à 80 caractères).
- Validation serveur, normalisation des espaces et refus de deux adversaires identiques.
- Rapport explicitement marqué **Démonstration — aucune prédiction** : rencontre
  non vérifiée, statistiques indisponibles, probabilités et pronostic non calculés.
- Aperçu facultatif d'une capture PNG/JPEG, maximum 5 Mio et 16 mégapixels.
  L'image reste dans le navigateur, sans requête réseau, stockage ou OCR.
  La sélection est contrôlée par type, signature et décodage ; SVG non accepté.
  Le bouton Retirer libère l'aperçu. Les URL temporaires sont révoquées au retrait,
  au remplacement et à la sortie de page. Ne pas confondre cet aperçu avec un
  téléversement serveur ou une analyse de l'image.
- États de chargement, erreurs de validation/réseau et délai de réponse de 15 secondes.
- Accès API limité aux utilisateurs authentifiés et non bannis, sans clé externe.

## Tester en local

Utiliser une copie de développement du dépôt, sans `local.env` de production.
Laisser `DATABASE_URL` vide pour rester sur SQLite locale.

```sh
python -m pip install -r requirements.txt
python app.py
```

Sous Windows, si la base des fuseaux horaires est absente :
`python -m pip install tzdata`.

1. Ouvrir `http://127.0.0.1:5000/login` et créer un compte de test ou se connecter.
2. Ouvrir **BET PRONO AI · BÊTA** (sur mobile : **AI · Bêta**).
3. Choisir Football, saisir Paris Saint-Germain et Olympique de Marseille, puis
   cliquer sur **Voir le rapport de démonstration**.
4. Vérifier que le rapport ne contient aucun score, pourcentage ou pronostic inventé.
5. Modifier un nom : le rapport précédent est masqué jusqu'à la prochaine soumission.
6. Essayer deux noms identiques, un champ vide et une capture invalide ; vérifier les erreurs.
7. Choisir une vraie capture PNG/JPEG, puis la retirer. Aucun fichier ne doit être
   envoyé dans l'onglet Réseau du navigateur.
8. Revenir aux paris, analyses et réglages ; vérifier que les données sont conservées.
9. Répéter sur un écran de 320 à 390 px de large, puis sur ordinateur.

## Tests automatisés

```sh
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/bet-prono-ai.js
```

Les tests Flask copient le module dans un répertoire temporaire avant son import,
neutralisent `DATABASE_URL` et créent leur propre base SQLite jetable. Ils couvrent
authentification/session expirée/compte banni, saisies mal formées, limites de
taille, sports acceptés, absence d'appels externes et conservation/isolation des paris.

Tests navigateur optionnels (aucune dépendance ajoutée à la production) :

```sh
python -m pip install playwright
python -m playwright install chromium
python tests/browser_ai.py
```

`BROWSER_CHANNEL=msedge` permet d'utiliser Edge installé.
`AI_SCREENSHOT_DIR` permet d'enregistrer deux captures du rendu.
Le script lance un serveur local sur un port libre avec la même base jetable,
teste cinq largeurs de 320 à 1440 px, la navigation, les erreurs API, le rendu des
noms comme texte, les images valides/invalides et la redirection vers la connexion.
Il ne teste pas le fournisseur Google OAuth ni PostgreSQL/Neon ; ces intégrations
ne sont pas modifiées par cette bêta.

## API de démonstration

`POST /api/ai/analyze`, cookie de connexion existant et `Content-Type: application/json` :

```json
{"sport":"football","home_team":"Paris","away_team":"Marseille"}
```

Réponse 200 : `mode: "demo"`, noms normalisés, liste des informations à vérifier,
`sources: []`, `prediction: null`, `Cache-Control: no-store`.
Erreurs : 400 saisie invalide, 401 session absente/invalide, 403 compte banni,
415 format non JSON ; la limite globale existante de 256 Kio reste inchangée (413).
Aucun historique d'analyse n'est enregistré. La requête contient uniquement le
sport et les noms, jamais l'image.

## Avant une analyse réelle

Il faudra choisir et connecter une API sportive autorisée, identifier les
rencontres sans ambiguïté (équipes/joueurs, compétition, date), puis afficher
les sources et leur fraîcheur. Les données manquantes devront rester signalées.

Un modèle d'analyse devra être évalué sur des résultats historiques séparés de
ses données d'entraînement, avec mesure de calibration et d'incertitude avant
toute publication de probabilités. Le simple branchement d'un modèle de langage
ne constitue pas une méthode de prédiction validée. Les clés devront rester
côté serveur, avec délais, quotas, limites de débit et gestion des pannes.

La lecture de captures nécessitera un service OCR/vision et une confirmation des
équipes détectées. Tout futur envoi d'image devra avoir sa propre validation
serveur, des limites de décodage, un stockage privé et une politique de suppression.
L'aperçu actuel ne fournit aucune de ces capacités serveur.

Une éventuelle sauvegarde d'historique devra être isolée par utilisateur.
La fusion et le déploiement doivent faire l'objet d'une décision distincte :
cette livraison prépare uniquement la branche et la pull request.
