# BET PRONO AI — Bêta (V2.6.0)

L'onglet **BET PRONO AI** (sur mobile : **AI · Bêta**) affiche des rencontres de
football et de hockey sur glace issues de 365Scores, une fiche par match, une analyse
générée par Gemini, un modèle statistique et le bilan réel des pronostics.

Voir aussi : [connecteur 365Scores](365SCORES.md) et
[configuration de l'analyse Gemini](AUTO_ANALYSIS.md).

## Ce que voit l'utilisateur

0. **Tableau de bord** (V2.6.0) : en haut, la carte « ⭐ Mes pronos suivis » montre les matchs suivis
   en direct (score, minute, « en bonne voie » ou non), puis à venir (30 jours, compte à rebours) et
   terminés du jour (✓ / ✕), retirés le lendemain à minuit. Actualisation chaque minute pendant un match, sinon toutes les 5 min,
   en pause quand l'onglet est masqué (`GET /api/ai/follows/dashboard`, 4 scores en direct au plus).

1. **Bilan des pronostics** (haut de l'onglet) : pourcentage de bons vainqueurs,
   de scores exacts et de buteurs trouvés, réussite de « Mes pronos suivis », et les
   derniers pronostics vérifiés.
2. **Mes pronos suivis** : les pronos que l'utilisateur a choisi de suivre (bouton
   « Suivre ce prono » dans la fiche), en attente puis vérifiés ✓ / ✗ après le match.
   Le prono est figé au moment du clic. « Retirer » le supprime de la liste.
3. **Recherche** : sport, date (±30 jours), équipe ou compétition, et menu
   **Compétition** rempli avec les compétitions du jour. Ligue 1, Ligue 2,
   Coupe de France, Ligue des champions, Ligue Europa, Ligue Europa Conférence et
   Ligue des nations apparaissent en tête (« À la une »), puis les autres par popularité.
4. **Fiche du match** (animation de chargement pendant la consultation et l'analyse) :
   - pronostic calculé par le modèle, affiché tout de suite : vainqueur et sa
     probabilité, double chance, score estimé, buteur possible et sa probabilité de marquer ;
     bouton **Suivre ce prono** ;
   - **modèle statistique** : probabilités victoire / nul / défaite, buts attendus,
     score le plus fréquent tous résultats confondus, plus de 2,5 buts (5,5 au hockey), les deux équipes marquent ;
   - **forme et confrontations** : victoires-nuls-défaites, buts marqués et encaissés
     par match, bilan domicile / extérieur, cinq dernières confrontations directes ;
   - statistiques 365Scores, suivi en direct, résultats récents et analyse IA.

## Fonctionnement

### Données (`sports_data.py`)
- Chaque match porte `decided` (`regulation`, `overtime`, `shootout`, `extra_time`,
  `penalties`) et `regulation`, le score en fin de temps réglementaire quand il est
  connu. Au hockey, un match gagné en prolongation ou aux tirs au but était à égalité
  au score du perdant après 60 minutes.
- Les confrontations directes viennent de `games/h2h/` (5 maximum, terminées, avant le match).
- `final_result()` récupère le score final et les buteurs (hors tirs au but et
  contre-son-camp) pour vérifier un pronostic.

### Modèle statistique (`match_model.py`)
Modèle volontairement simple et lisible, **qui décide du pronostic** :
- moyennes de buts marqués et encaissés sur les **10 derniers résultats** au plus
  (temps réglementaire au hockey), les plus récents comptant davantage (×0,85 par match
  plus ancien), rapprochées d'une valeur de référence quand l'échantillon est petit ;
- avantage du terrain léger ; loi de Poisson avec la **correction de Dixon-Coles** au
  football (0-0 et 1-1 un peu plus fréquents) ;
- prono : le résultat le plus probable (1 / N / 2), puis le score le plus probable
  **parmi ce résultat** (il peut différer du score le plus fréquent tous résultats confondus) ;
- buteur : probabilité de marquer = buts par match du joueur × écart attendu dans ce match
  × disponibilité (composition confirmée 100 %, probable 90 %, inconnue 80 %). Le plus
  probable de l'équipe qui marque est proposé s'il dépasse 15 %.

Il exige trois résultats vérifiés par équipe. C'est un point de repère, pas une garantie :
sa réussite réelle est mesurée dans le bilan.

### Analyse IA (`match_analysis.py`)
- Gemini **explique** le match à partir des faits vérifiés (statistiques, résultats récents,
  forme calculée, confrontations directes, buts attendus du modèle) et cite ses sources.
  Il ne choisit plus le score ni le buteur : c'est le modèle.
- Jusqu'à 3 analyses en parallèle ; une analyse déjà prête est toujours servie, même
  quand d'autres sont en cours.
- Une réponse mal formée, refusée ou tronquée est **réessayée une fois**. Elle ne bloque
  pas les autres utilisateurs et n'est pas décomptée du quota de l'utilisateur.
- Seules les vraies pannes (quota, clé refusée, modèle introuvable, service indisponible)
  mettent l'analyse en pause pour tous, de 45 s à 5 min selon le cas.
- Les analyses validées sont gardées **6 h en base** (`ai_analysis_cache`) : un
  redémarrage du serveur sur Render ne relance pas Gemini.

### Bilan des pronostics (`app.py`)
- Chaque pronostic est enregistré dans `ai_predictions` à l'ouverture de la fiche
  (dernier pronostic avant le coup d'envoi).
- `POST` / `DELETE /api/ai/follows/<id>` suit ou retire un prono (table `ai_follows`,
  500 au maximum par compte) ; `GET /api/ai/follows` renvoie la liste et sa réussite.
  Les matchs suivis sont vérifiés en priorité.
- `GET /api/ai/track-record` vérifie jusqu'à 3 matchs commencés depuis plus de 2 h à
  chaque consultation, puis renvoie les taux de réussite.
- Hockey : comparé au temps réglementaire. Football avec prolongation : seul le match
  nul après 90 minutes est compté (score exact inconnu). Un match sans résultat après
  2 jours est écarté.

Les tables sont créées automatiquement au démarrage (SQLite en local, PostgreSQL/Neon
en production). Aucune migration manuelle.

## Nouveautés V2.5.0

### Données en plus (`sports_data.py`)
- **Classement** (`standings/`, cache 30 min) : matchs joués, buts marqués et encaissés des deux
  équipes, et moyenne de buts de la compétition. Absent si les équipes ne partagent pas de tableau
  (coupe entre divisions).
- **Cotes** (`bets/lines/`, cache 5 min) : 1N2, plus/moins de buts (2,5 au football, 5,5 au hockey) et
  « les deux équipes marquent », converties en probabilités sans la marge du bookmaker. 365Scores ne
  les sert pas pour la France : un pays international est utilisé, en lecture seule, sans lien de pari.
- **Absents** : joueurs listés absents ou incertains avant le match, avec leurs buts. Un absent n'est
  jamais proposé comme buteur.
- Ces données sont facultatives : si elles manquent, le modèle fonctionne comme avant et leur échec
  ne met pas en pause l'accès 365Scores.

### Modèle (`match_model.py`)
- Moyenne de buts **de la compétition** quand le classement est connu.
- **Force sur la saison** (attaque et défense rapportées à la moyenne de la compétition), mélangée à
  55 % avec la forme récente.
- **Absents** : un buteur absent réduit l'attaque de son équipe de la moitié de sa part des buts
  (au plus −25 %).
- Prono : marchés (double chance, plus/moins de buts, les deux équipes marquent) comparés aux cotes,
  et indicateur **« match serré »** quand le résultat le plus probable est sous 45 % (42 % au hockey).
- Non disponible : gardien titulaire au hockey (la source ne le donne pas avant le match).

### Gemini explique le prono (`match_analysis.py`, prompt v6)
« Pourquoi ce prono ? » : deux ou trois phrases qui citent le fait `pick_model`. Les chiffres doivent
venir des faits cités ; conseils de mise et certitudes (« garanti », « 100 % »…) sont refusés.

### Justesse des pourcentages et vérification automatique (`app.py`)
- Les probabilités du modèle et des bookmakers sont enregistrées avec chaque prono.
- Bilan : réussite attendue / réelle par tranche (calibration), score de Brier du modèle et des
  bookmakers sur les mêmes matchs, réussite des marchés de buts. Avis « peu de matchs » sous 100 pronos.
- Vérification toutes les 30 min tant que le serveur tourne, plus `POST /api/ai/settle` (en-tête
  `X-Cron-Token`, invisible sans la variable `CRON_TOKEN`) appelé chaque heure par
  `.github/workflows/settle-predictions.yml` pour réveiller le site. À configurer : `CRON_TOKEN` (24
  caractères minimum) dans Render **et** dans les secrets GitHub du dépôt.

## Tester en local

Utiliser une copie de développement, sans `local.env` de production, et laisser
`DATABASE_URL` vide pour rester sur SQLite.

```sh
python -m pip install -r requirements.txt
python app.py
```

1. Ouvrir `http://127.0.0.1:5000/login`, créer un compte de test.
2. Ouvrir **BET PRONO AI**, vérifier le bloc **Bilan des pronostics**.
3. Choisir une date avec de la Ligue 1, cliquer sur **Chercher les matchs**, puis choisir
   **Ligue 1** dans le menu Compétition : seuls ses matchs restent.
4. Ouvrir un match à venir : vérifier le modèle statistique et le tableau de forme.
5. Avec `GEMINI_API_KEY`, vérifier le pronostic IA ; il apparaît ensuite en attente
   dans le bilan, puis vérifié dès 2 h après le coup d'envoi (puis toutes les 30 min).

## Tests automatisés

```sh
python -m unittest discover -s tests -v
```

Les tests n'appellent ni 365Scores ni Gemini : réponses simulées et base SQLite jetable.
