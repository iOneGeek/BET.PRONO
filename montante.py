"""Montante par paliers : calcul pur (sans base de données), partagé par l'API et les tests.

Règles :
- palier 1 : mise de départ ; retour = mise × cote (annulé : retour = mise) ;
- après un palier gagné, le retrait éventuel est mis de côté et la mise suivante = retour − retrait ;
- un palier perdu arrête la montante ; les paliers non joués sont une simulation (si tout est gagné).
"""

from decimal import ROUND_HALF_UP, Decimal

MIN_STEPS, MAX_STEPS = 3, 30
MIN_ODDS, MAX_ODDS = 1.01, 20.0
RESULTS = ('pending', 'won', 'lost', 'void')


CENT = Decimal('0.01')


def _cents(value):
    """Montant arrondi au centime, comme un bookmaker (arrondi commercial)."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _money(value):
    return float(_cents(value))


def compute(montante, steps):
    """Tableau complet d'une montante : mises, retours, retraits, palier en cours et totaux."""
    stake = _cents(montante['start_stake'])
    rows = []
    current = None
    stopped_at = None
    banked = Decimal(0)   # Retraits réellement encaissés (paliers gagnés).
    planned = Decimal(0)  # Retraits prévus, y compris ceux des paliers à venir.
    for step in sorted(steps, key=lambda s: s['step_no']):
        odds = float(step['odds'])
        result = step['result'] if step['result'] in RESULTS else 'pending'
        withdrawal = _cents(step['withdrawal'] or 0)
        if stopped_at is not None:
            state = 'off'
        elif result == 'pending':
            state = 'current' if current is None else 'simulation'
            if current is None:
                current = step['step_no']
        else:
            state = result
        played_back = stake if result == 'void' else _cents(stake * Decimal(str(odds)))
        withdrawal = min(withdrawal, played_back) if state != 'off' else withdrawal
        row = {'step_no': step['step_no'], 'stake': _money(stake), 'odds': odds, 'return': _money(played_back),
               'withdrawal': _money(withdrawal), 'pick': step.get('pick') or '', 'game_id': step.get('game_id'),
               'result': result, 'state': state, 'settled_at': step.get('settled_at')}
        rows.append(row)
        if state == 'lost':
            stopped_at = step['step_no']
            row['withdrawal'] = 0.0
            continue
        if state == 'off':
            row['stake'] = row['return'] = None
            continue
        planned += withdrawal
        if state in ('won', 'void'):
            banked += withdrawal
        stake = played_back - withdrawal
    total = len(rows)
    won = sum(1 for row in rows if row['state'] in ('won', 'void'))
    last = rows[-1] if rows else None
    status = montante.get('status') or 'active'
    if status == 'active' and stopped_at is not None:
        status = 'lost'
    elif status == 'active' and rows and current is None:
        status = 'won'
    in_play = next((row for row in rows if row['state'] == 'current'), None)
    return {
        'id': montante.get('id'), 'title': montante.get('title') or 'Les paliers', 'status': status,
        'start_stake': _money(float(montante['start_stake'])), 'default_odds': float(montante.get('default_odds') or 1.5),
        'steps': rows, 'total_steps': total, 'won_steps': won, 'current_step': current, 'lost_step': stopped_at,
        'current_stake': in_play['stake'] if in_play else None,
        'final_return': last['return'] if last and stopped_at is None else None,
        'withdrawals_banked': _money(banked), 'withdrawals_planned': _money(planned),
        'created_at': montante.get('created_at'), 'ended_at': montante.get('ended_at'),
    }


def build_steps(count, default_odds, odds=None, withdrawals=None):
    """Paliers initiaux d'une nouvelle montante, avec cotes et retraits particuliers éventuels."""
    odds = odds or {}
    withdrawals = withdrawals or {}
    return [{'step_no': n, 'odds': float(odds.get(n, default_odds)), 'withdrawal': float(withdrawals.get(n, 0)),
             'pick': '', 'game_id': None, 'result': 'pending', 'settled_at': None} for n in range(1, count + 1)]


def valid_odds(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and MIN_ODDS <= value <= MAX_ODDS
