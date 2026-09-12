"""
One-unit-card-action-per-turn rule (explicitly frozen, added after the
turn-0 lethal combo finding: chained Normal Summon + Level-Up + Level-Up
+ direct attack could kill an undeveloped opponent before their first
turn). A player may take at most one of {Normal Summon, Level-Up Summon}
per turn -- never both, never chained.

Single source of truth: engine.can_normal_summon / engine.can_level_up.
interface.py enumerates through those same predicates, so no separate
interface-layer test is needed to prove enumeration respects the rule --
proving the predicate is correct is sufficient.
"""

import copy

import cards
import engine
import model
from turn_manager import TurnManager
from match_runner import build_deterministic_opening


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _summon_h1(state, tm, player):
    tm.validate_and_execute(state, {"action": "normal_summon", "card_id": cards.CONSCRIPT.id})


def test_second_normal_summon_same_turn_illegal():
    print("U1: a second Normal Summon in the same turn is illegal")
    state, p0, p1 = build_deterministic_opening(lp=800)
    tm = TurnManager()
    _summon_h1(state, tm, p0)
    assert_true(p0.unit_action_used_this_turn, "flag set after first summon")

    # Second unit card in hand -- summoning it this turn must be rejected.
    second_unit_card = next((c for c in p0.hand if c.card_type == model.CardType.UNIT), None)
    assert_true(second_unit_card is not None, "fixture opening hand should have a second unit card")

    snap = copy.deepcopy(state)
    try:
        tm.validate_and_execute(state, {"action": "normal_summon", "card_id": second_unit_card.id})
        raise AssertionError("expected rejection of second Normal Summon this turn")
    except (ValueError, engine.InvariantError):
        pass
    assert_true(len(state.active.hand) == len(snap.active.hand), "no mutation on illegal second summon")


def test_level_up_after_normal_summon_same_turn_illegal():
    print("U2: Level-Up after Normal Summon in the same turn is illegal")
    state, p0, p1 = build_deterministic_opening(lp=800)
    tm = TurnManager()
    _summon_h1(state, tm, p0)

    unit = p0.field_units()[0]
    upgrade = next((c for c in p0.hand if c.card_type == model.CardType.UNIT and c.level == unit.card.level + 1), None)
    assert_true(upgrade is not None, "fixture hand should contain the next-level upgrade")

    snap = copy.deepcopy(state)
    try:
        tm.validate_and_execute(state, {"action": "level_up", "unit_id": unit.uid, "card_id": upgrade.id})
        raise AssertionError("expected rejection of Level-Up after Normal Summon this turn")
    except (ValueError, engine.InvariantError):
        pass
    assert_true(unit.card.id == snap.active.field_units()[0].card.id, "no mutation: unit not leveled")


def test_chained_level_ups_same_turn_illegal():
    print("U3: a second Level-Up chained in the same turn is illegal (the original bug)")
    state, p0, p1 = build_deterministic_opening(lp=800)
    tm = TurnManager()
    _summon_h1(state, tm, p0)

    unit = p0.field_units()[0]
    up1 = next(c for c in p0.hand if c.card_type == model.CardType.UNIT and c.level == unit.card.level + 1)

    # Simplest direct reproduction of the original combo, minus the summon:
    # place a level-1 unit directly, consume the slot via one Level-Up,
    # then assert a second Level-Up this same turn is rejected.
    from model import UnitState, Mode
    import uuid
    state3, p0c, p1c = build_deterministic_opening(lp=800)
    tm3 = TurnManager()
    seed_unit = UnitState(uid=str(uuid.uuid4()), card=cards.CONSCRIPT, owner=p0c,
                           current_hp=cards.CONSCRIPT.base_hp, mode=Mode.ATTACK)
    p0c.unit_zones[0] = seed_unit
    lvl2 = next(c for c in p0c.hand if c.card_type == model.CardType.UNIT and c.level == 2)
    tm3.validate_and_execute(state3, {"action": "level_up", "unit_id": seed_unit.uid, "card_id": lvl2.id})
    assert_true(p0c.unit_action_used_this_turn, "slot consumed by first level-up")

    leveled_unit = p0c.field_units()[0]
    lvl3 = next((c for c in p0c.hand if c.card_type == model.CardType.UNIT and c.level == 3), None)
    if lvl3 is not None:
        snap = copy.deepcopy(state3)
        try:
            tm3.validate_and_execute(state3, {"action": "level_up", "unit_id": leveled_unit.uid, "card_id": lvl3.id})
            raise AssertionError("expected rejection of chained second Level-Up same turn")
        except (ValueError, engine.InvariantError):
            pass
        assert_true(p0c.field_units()[0].card.level == 2, "no mutation: still Level 2, chain blocked")


def test_slot_resets_next_turn():
    print("U4: the slot resets at the start of the player's next turn")
    state, p0, p1 = build_deterministic_opening(lp=800)
    tm = TurnManager()
    _summon_h1(state, tm, p0)
    assert_true(p0.unit_action_used_this_turn, "used this turn")

    # End phase, pass through opponent's turn, come back around.
    tm.validate_and_execute(state, {"action": "end_phase"})
    tm.next_turn(state)  # now p1's turn
    tm.validate_and_execute(state, {"action": "end_phase"})
    tm.next_turn(state)  # back to p0's turn

    assert_true(p0.unit_action_used_this_turn is False, "slot reset at start of p0's new turn")

    unit = p0.field_units()[0]
    upgrade = next(c for c in p0.hand if c.card_type == model.CardType.UNIT and c.level == unit.card.level + 1)
    tm.validate_and_execute(state, {"action": "level_up", "unit_id": unit.uid, "card_id": upgrade.id})
    assert_true(p0.unit_action_used_this_turn, "new turn's unit action correctly consumed the fresh slot")


def test_turn_zero_combo_capped_at_single_level():
    print("U5: the original turn-0 combo is now capped -- direct attack AP matches a single Normal Summon, not a chain to L3")
    state, p0, p1 = build_deterministic_opening(lp=250)
    tm = TurnManager()
    import heuristic
    start_turn = state.turn_number
    i = 0
    while i < 30 and state.turn_number == start_turn:
        if state.pending_event is not None:
            action = heuristic.choose_response(state)
        else:
            action = heuristic.choose_action(state)
        if action.get("action") == "end_phase" and state.pending_event is None:
            break
        tm.validate_and_execute(state, action)
        i += 1
    # p1 must still be alive -- the L1-only opening (50 AP) cannot kill lp=250 in one hit.
    assert_true(p1.lp > 0, f"expected p1 to survive turn 0 at lp=250, got lp={p1.lp}")
    assert_true(p1.lp == 200, f"expected exactly one 50 AP direct hit (250->200), got {p1.lp}")


if __name__ == "__main__":
    import sys
    try:
        test_second_normal_summon_same_turn_illegal()
        test_level_up_after_normal_summon_same_turn_illegal()
        test_chained_level_ups_same_turn_illegal()
        test_slot_resets_next_turn()
        test_turn_zero_combo_capped_at_single_level()
        print("\n==========================================")
        print("ONE-UNIT-ACTION-PER-TURN: PASSED (U1-U5)")
        print("==========================================")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
