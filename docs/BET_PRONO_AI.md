# BET PRONO AI — Bêta (V2.3.9)

L'onglet **BET PRONO AI** (sur mobile : **AI · Bêta**) affiche des rencontres de
football et de hockey sur glace issues de 365Scores, une fiche par match, une analyse
générée par Gemini, un modèle statistique et le bilan réel des pronostics.

Voir aussi : [connecteur 365Scores](365SCORES.md) et
[configuration de l'analyse Gemini](AUTO_ANALYSIS.md).

## Ce que voit l'utilisateur

1. **Bilan des pronostics** (haut de l'onglet) : pourcentage de bons vainqueurs,
   de scores exacts et de buteurs trouvés par l'IA, et de bons vainqueurs du modèle
   statistique, avec les derniers pronostics vérifiés.
2. **Recherche** : sport, date (±30 jours), équipe ou compétition, et menu
   **Compétition** rempli avec les compétitions du jour. Ligue 1, Ligue 2,
   Coupe de France, Ligue des champions, Ligue Europa, Ligue Europa Conférence et
   Ligue des nations apparaissent en tête (« À la une »), puis les autres par popularité.
3. **Fiche du match** :
   - pronostic IA (vainqueur, score estimé, buteur possible) avant le coup d'envoi ;
   - **modèle statistique** : probabilités victoire / nul / défaite, buts attendus,
     score le plus probable, plus de 2,5 buts (5,5 au hockey), les deux équipes marquent ;
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
Modèle de Poisson volontairement simple et lisible : moyennes de buts marqués et
encaissés sur les résultats récents (temps réglementaire au hockey), rapprochées d'une
valeur de référence quand l'échantillon est petit, avantage du terrain léger. Il exige
trois résultats vérifiés par équipe. C'est un point de repère, pas une garantie : sa
réussite réelle est mesurée dans le bilan.

### Analyse IA (`match_analysis.py`)
- Gemini reçoit les faits vérifiés : statistiques, résultats récents, forme calculée,
  confrontations directes et buts attendus du modèle. Il doit citer ses sources et
  rester cohérent avec le modèle.
- Jusqu'à 3 analyses en parallèle ; une analyse déjà prête est toujours servie, même
  quand d'autres sont en cours.
- Une réponse mal formée, refusée ou tronquée est **réessayée une fois**. Elle ne bloque
  pas les autres utilisateurs et n'est pas décomptée du quota de l'utilisateur.
- Seules les vraies pannes (quota, clé refusée, modèle introuvable, service indisponible)
  mettent l'analyse en pause pour tous, de 45 s à 5 min selon le cas.
- Les analyses validées sont gardées **6 h en base** (`ai_analysis_cache`) : un
  redémarrage du serveur sur Render ne relance pas Gemini.

### Bilan des pronostics (`app.py`)
- Chaque pronostic IA est enregistré dans `ai_predictions` (dernier pronostic avant
  le coup d'envoi), avec l'estimation du modèle.
- `GET /api/ai/track-record` vérifie jusqu'à 3 matchs terminés depuis plus de 3 h à
  chaque consultation, puis renvoie les taux de réussite.
- Hockey : comparé au temps réglementaire. Football avec prolongation : seul le match
  nul après 90 minutes est compté (score exact inconnu). Un match sans résultat après
  2 jours est écarté.

Les tables sont créées automatiquement au démarrage (SQLite en local, PostgreSQL/Neon
en production). Aucune migration manuelle.

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
   dans le bilan, puis vérifié 3 h après la fin du match.

## Tests automatisés

```sh
python -m unittest discover -s tests -v
```

Les tests n'appellent ni 365Scores ni Gemini : réponses simulées et base SQLite jetable.
