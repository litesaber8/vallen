"""
Vallen — Heuristic Agent (Canonical Action Producer).

Deterministic policy that consumes only the legality surface exposed by
interface.py. Never reconstructs targets, never calls engine mutations,
never inspects or mutates pending_event directly.

Pre-Phase 4B.
"""

from typing import Any, Dict, List, Optional, Tuple
from model import GameState, Player, UnitState, Mode, Card, CardType, SupportType
import interface


def choose_reclaim_from_discard(player: Player):
    """Legacy stub retained for existing reclaim tests."""
    if player.discard_pile:
        return player.discard_pile[0]
    return None


def _stable_card_key(card: Card) -> str:
    return card.id


def _stable_unit_key(unit: UnitState) -> str:
    return unit.uid


def _choose_level_up(player: Player) -> Optional[Dict[str, Any]]:
    """Prefer higher resulting level; stable tie-break by material uid then card id."""
    legal = interface.legal_level_ups(player)
    if not legal:
        return None
    # Sort: prefer higher upgrade level, then stable ids
    legal_sorted = sorted(
        legal,
        key=lambda pair: (-pair[1].level, _stable_unit_key(pair[0]), _stable_card_key(pair[1])),
    )
    material, card = legal_sorted[0]
    return {"action": "level_up", "unit_id": material.uid, "card_id": card.id}


def _choose_normal_summon(player: Player) -> Optional[Dict[str, Any]]:
    """Prefer higher level; stable tie-break by card id."""
    legal = interface.legal_normal_summons(player)
    if not legal:
        return None
    legal_sorted = sorted(
        legal,
        key=lambda pair: (-pair[0].level, _stable_card_key(pair[0])),
    )
    card, _tributes = legal_sorted[0]
    return {"action": "normal_summon", "card_id": card.id}


def _choose_support(player: Player) -> Optional[Dict[str, Any]]:
    """
    Prefer Field > Equip > Normal when available.
    Uses only targets enumerated by interface.
    """
    # Field (no target)
    fields = interface.legal_fields(player)
    if fields:
        fields_sorted = sorted(fields, key=_stable_card_key)
        return {"action": "field_support", "card_id": fields_sorted[0].id}

    # Equip (card, unit)
    equips = interface.legal_equips(player)
    if equips:
        equips_sorted = sorted(
            equips,
            key=lambda pair: (_stable_card_key(pair[0]), _stable_unit_key(pair[1])),
        )
        card, unit = equips_sorted[0]
        return {"action": "equip_support", "card_id": card.id, "unit_id": unit.uid}

    # Normal (card, Optional[target])
    normals = interface.legal_normal_supports(player)
    if normals:
        normals_sorted = sorted(
            normals,
            key=lambda pair: (
                _stable_card_key(pair[0]),
                pair[1].uid if pair[1] is not None else "",
            ),
        )
        card, target = normals_sorted[0]
        action: Dict[str, Any] = {"action": "normal_support", "card_id": card.id}
        if target is not None:
            action["target"] = target.uid
        return action

    return None


