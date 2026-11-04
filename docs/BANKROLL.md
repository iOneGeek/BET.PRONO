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

Les captures fournies montrent 421,92 € contre 330 €, soit 91,92 € d'écart.
Les mises visibles, 5 € et 20,29 €, totalisent 25,29 €. Si ce sont les seules
mises en cours enregistrées, leur déduction donne 396,63 € : il reste 66,63 €
à rapprocher avec l'historique. La correction ne force pas artificiellement
le solde à 330 €. Utiliser « Exporter mes données » pour examiner les opérations.

## Validation

`python -m unittest discover -s tests -v` : base SQLite temporaire, solde admin,
transitions en cours/perdu/remboursé/gagné, suppression et isolation des comptes.

`python tests/browser_bankroll.py` (Playwright, `BROWSER_CHANNEL=msedge` si besoin) :
solde, bénéfice inchangé, report antérieur et fin des deux graphiques pour toutes
les périodes, changements de statut réels via Flask, affichage 320/390/1440 px
et courbe sans opération. Données fictives uniquement, aucun accès au compte réel.
