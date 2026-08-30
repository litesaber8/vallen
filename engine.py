"""
Compact Card Game — rules engine.
This module only answers "what is legal / what happened". It never decides
WHY an action is taken — that's the heuristic layer's job (heuristic.py).
"""

from typing import Optional
from model import (
    Card, CardType, Mode, UnitState, ResourcePileCard, Player,
    GameState, Phase, InvariantError,
)


def assert_invariants(state: GameState):
    seen_ids = set()
    for p in state.players:
        for u in p.field_units():
            if id(u) in seen_ids:
                raise InvariantError(f"Unit {u.card.name} exists in more than one zone")
            seen_ids.add(id(u))
            if u.current_hp > u.max_hp:
                raise InvariantError(
                    f"{u.card.name} has {u.current_hp} HP but max is {u.max_hp}"
                )
            if u.current_hp < 0:
                raise InvariantError(f"{u.card.name} has negative HP")
            if u.owner is not p:
                raise InvariantError(f"{u.card.name} sits in {p.name}'s zone but is owned by {u.owner.name}")


def assert_end_of_active_turn_recovery(player: Player):
    for u in player.field_units():
        if u.current_hp != u.max_hp:
            raise InvariantError(
                f"{u.card.name} should be fully healed at start of {player.name}'s turn"
            )


def tribute_cost(level: int) -> int:
    return max(0, level - 1)


def can_normal_summon(player: Player, card: Card, chosen_tribute) -> bool:
    total_value = 0
    zones_freed_by_tribute = 0
    for kind, item in chosen_tribute:
        if kind == "field":
            total_value += item.card.level
            zones_freed_by_tribute += 1
        elif kind == "resource":
            total_value += item.value
    if total_value != tribute_cost(card.level):
        return False
    open_zones_now = sum(1 for z in player.unit_zones if z is None)
    return (open_zones_now + zones_freed_by_tribute) > 0


def do_normal_summon(state: GameState, player: Player, card: Card, chosen_tribute):
    if not can_normal_summon(player, card, chosen_tribute):
        raise InvariantError(f"Illegal Normal Summon of {card.name}")

    zone_freed = None
    for kind, item in chosen_tribute:
        if kind == "field":
            zone_freed = player.unit_zones.index(item)
            player.unit_zones[zone_freed] = None
            player.discard_pile.append(item.card)
            state.emit(f"  Tribute: {item.card.name} -> Discard Pile")
        elif kind == "resource":
            player.resource_pile.remove(item)
            player.discard_pile.append(item.card)
            state.emit(f"  Tribute (from Resource): {item.card.name} -> Discard Pile")

    zone = zone_freed if zone_freed is not None else player.empty_zone_index()
    new_unit = UnitState(card=card, owner=player, current_hp=card.base_hp, mode=Mode.ATTACK)
    player.unit_zones[zone] = new_unit
    player.hand.remove(card)
    state.emit(f"  Normal Summon: {card.name} (LV{card.level}) -> zone {zone}")
    assert_invariants(state)
    return new_unit


def can_level_up(player: Player, material: UnitState, upgrade_card: Card) -> bool:
    return (
        material in player.field_units()
        and upgrade_card.level == material.card.level + 1
    )


def do_level_up(state: GameState, player: Player, material: UnitState, upgrade_card: Card):
    if not can_level_up(player, material, upgrade_card):
        raise InvariantError(f"Illegal Level-Up into {upgrade_card.name}")
    zone = player.unit_zones.index(material)
    new_unit = UnitState(
        card=upgrade_card, owner=player, current_hp=upgrade_card.base_hp,
        mode=Mode.ATTACK, level_up_unlocked=True, built_from=material.card,
    )
    player.unit_zones[zone] = new_unit
    player.hand.remove(upgrade_card)
    player.discard_pile.append(material.card)
    state.emit(f"  Level-Up Summon: {material.card.name} -> Discard Pile; "
                f"{upgrade_card.name} enters with ability unlocked")
    assert_invariants(state)
    return new_unit


def can_switch_mode(player: Player, unit: UnitState) -> bool:
    return unit in player.field_units()


def switch_mode(state: GameState, player: Player, unit: UnitState) -> None:
    if not can_switch_mode(player, unit):
        raise InvariantError(f"Cannot switch mode of {unit.card.name}")
    unit.mode = Mode.DEFENSE if unit.mode == Mode.ATTACK else Mode.ATTACK
    state.emit(f"  {unit.card.name} switches to {unit.mode.name}")
    assert_invariants(state)


