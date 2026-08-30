"""
Compact Card Game — decision surface (interface layer).

Pure functions that answer "what is legal right now?".
They never mutate state. A UI, AI, or network layer picks one of the
returned options and hands it to the corresponding do_* function in
engine.py. The engine independently re-validates at the mutation boundary.
"""

from typing import List, Optional, Tuple, Union
from model import (
    Card, CardType, Mode, UnitState, ResourcePileCard, Player, GameState,
)
import engine


TributeChoice = List[Tuple[str, Union[UnitState, ResourcePileCard]]]


def _all_tribute_combinations(
    player: Player,
    cost: int,
) -> List[TributeChoice]:
    """
    Generate every combination of distinct physical objects whose values
    sum exactly to `cost`.

    Field units contribute their level.
    Resource Pile cards contribute ResourcePileCard.value (always 1).
    Each physical object may be selected at most once.
    """
    if cost == 0:
        return [[]]

    candidates: List[Tuple[str, Union[UnitState, ResourcePileCard], int]] = []

    for unit in player.field_units():
        candidates.append(("field", unit, unit.card.level))

    for rp_card in player.resource_pile:
        candidates.append(("resource", rp_card, rp_card.value))

    results: List[TributeChoice] = []

    def search(start: int, remaining: int, chosen: TributeChoice) -> None:
        if remaining == 0:
            results.append(list(chosen))
            return
        if remaining < 0:
            return

        for i in range(start, len(candidates)):
            zone, obj, value = candidates[i]
            if value > remaining:
                continue
            chosen.append((zone, obj))
            search(i + 1, remaining - value, chosen)
            chosen.pop()

    search(0, cost, [])
    return results


def legal_normal_summons(player: Player) -> List[Tuple[Card, List[TributeChoice]]]:
    results = []
    hand_units = [c for c in player.hand if c.card_type == CardType.UNIT]

    for card in hand_units:
        cost = engine.tribute_cost(card.level)
        raw = _all_tribute_combinations(player, cost)
        valid = [t for t in raw if engine.can_normal_summon(player, card, t)]
        if valid:
            results.append((card, valid))
    return results


def legal_level_ups(player: Player) -> List[Tuple[UnitState, Card]]:
    results = []
    for material in player.field_units():
        for card in player.hand:
            if engine.can_level_up(player, material, card):
                results.append((material, card))
    return results


def legal_mode_switches(player: Player) -> List[UnitState]:
    return [
        u for u in player.field_units()
        if engine.can_switch_mode(player, u)
    ]


def legal_attacks(state: GameState) -> List[Tuple[UnitState, Optional[UnitState]]]:
    """
    Returns list of (attacker, defender).
    defender=None means a legal direct attack.

    Mirrors the engine's mandatory Defense Mode taunt rule.
    """
    attacker_player = state.active
    defender_player = state.opponent
    results = []

    attackers = [u for u in attacker_player.field_units() if u.mode == Mode.ATTACK]
    if not attackers:
        return results

    opponent_units = defender_player.field_units()
    defense_units = [u for u in opponent_units if u.mode == Mode.DEFENSE]

    if not opponent_units:
        for atk in attackers:
            results.append((atk, None))
        return results

    if defense_units:
        for atk in attackers:
            for defn in defense_units:
                results.append((atk, defn))
    else:
        for atk in attackers:
            for defn in opponent_units:
                results.append((atk, defn))

    return results
