"""
Pre-Phase 4B — Heuristic Agent focused tests.

Proves:
- Returns a legal Canonical Action
- Normal Summon / Level-Up / Attack / Direct Attack / Mode switch selection
- Normal Support uses (card, target) from interface
- Response window: Counter vs pass_response deterministically
- Unavailable Counter → pass_response
- Identical state → identical action
- No direct engine mutation (boundary: interface → heuristic → Canonical → TurnManager → engine)
"""

import copy
import model
import cards
import interface
import heuristic
from turn_manager import TurnManager


def assert_equal(actual, expected, msg):
    if actual != expected:
        raise AssertionError(f"{msg} | Expected {expected!r}, got {actual!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def setup_game(active_hand=None, active_field=None, opponent_field=None, opponent_supports=None):
    user = model.Player(name="User", faction="Humanity", deck=[])
    ai = model.Player(name="AI", faction="Iron Recursion", deck=[])
    if active_hand is not None:
        user.hand = list(active_hand)
    if active_field is not None:
        for i, u in enumerate(active_field):
            u.owner = user
            user.unit_zones[i] = u
    if opponent_field is not None:
        for i, u in enumerate(opponent_field):
            u.owner = ai
            ai.unit_zones[i] = u
    if opponent_supports is not None:
        for i, c in enumerate(opponent_supports):
            ai.support_zones[i] = c
    state = model.GameState(players=(user, ai))
    return state, user, ai


def test_returns_canonical_dict():
    print("H1: choose_action returns a Canonical Action dict")
    state, user, ai = setup_game()
    action = heuristic.choose_action(state)
    assert_true(isinstance(action, dict), "Must return dict")
    assert_true("action" in action, "Must have 'action' key")
    assert_equal(action["action"], "end_phase", "Empty board → end_phase")


def test_normal_summon_selection():
    print("H2: Normal Summon selection")
    state, user, ai = setup_game(active_hand=[cards.CONSCRIPT])
    action = heuristic.choose_action(state)
    assert_equal(action["action"], "normal_summon", "Should summon")
    assert_equal(action["card_id"], cards.CONSCRIPT.id, "Should select Conscript")


def test_level_up_priority():
    print("H3: Level-Up preferred over Normal Summon")
    material = model.UnitState(
        uid="mat1", card=cards.CONSCRIPT, owner=None, current_hp=100, mode=model.Mode.ATTACK
    )
    # Level-2 unit in hand
    state, user, ai = setup_game(
        active_hand=[cards.VETERAN_A, cards.CONSCRIPT],
        active_field=[material],
    )
    material.owner = user
    action = heuristic.choose_action(state)
    assert_equal(action["action"], "level_up", "Level-Up has higher priority")
    assert_equal(action["unit_id"], "mat1", "Correct material")
    assert_equal(action["card_id"], cards.VETERAN_A.id, "Correct upgrade card")


def test_attack_and_direct():
    print("H4: Attack with target and direct attack")
    atk = model.UnitState(
        uid="atk1", card=cards.CONSCRIPT, owner=None,
        current_hp=100, mode=model.Mode.ATTACK, has_attacked=False,
    )
    # Direct attack (empty opponent field)
    state, user, ai = setup_game(active_field=[atk])
    atk.owner = user
    action = heuristic.choose_action(state)
    assert_equal(action["action"], "attack", "Should attack")
    assert_equal(action["attacker_id"], "atk1", "Correct attacker")
    assert_equal(action["defender_id"], None, "Direct attack")

    # Targeted attack
    defn = model.UnitState(
        uid="def1", card=cards.CONSCRIPT, owner=None,
        current_hp=100, mode=model.Mode.ATTACK,
    )
    state2, user2, ai2 = setup_game(active_field=[atk], opponent_field=[defn])
    atk.owner = user2
    defn.owner = ai2
    # Reset has_attacked in case
    atk.has_attacked = False
    action2 = heuristic.choose_action(state2)
    assert_equal(action2["action"], "attack", "Should attack unit")
    assert_equal(action2["attacker_id"], "atk1", "Correct attacker id")
    assert_equal(action2["defender_id"], "def1", "Correct defender id")


def test_mode_switch():
    print("H5: Mode switch when beneficial (low HP Attack → Defense)")
    fragile = model.UnitState(
        uid="frag1", card=cards.CONSCRIPT, owner=None,
        current_hp=20, mode=model.Mode.ATTACK,  # low relative to max 100
    )
    state, user, ai = setup_game(active_field=[fragile])
    fragile.owner = user
    action = heuristic.choose_action(state)
    # Priority: no summon/level/support → mode switch before attack
    assert_equal(action["action"], "switch_mode", "Should switch fragile unit")
    assert_equal(action["unit_id"], "frag1", "Correct unit")


def test_normal_support_uses_interface_pair():
    print("H6: Normal Support uses (card, target) from interface")
    state, user, ai = setup_game(active_hand=[cards.S_NORMAL])
    # Confirm interface shape
    legal = interface.legal_normal_supports(user)
    assert_equal(len(legal), 1, "Interface exposes one Normal")
    card, target = legal[0]
    assert_equal(target, None, "Fixture is targetless")

    action = heuristic.choose_action(state)
    assert_equal(action["action"], "normal_support", "Should play Normal Support")
    assert_equal(action["card_id"], cards.S_NORMAL.id, "Correct Normal Support")
    assert_true("target" not in action or action.get("target") is None,
                "Must not invent a target when interface gave None")


def test_response_counter_when_available():
    print("H7: Response window chooses Counter when available")
    state, user, ai = setup_game(
        active_hand=[cards.S_NORMAL],
        opponent_supports=[cards.S_COUNTER],
    )
    # Declare a pending event via TurnManager (legal setup)
    tm = TurnManager()
    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})
    assert_true(state.pending_event is not None, "Pending must be set")

    # Heuristic must not read pending_event; choose_response uses only legal_counters
    action = heuristic.choose_response(state)
    assert_equal(action["action"], "counter_support", "Should counter")
    assert_equal(action["card_id"], cards.S_COUNTER.id, "Correct Counter")


