# Analyse intégrée au match

La sélection d'une rencontre dans BET PRONO AI affiche les statistiques, puis
prépare automatiquement une synthèse dans la même fiche. Il n'y a aucun bouton
supplémentaire et aucun nom de fournisseur de modèle dans l'interface.
La mention « Synthèse générée par IA » distingue le texte généré des données source.

Les statistiques fonctionnent même sans clé, en cas de panne ou de quota atteint.
Pour un match programmé, la fiche charge jusqu'à cinq résultats
récents vérifiés de chaque équipe et les transmet à l'analyse. Les dates et scores
apparaissent dans la fiche et les références de la synthèse. En l'absence de
statistiques et de résultats récents exploitables, aucune génération n'est demandée.
Avant le début du match, trois résultats vérifiés par équipe permettent de demander
une estimation du score. Le vainqueur découle de ce score (temps réglementaire au hockey).
Le buteur est facultatif et doit appartenir aux candidats identifiés par la source.

## Activer dans Render

1. Créer une clé dans [Google AI Studio](https://aistudio.google.com/apikey), si nécessaire.
2. Dans le service BET.PRONO, ouvrir **Environment** et ajouter `GEMINI_API_KEY`
   avec la clé comme valeur. Ne pas la mettre sur GitHub ni dans le chat.
3. Vérifier les variables suivantes :
   - `GEMINI_MODEL=gemini-3.8-flash` (valeur par défaut, modèle configurable).
   - `AUTO_ANALYSIS_ENABLED=1` (valeur par défaut).
   - `SPORTS_DATA_ENABLED=1` pour la consultation des données.
4. Sauvegarder la configuration puis, après intégration de cette branche,
   déployer la version correspondante selon le processus habituel.
5. Choisir une rencontre comportant des statistiques ou des résultats récents. La section « Analyse du match »
   doit afficher une synthèse, les données citées et les limites, sans clic supplémentaire.

`AUTO_ANALYSIS_ENABLED=0` désactive uniquement la synthèse. L’application distingue
une clé absente, un accès refusé, un quota atteint, un modèle inaccessible,
une requête refusée, un délai dépassé et une réponse invalide ou tronquée.
Les variables optionnelles utilisent les valeurs par défaut indiquées plus haut.
Les journaux Render indiquent `Automatic match analysis failed` suivi d’un code fixe.
Le code est également retourné dans `reason` et conservé pendant la suspension
des appels après erreur. Seul ce code est journalisé, sans clé, corps de réponse,
prompt ni texte d’exception. Un refus HTTP 400 indique une requête refusée et
nécessite de vérifier la clé et la compatibilité du modèle pour préciser la cause.
La disponibilité du modèle et les quotas dépendent du compte Google utilisé.
Aucune souscription ou activation de facturation n'est effectuée par ce code.

## Traitement côté serveur

Le navigateur transmet uniquement l'identifiant du match dans l'URL et l'empreinte
du jeu de données affiché (`snapshot_id`). Le serveur recharge ses données 365Scores
et vérifie l'empreinte avant de demander l'analyse. Si les données ont changé,
l'utilisateur est invité à sélectionner de nouveau la rencontre. Les textes et
chiffres sportifs ne sont pas acceptés depuis le navigateur.

`POST /api/ai/matches/<id>/analysis` requiert la session existante, un compte non
banni et un corps JSON contenant seulement `snapshot_id`. La réponse peut être
`ready`, `unavailable`, `insufficient_data` ou `outdated`. Elle est `no-store`.

La requête envoyée à Google contient uniquement les données publiques normalisées
du match et les statistiques identifiées. Aucun compte utilisateur, pari, bankroll,
cookie ou capture d'écran n'est transmis. La clé est placée dans l'en-tête
`x-goog-api-key`, jamais dans une URL, un message d'erreur ou la réponse au navigateur.

Le modèle reçoit une instruction de synthèse descriptive en français, sans outil
de recherche ou d'exécution de code. Le pronostic éventuel figure dans un champ distinct. Les champs des
données sont explicitement traités comme des informations, jamais des instructions.
L'appel utilise l'API REST `generateContent`, une sortie JSON structurée et un
plafond de 4 096 jetons de sortie avec niveau de raisonnement LOW.

## Contrôles et limites

- Un résumé court sans chiffres et une à trois observations, chacune liée à un
  ou deux faits du match. Les références affichées sont reconstruites par le serveur.
- Schéma, tailles, identifiants de faits et chiffres des observations contrôlés
  côté serveur. HTML, liens et certaines formulations de prédiction sont refusés.
- Ces contrôles ne prouvent **pas** la justesse sémantique du texte : une lecture
  incorrecte des données reste possible. L'interface rappelle de vérifier les faits.
- Le score proposé cite au moins un résultat de chaque équipe. Un buteur proposé cite
  aussi sa fiche et son équipe doit marquer dans le scénario. La fiabilité des estimations reste à évaluer.
- Une seule génération simultanée par processus. Les autres demandes reçoivent
  un état d'indisponibilité temporaire, sans attente bloquant les statistiques.
- Cache partagé des synthèses : 10 minutes, 128 entrées, lié au modèle, à la version
  de l'instruction et au contenu exact du match. Une réponse en cache ne consomme
  pas un nouvel appel au modèle.
- 6 nouvelles générations par utilisateur/heure et 30 par processus/heure.
  Ces limites sont locales et repartent à zéro au redémarrage ; ce n'est pas un
  plafond de facturation garanti. Ajouter un limiteur partagé avant plusieurs instances.
- Délais connexion/lecture 3,05/18 secondes, budget contrôlé pendant la lecture
  de 22 secondes, 128 Kio maximum pour la réponse. Pas de redirection ou de nouvelle
  tentative automatique. Une panne, réponse tronquée/refusée ou invalide suspend
  les appels pendant 60 secondes et ne laisse apparaître aucun texte généré partiel.
- Le navigateur abandonne une analyse obsolète lors d'un changement de rencontre
  ou de recherche. Une erreur d'analyse ne masque jamais les données sportives.

## Vérifications et activation réelle

Les tests automatisés utilisent des réponses de modèle synthétiques, sans clé
réelle ni frais. Ils couvrent le déclenchement automatique, la correspondance avec
le match affiché, les données insuffisantes, la clé absente, les erreurs/quota,
les réponses invalides, les références inconnues, les chiffres non sourcés,
le cache et les réponses tardives lors d'un changement de match.

```sh
python -m unittest discover -s tests -v
python tests/browser_ai.py
```

Pour vérifier le pronostic avec le compte Google configuré sur Render, sélectionner
un match à venir disposant d'au moins trois résultats récents de chaque côté.

Références consultées : [modèle Gemini 3.8 Flash](https://aistudio.google.com/docs/models/gemini-3.8-flash),
[API generateContent](https://aistudio.google.com/api-reference/generate-content),
[sorties structurées](https://aistudio.google.com/docs/structured-output),
[clés API](https://aistudio.google.com/docs/api-key).
