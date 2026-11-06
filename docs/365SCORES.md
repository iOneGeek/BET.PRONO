# Données football 365Scores — intégration expérimentale

## Fonctionnement et limites

Dans **BET PRONO AI**, « Trouver un vrai match » charge les rencontres de football
pour une date (fuseau Europe/Paris, aujourd'hui ±30 jours). Le filtre par équipe
ou compétition est appliqué côté serveur, sans transmettre les noms saisis au
fournisseur. Les accents et la casse sont ignorés. Une recherche vide liste la
journée ; au-delà de 200 résultats, préciser la recherche.

L'utilisateur sélectionne explicitement une rencontre, identifiée par son ID
365Scores, ses adversaires, sa compétition et son horaire. La fiche affiche le
statut, les scores disponibles et les statistiques de match fournies pour les
deux identifiants d'équipe. Une valeur absente reste « Indisponible », jamais zéro.
Les scores d'une rencontre programmée ne sont pas affichés. Les statistiques
de périodes distinctes ne sont pas mélangées avec celles du match complet.

La source et l'heure **de récupération** sont visibles. Cette heure ne garantit
pas la fraîcheur des données en amont : des scores peuvent être différés et la
couverture peut être partielle. Les noms et intitulés restent dans la langue
de la source (anglais avec le paramètre actuellement testé).

Le connecteur sportif ne récupère pas de pronostics ou de cotes et ne recommande
aucune mise. Une [synthèse IA optionnelle](AUTO_ANALYSIS.md) est désormais demandée
automatiquement après l'affichage du match, sans bouton supplémentaire.
Elle ne modifie ni les paris ni la bankroll et ne calcule aucune prédiction.
Le formulaire de démonstration multisport et l'aperçu local d'image restent séparés.

Pour une rencontre programmée sans statistiques, la fiche récupère les références
`recentMatches` des deux équipes, au maximum 15 chacune. Une consultation groupée
de `games/allscores/` avec `games=<identifiants>` et `showOdds=false` fournit les résultats.
Seuls les matchs de football terminés, antérieurs à la fois à maintenant et au coup
d'envoi sélectionné, avec identifiant demandé, équipe correspondante et scores
entiers disponibles sont retenus. Ils sont dédupliqués, triés par date et limités
aux cinq plus récents disponibles pour chaque équipe. Les résultats, dates et
compétitions sont affichés avant la synthèse. Une panne de l'historique laisse la
fiche consultable et indique les données manquantes. Le budget de récupération
d'une fiche est de 22 secondes pour l'ensemble de ses appels.

Ce parcours a été vérifié le 6 novembre 2026 sur Valencia–Real Madrid
(référence 4750793), avec cinq résultats récupérés par équipe. L'analyse du modèle
reste testée avec des réponses simulées jusqu'à validation réelle sur Render.

## Service testé

Hôte fixe : `https://webws.365scores.com/web/`.

- `games/allscores/` : `appTypeId=5`, `langId=1`, `timezoneName=Europe/Paris`,
  `sports=1`, `startDate` et `endDate` au format `DD/MM/YYYY`,
  `showOdds=false`, `onlyMajorGames=false`.
- `game/stats/` : paramètres communs et `games=<identifiant>`.
- `game/` : paramètres communs et `gameId=<identifiant>`, lorsque les statistiques
  renvoient une enveloppe valide sans rencontre. Ce cas a été vérifié sur deux matchs
  programmés le 6 novembre 2026. La fiche affiche alors les informations disponibles
  avec une liste de statistiques vide. Un refus HTTP ne déclenche pas ce second appel.

Les réponses ont été vérifiées directement sur le service public le 4 novembre
2026, sans clé, cookie, faux Origin/Referer ou identité de navigateur. Une recherche
réelle et une fiche avec statistiques ont également traversé le connecteur final.
Les réponses brutes et les données de matchs ne sont pas commitées.

Aucune documentation officielle de contrat partenaire n'a été identifiée pour
ces points d'accès web. Ne pas présenter cette intégration comme une API officielle
garantie : le schéma, l'accès et la couverture peuvent changer. Une réponse refusée
ou non reconnue produit une erreur explicite, sans contournement ni faux résultat.

## Configuration

Aucune clé API supplémentaire. `SPORTS_DATA_ENABLED=1` active la consultation
(valeur par défaut) ; `SPORTS_DATA_ENABLED=0` la désactive sans affecter le reste
de l'application. Configurer cette variable dans Render > Environment ou dans
`local.env`. Pas de nouvelle dépendance de production, migration ou tâche planifiée.
La synthèse automatique utilise séparément `GEMINI_API_KEY`, uniquement côté serveur ;
elle reste indisponible sans cette clé, tandis que les données sportives fonctionnent.

Seuls des clics explicites déclenchent une recherche ou une fiche. Aucun sondage
automatique ni téléchargement d'image/logo distant n'est ajouté.

## Protections et cache

- Les deux routes réutilisent `login_required`, y compris le refus des comptes bannis.
- Cache mémoire partagé entre les utilisateurs d'un même processus : 60 secondes,
  32 réponses maximum. Le cache conserve l'heure d'origine et n'est pas servi après expiration.
- Au plus 20 demandes utilisateur/minute et 20 appels fournisseur/minute/processus.
  Les succès en cache n'utilisent pas le quota fournisseur. Les recherches d'une
  même date partagent le cache, même avec des noms différents.
- Cache et limitations protégés par verrou pour les threads ; un seul appel
  fournisseur à la fois évite les requêtes identiques simultanées.
- Délais connexion/lecture 3,05/6 secondes et contrôle d'un budget de 10 secondes
  pendant la lecture des blocs ; 2 Mio maximum par réponse décompressée.
- Pas de redirection HTTP, de nouvelle tentative automatique ou d'URL fournie
  par l'utilisateur. Pause des appels après erreur (30 s, 60 s après quota 429).
- Les erreurs ne divulguent ni réponse brute ni détails internes ; le navigateur
  réactive les contrôles après erreur. Les données sont rendues comme texte.
- Réponses applicatives `Cache-Control: no-store`, aucune persistance en base.

**Plusieurs workers/instances :** chaque processus a son cache et ses compteurs.
Avant de multiplier les instances, prévoir un cache/limiteur partagé (par exemple
Redis) pour imposer une limite globale. Ces limites locales sont nos protections,
pas un quota contractuel annoncé par 365Scores.

## Routes

- `GET /api/ai/matches?date=YYYY-MM-DD&q=Paris` : liste, source, heure de récupération,
  marqueur de cache, nombre total et indicateur de résultats tronqués/incomplets.
- `GET /api/ai/matches/<id>` : fiche, statistiques, source, heure, `prediction: null`.

Erreurs : 400 saisie invalide, 401 session absente, 403 compte banni, 404 rencontre
introuvable/incomplète, 429 limite atteinte (`Retry-After: 60`), 502 schéma inconnu,
503 service désactivé/indisponible ou accès refusé en amont.

## Tester

1. Lancer la branche localement avec SQLite et un compte de test, comme dans le README.
2. Ouvrir BET PRONO AI, choisir la date du jour et cliquer sur Chercher les matchs.
3. Filtrer par un nom figurant dans la liste ; sélectionner une rencontre.
4. Vérifier identité/date/compétition, source, heure de récupération et statistiques.
   Un match à venir peut ne pas avoir de statistiques : cela doit être indiqué.
5. Changer le filtre : l'ancien rapport disparaît. Vérifier le rendu mobile.
6. Désactiver le service via `SPORTS_DATA_ENABLED=0`, redémarrer et vérifier le message
   d'indisponibilité ; le formulaire de démonstration et les paris doivent fonctionner.

```sh
python -m unittest discover -s tests -v
node --check static/sports-data.js
python tests/browser_ai.py
```

Le dernier script utilise Playwright (installation dans le guide bêta). Les tests
automatisés utilisent des données **synthétiques**, une base temporaire et des
réponses fournisseur simulées : aucun compte réel ni appel fournisseur en CI.
Ils couvrent également la démonstration, l'authentification, les quotas/cache,
le schéma invalide, le réseau, les données absentes, l'injection HTML et le mobile.
Les captures portant `365scores-test` représentent des données de test.

L'intégration est livrée sur une branche avec PR ; cette modification ne déclenche
aucune fusion ou mise en production manuelle.