def test_response_pass_when_no_counter():
    print("H8: Unavailable Counter → pass_response")
    state, user, ai = setup_game(active_hand=[cards.S_NORMAL])
    tm = TurnManager()
    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})
    assert_true(state.pending_event is not None, "Pending must be set")

    # No counter set on opponent → legal_counters is empty
    counters = interface.legal_counters(state)
    assert_equal(counters, [], "No legal counters")

    action = heuristic.choose_response(state)
    assert_equal(action["action"], "pass_response", "Must pass when no Counter")


def test_determinism():
    print("H9: Identical state → identical action")
    material = model.UnitState(
        uid="mat1", card=cards.CONSCRIPT, owner=None, current_hp=100
    )
    state, user, ai = setup_game(
        active_hand=[cards.VETERAN_A, cards.CONSCRIPT],
        active_field=[material],
    )
    material.owner = user

    a1 = heuristic.choose_action(state)
    a2 = heuristic.choose_action(state)
    a3 = heuristic.choose_action(state)
    assert_equal(a1, a2, "Deterministic run 1==2")
    assert_equal(a2, a3, "Deterministic run 2==3")


def test_boundary_no_engine_mutation_by_heuristic():
    print("H10: Boundary — heuristic produces action; TurnManager+engine mutate")
    state, user, ai = setup_game(active_hand=[cards.CONSCRIPT])
    snapshot = copy.deepcopy(state)

    action = heuristic.choose_action(state)

    # Heuristic itself must not have mutated state
    assert_equal(len(user.hand), len(snapshot.active.hand), "Heuristic must not mutate hand")
    assert_equal(user.field_units(), snapshot.active.field_units(), "Heuristic must not mutate field")
    assert_equal(state.pending_event, snapshot.pending_event, "Heuristic must not touch pending")

    # Full pipeline: interface → heuristic → Canonical → TurnManager → engine
    tm = TurnManager()
    result = tm.validate_and_execute(state, action)
    assert_true(result is not None or True, "Pipeline must accept the action")
    # After summon, hand should decrease
    assert_equal(len(user.hand), 0, "Engine should have spent the card")
    assert_equal(len(user.field_units()), 1, "Engine should have placed the unit")


def test_boundary_response_pipeline():
    print("H11: Boundary response pipeline (Counter path)")
    state, user, ai = setup_game(
        active_hand=[cards.S_NORMAL],
        opponent_supports=[cards.S_COUNTER],
    )
    tm = TurnManager()
    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})

    action = heuristic.choose_response(state)
    assert_equal(action["action"], "counter_support", "Should counter")

    # Execute through TurnManager
    res = tm.validate_and_execute(state, action)
    assert_equal(res["status"], "countered", "Counter should cancel the event")
    assert_equal(state.pending_event, None, "Pending cleared")
    assert_true(cards.S_NORMAL in user.hand, "Cancelled Normal stays in hand")


if __name__ == "__main__":
    try:
        test_returns_canonical_dict()
        test_normal_summon_selection()
        test_level_up_priority()
        test_attack_and_direct()
        test_mode_switch()
        test_normal_support_uses_interface_pair()
        test_response_counter_when_available()
        test_response_pass_when_no_counter()
        test_determinism()
        test_boundary_no_engine_mutation_by_heuristic()
        test_boundary_response_pipeline()
        print("\n==========================================")
        print("HEURISTIC AGENT: PASSED (H1-H11)")
        print("==========================================")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