def _choose_mode_switch(player: Player) -> Optional[Dict[str, Any]]:
    """
    Switch a unit to Defense if it is low HP relative to max, else prefer
    Attack Mode for units that can still act. Deterministic selection.
    """
    legal = interface.legal_mode_switches(player)
    if not legal:
        return None

    def score(u: UnitState) -> Tuple[int, str]:
        # Prefer switching Attack->Defense when HP is low (fragile).
        # Prefer Defense->Attack when healthy so the unit can attack later.
        if u.mode == Mode.ATTACK and u.current_hp <= max(1, u.max_hp // 2):
            return (0, _stable_unit_key(u))  # high priority switch to DEF
        if u.mode == Mode.DEFENSE and u.current_hp > u.max_hp // 2:
            return (1, _stable_unit_key(u))  # switch to ATK
        # Otherwise lower priority; still legal, pick stably
        return (2, _stable_unit_key(u))

    legal_sorted = sorted(legal, key=score)
    unit = legal_sorted[0]
    # Only emit a switch when the simple policy considers it beneficial
    # (score 0 or 1). Score 2 means "no strong reason" — skip.
    if score(unit)[0] >= 2:
        return None
    return {"action": "switch_mode", "unit_id": unit.uid}


def _choose_attack(state: GameState) -> Optional[Dict[str, Any]]:
    """
    Prefer attacks that can destroy (or chip) higher-AP/HP threats.
    Direct attacks when legal. Stable tie-break by attacker/defender uid.
    """
    legal = interface.legal_attacks(state)
    if not legal:
        return None

    def score(pair: Tuple[UnitState, Optional[UnitState]]) -> Tuple:
        atk, defn = pair
        if defn is None:
            # Direct attack: prefer higher AP
            return (0, -atk.ap, _stable_unit_key(atk), "")
        # Prefer lethal or high damage; prefer higher attacker AP
        lethal = 0 if atk.ap >= defn.current_hp else 1
        return (1, lethal, -atk.ap, _stable_unit_key(atk), _stable_unit_key(defn))

    legal_sorted = sorted(legal, key=score)
    atk, defn = legal_sorted[0]
    return {
        "action": "attack",
        "attacker_id": atk.uid,
        "defender_id": defn.uid if defn is not None else None,
    }


def _choose_response(state: GameState) -> Dict[str, Any]:
    """
    Response-window policy.
    Consumes only interface.legal_counters. Never inspects pending_event.
    """
    counters = interface.legal_counters(state)
    if not counters:
        return {"action": "pass_response"}

    # Deterministic net-positive heuristic:
    # For the current fixture set every Counter is eligible and has positive
    # value (it cancels the opponent's pending action). Always counter when
    # a legal Counter exists. Stable choice by card id.
    counters_sorted = sorted(counters, key=lambda pair: _stable_card_key(pair[0]))
    card, _event = counters_sorted[0]
    # Simple net-positive: always positive for current rules (cancel opponent event).
    # Future: evaluate card.abilities / event type for true net value.
    return {"action": "counter_support", "card_id": card.id}


def choose_action(state: GameState) -> Dict[str, Any]:
    """
    Primary entry point. Returns one Canonical Action dict.

    Priority (Main/Battle):
      1. Level-Up
      2. Normal Summon
      3. Support (Field > Equip > Normal)
      4. Beneficial mode switch
      5. Attack
      6. End Phase

    Response window is handled first when the interface exposes response choices
    (i.e. when legal_counters is non-empty or pending forces response-only play).
    """
    # Response window: if any Counter is legal, or more generally when the
    # interface would only expose response actions. We detect the response
    # context by the presence of legal counters OR by checking whether
    # normal actions are empty while a response is possible.
    # Strict rule: never read pending_event. Use only interface results.
    counters = interface.legal_counters(state)
    if counters:
        return _choose_response(state)

    # If no counters but we are in a response-only situation, the only legal
    # move exposed by a complete legality surface would be pass_response.
    # Because interface does not yet expose a dedicated "is_response_window"
    # query, we treat an empty main-action set + existing legal_counters path
    # as covered above. When counters is empty we fall through to main policy;
    # callers that are inside a pending window with no counters must still be
    # able to pass. Detect that by: no main actions possible and no counters
    # — emit pass_response only when the state is otherwise idle of main acts
    # *and* a pending response is the only sensible choice. For safety and
    # determinism we also check legal_attacks/summons etc.; if everything is
    # empty we end the phase rather than inventing pass_response outside a
    # window.
    player = state.active

    # 1. Level-Up
    action = _choose_level_up(player)
    if action is not None:
        return action

    # 2. Normal Summon
    action = _choose_normal_summon(player)
    if action is not None:
        return action

    # 3. Support
    action = _choose_support(player)
    if action is not None:
        return action

    # 4. Mode switch (only when beneficial)
    action = _choose_mode_switch(player)
    if action is not None:
        return action

    # 5. Attack
    action = _choose_attack(state)
    if action is not None:
        return action

    # 6. End Phase
    return {"action": "end_phase"}


def choose_response(state: GameState) -> Dict[str, Any]:
    """
    Explicit response-window entry point for callers that already know
    they are inside a response window. Uses only interface.legal_counters.
    """
    return _choose_response(state)
