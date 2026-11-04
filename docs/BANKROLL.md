# Solde disponible

Le montant affiché correspond au solde disponible calculé sur tout l'historique :

`bankroll initiale + bénéfice net des paris réglés − retraits − mises en cours`.

Un pari gagné contribue `mise × (cote − 1) + bonus`, un perdu `−mise`,
un remboursé zéro. Un pari en cours immobilise sa mise, sans créditer de gain
potentiel ni de bonus. Le changement de statut remplace cette contribution :
un pari qui passe d'en cours à perdu ne retire pas une deuxième mise.

Les filtres 7/30/90 jours ne changent pas le solde actuel. Chaque courbe reprend
le solde des opérations précédant la période ; son dernier point correspond
au montant affiché. Les courbes utilisent les statuts actuels aux dates saisies,
et non un historique horodaté des règlements (non conservé dans le modèle actuel).
Le détail dépliable sépare résultat net total, retraits et mises immobilisées.
Le bénéfice et le ROI restent calculés sur les paris réglés de la période.
Les vues administrateur utilisent également le solde disponible.

## Comparer avec le bookmaker

Les calculs ne modifient aucun pari enregistré et ne synchronisent pas le compte
bookmaker. Vérifier que le périmètre est le même (compte, sports/poker), les
statuts, mises, cotes, bonus réellement crédités, retraits et capital de départ.
Les dépôts supplémentaires, freebets et cashouts n'ont pas de traitement dédié.
L'arrondi de chaque règlement par le bookmaker peut aussi différer du calcul
actuel, qui conserve la précision puis arrondit les montants affichés.

## Gains réellement crédités

Le champ facultatif `p` / `payout` représente le retour total crédité, mise et
bonus compris. Lorsqu’il est renseigné sur un pari réglé (gagné, perdu ou
remboursé), son bénéfice est `payout − mise`, sans ajouter à nouveau le bonus.
Zéro est une valeur valide. `null` conserve le calcul historique depuis la cote.
Les cotes et bonus saisis restent conservés. Un changement de statut efface
l’ancien montant, sauf si un nouveau montant est explicitement fourni.
Le formulaire « Modifier le pari », l’export, l’import, les graphiques et les
vues administrateur utilisent ce champ. La migration ajoute une colonne nullable
sans modifier les paris existants (SQLite/PostgreSQL).

## Rapprochement sans remplacement de l’historique

Dans Mes paris, en bas, « Rapprocher un historique vérifié » accepte un JSON :
`version: 1`, `initial_bankroll`, `before` (export intégral avec identifiants),
`updates` (objets avec `id` et `s` et/ou `p`) et `additions` (nouveaux paris).
Les références bookmaker et justificatifs doivent être conservés dans un audit
privé ; le fichier de rapprochement doit être établi après vérification des
correspondances. Il ne devine pas les paris manquants et ne synchronise pas Winamax.

L’aperçu affiche chaque modification, les ajouts et le solde résultant. Le bouton
de sauvegarde télécharge `{bets, initial_bankroll}` avant d’activer l’application.
Conserver cette sauvegarde. Elle contient les données antérieures ; une restauration
par l’import historique remplace les paris et leurs identifiants et n’est donc pas
un retour arrière adapté aux pronostics suivis. Préférer un correctif inverse.

`POST /api/bets/reconcile` est authentifié, ne supprime aucune ligne et conserve
les identifiants et liens de suivi. Il vérifie l’ensemble de l’état initial sous
verrou, puis applique toutes les écritures dans une transaction. Un fichier périmé
ou déjà appliqué est refusé (409) ; une erreur annule toutes les écritures. La mise
d’un pronostic suivi ne peut pas être changée par ce rapprochement. Sans
`apply: true`, aucune modification n’est effectuée. Les fichiers et montants
personnels ne sont pas à déposer dans le dépôt public.

## Validation

`python -m unittest discover -s tests -v` : base SQLite temporaire, solde admin,
transitions en cours/perdu/remboursé/gagné, suppression et isolation des comptes.

`python tests/browser_bankroll.py` (Playwright, `BROWSER_CHANNEL=msedge` si besoin) :
solde, bénéfice inchangé, report antérieur et fin des deux graphiques pour toutes
les périodes, changements de statut réels via Flask, affichage 320/390/1440 px
et courbe sans opération. Données fictives uniquement, aucun accès au compte réel.

Les régressions couvrent aussi la migration répétée, les gains exacts et nuls,
l’export/import, la conservation des suivis, l’aperçu sans écriture, l’isolement
des comptes, l’échec partiel annulé et le refus des fichiers périmés ou rejoués.
Le test navigateur vérifie le téléchargement de la sauvegarde puis l’application.
PostgreSQL utilise la même logique mais n’a pas été testé sur une base réelle.