def _validate_battle_target(
    state: GameState,
    attacker: UnitState,
    defender_player: Player,
    defender: Optional[UnitState],
) -> None:
    """Enforce attacker legality + mandatory Defense Mode taunt at the
    mutation boundary. Interface.py also filters these cases, but the
    engine must reject illegal calls even if a caller bypasses the
    interface."""
    active = state.active

    if attacker not in active.field_units():
        raise InvariantError("Attacker is not on the active player's field.")
    if attacker.mode != Mode.ATTACK:
        raise InvariantError("Only Attack Mode units can initiate attacks.")

    if defender_player is not state.opponent:
        raise InvariantError("defender_player is not the opposing player.")

    opponent_units = defender_player.field_units()
    defense_units = [u for u in opponent_units if u.mode == Mode.DEFENSE]

    if not opponent_units:
        if defender is not None:
            raise InvariantError("Cannot target a unit when opponent has no units.")
        return

    if defense_units:
        if defender is None:
            raise InvariantError("Defense Mode unit must be attacked first (taunt).")
        if defender not in defense_units:
            raise InvariantError(
                "A Defense Mode unit must be targeted before other units or LP."
            )
        return

    if defender is None:
        raise InvariantError("Cannot directly attack while opponent has units.")
    if defender not in opponent_units:
        raise InvariantError("Defender is not an opposing unit.")


def resolve_battle(
    state: GameState,
    attacker: UnitState,
    defender_player: Player,
    defender: Optional[UnitState] = None,
):
    """defender=None means a direct attack.
    Returns a list of (player, Card) for every unit destroyed this exchange.
    """
    _validate_battle_target(state, attacker, defender_player, defender)

    if defender is None:
        defender_player.lp -= attacker.ap
        state.emit(f"  {attacker.card.name} attacks directly for {attacker.ap} -> "
                    f"{defender_player.name} LP: {defender_player.lp}")
        return []

    if attacker.mode == Mode.ATTACK and defender.mode == Mode.ATTACK:
        defender.current_hp -= attacker.ap
        attacker.current_hp -= defender.ap
        state.emit(f"  {attacker.card.name} (ATK) vs {defender.card.name} (ATK): "
                    f"simultaneous damage, {defender.card.name} takes {attacker.ap}, "
                    f"{attacker.card.name} takes {defender.ap}")
    elif defender.mode == Mode.DEFENSE:
        defender.current_hp -= attacker.ap
        state.emit(f"  {attacker.card.name} (ATK) vs {defender.card.name} (DEF): "
                    f"no retaliation, {defender.card.name} takes {attacker.ap}")
    else:
        raise InvariantError("Unhandled mode combination in battle resolution")

    return _resolve_destructions(state, attacker.owner, defender_player)


def _resolve_destructions(state: GameState, attacker_owner: Player, defender_owner: Player):
    destroyed = []
    for player in (attacker_owner, defender_owner):
        for i, u in enumerate(player.unit_zones):
            if u is not None and u.current_hp <= 0:
                if _has_sacrifice_denial(player, u):
                    u.current_hp = 0
                    state.emit(f"  {u.card.name} would be destroyed but sacrifice_denial holds "
                               f"(another Fallen Holy unit is on field) — stays at 0 HP, damaged")
                    continue
                player.unit_zones[i] = None
                player.resource_pile.append(ResourcePileCard(card=u.card))
                state.emit(f"  {u.card.name} destroyed -> {player.name}'s Resource Pile")
                state.emit(_on_destruction_hint(u.card))
                destroyed.append((player, u.card))
    assert_invariants(state)
    return destroyed


def _has_sacrifice_denial(player: Player, unit: UnitState) -> bool:
    if "sacrifice_denial" not in unit.card.abilities:
        return False
    others = [o for o in player.field_units() if o is not unit and o.card.faction == unit.card.faction]
    return len(others) > 0


def _on_destruction_hint(destroyed_card: Card) -> str:
    if "on_destruction_free_summon" in destroyed_card.abilities:
        return "  On Destruction: owner may free-summon a LV1 from Resource Pile"
    if "on_destruction_reclaim_discard" in destroyed_card.abilities:
        return "  On Destruction: owner may reclaim 1 card from Discard -> Resource Pile"
    return "  (no On Destruction ability)"


def recover_active_player_units(state: GameState):
    player = state.active
    for u in player.field_units():
        u.current_hp = u.max_hp
    assert_end_of_active_turn_recovery(player)


def do_reclaim_from_discard(state: GameState, player: Player, card: Card):
    if card not in player.discard_pile:
        raise InvariantError(f"Cannot reclaim {card.name}: not in {player.name}'s Discard Pile")
    player.discard_pile.remove(card)
    player.resource_pile.append(ResourcePileCard(card=card))
    state.emit(f"  {player.name} reclaims {card.name}: Discard -> Resource Pile")
    assert_invariants(state)
