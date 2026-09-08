
import model
import cards
import engine
import interface
from turn_manager import TurnManager

def assert_equal(actual, expected, msg):
    if actual != expected:
        raise AssertionError(f"{msg} | Expected {expected}, got {actual}")

def setup_game():
    user = model.Player(name="User", faction="Humanity", deck=[])
    ai = model.Player(name="AI", faction="Iron Recursion", deck=[])
    state = model.GameState(players=(user, ai))
    tm = TurnManager()
    return state, tm, user, ai

def test_s1_normal_support_resolve():
    print("S1: Normal Support -> No Counter -> Resolve")
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_NORMAL]

    # Declare
    res = tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})
    assert_equal(res["status"], "pending", "S1: Action should be pending")

    # AI Passes
    tm.validate_and_execute(state, {"action": "pass_response"})
    assert_equal(state.pending_event, None, "S1: Pending event should be cleared")
    assert cards.S_NORMAL not in user.hand, "S1: Card should be spent"
    assert cards.S_NORMAL in user.discard_pile, "S1: Card should be in discard"

def test_s2_normal_support_counter():
    print("S2: Normal Support -> Counter -> Cancel")
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_NORMAL]
    ai.support_zones[0] = cards.S_COUNTER

    # Declare
    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})

    # AI Counters
    res = tm.validate_and_execute(state, {"action": "counter_support", "card_id": cards.S_COUNTER.id})
    assert_equal(res["status"], "countered", "S2: Should be countered")
    assert_equal(state.pending_event, None, "S2: Event should be cleared")
    assert cards.S_NORMAL in user.hand, "S2: Normal support should NOT be spent (cancelled)"
    assert cards.S_COUNTER not in ai.support_zones, "S2: Counter should be spent"
    assert cards.S_COUNTER in ai.discard_pile, "S2: Counter should be in discard"

def test_s3_equip_support_resolve():
    print("S3: Equip Support -> No Counter -> Resolve")
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_EQUIP]
    u = model.UnitState(uid="u1", card=cards.CONSCRIPT, owner=user, current_hp=100)
    user.unit_zones[0] = u

    # Declare
    tm.validate_and_execute(state, {"action": "equip_support", "card_id": cards.S_EQUIP.id, "unit_id": u.uid})

    # AI Passes
    tm.validate_and_execute(state, {"action": "pass_response"})
    assert_equal(len(u.attached_equips), 1, "S3: Equip should be attached")
    assert u.attached_equips[0].card == cards.S_EQUIP, "S3: Wrong equip attached"

def test_s4_equip_support_counter():
    print("S4: Equip Support -> Counter -> Cancel")
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_EQUIP]
    u = model.UnitState(uid="u1", card=cards.CONSCRIPT, owner=user, current_hp=100)
    user.unit_zones[0] = u
    ai.support_zones[0] = cards.S_COUNTER

    tm.validate_and_execute(state, {"action": "equip_support", "card_id": cards.S_EQUIP.id, "unit_id": u.uid})
    tm.validate_and_execute(state, {"action": "counter_support", "card_id": cards.S_COUNTER.id})

    assert_equal(len(u.attached_equips), 0, "S4: Equip should NOT be attached")
    assert cards.S_EQUIP in user.hand, "S4: Equip should still be in hand"

def test_s5_field_support_resolve():
    print("S5: Field Support -> No Counter -> Resolve")
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_FIELD]

    tm.validate_and_execute(state, {"action": "field_support", "card_id": cards.S_FIELD.id})
    tm.validate_and_execute(state, {"action": "pass_response"})

    assert cards.S_FIELD in user.support_zones, "S5: Field should be in support zone"

def test_s6_field_support_counter():
    print("S6: Field Support -> Counter -> Cancel")
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_FIELD]
    ai.support_zones[0] = cards.S_COUNTER

    tm.validate_and_execute(state, {"action": "field_support", "card_id": cards.S_FIELD.id})
    tm.validate_and_execute(state, {"action": "counter_support", "card_id": cards.S_COUNTER.id})

    assert cards.S_FIELD not in user.support_zones, "S6: Field should NOT be in support zone"
    assert cards.S_FIELD in user.hand, "S6: Field should still be in hand"

def test_s7_attack_spent_rule():
    print("S7: Attack -> Counter -> Cancel (Check Attack Spent)")
    state, tm, user, ai = setup_game()
    u = model.UnitState(uid="u1", card=cards.CONSCRIPT, owner=user, current_hp=100, mode=model.Mode.ATTACK)
    user.unit_zones[0] = u
    ai.support_zones[0] = cards.S_COUNTER

    # Declare Attack
    tm.validate_and_execute(state, {"action": "attack", "attacker_id": u.uid, "defender_id": None})

    # AI Counters
    tm.validate_and_execute(state, {"action": "counter_support", "card_id": cards.S_COUNTER.id})

    # According to spec, attacker has still used its attack for the turn.
    # Note: In current engine.resolve_battle, has_attacked is set.
    # But the pending event doesn't call resolve_battle until resolution.
    # We need the TurnManager or Engine to mark it spent on declaration.

    # Let's check the current implementation:
    # In engine.resolve_battle: attacker.has_attacked = True
    # In TurnManager.validate_and_execute: it just sets pending_event.
    # The "Attack Spent" rule says it's spent upon declaration.

    # This is a potential BUG in my current implementation. I should fix it in TurnManager.
    # But let's see if it fails first.
    assert_equal(u.has_attacked, True, "S7: Unit should be marked as having attacked even if countered")

def test_s8_no_pivoting():
    print("S8: Attack -> Target removed during pending -> Fails to resolve")
    state, tm, user, ai = setup_game()
    u_atk = model.UnitState(uid="atk", card=cards.CONSCRIPT, owner=user, current_hp=100, mode=model.Mode.ATTACK)
    u_def = model.UnitState(uid="def", card=cards.CONSCRIPT, owner=ai, current_hp=100)
    user.unit_zones[0] = u_atk
    ai.unit_zones[0] = u_def

    # Declare attack on u_def
    tm.validate_and_execute(state, {"action": "attack", "attacker_id": u_atk.uid, "defender_id": u_def.uid})

    # Simulation: u_def is removed from field
    ai.unit_zones[0] = None

    # Resolve
    res = tm.validate_and_execute(state, {"action": "pass_response"})
    assert_equal(res["status"], "fizzled", "S8: Attack should fail to resolve if target is gone")

def test_s9_defense_target_removal():
    print("S9: Attack -> Defense target removed during pending -> Fails to resolve")
    state, tm, user, ai = setup_game()
    u_atk = model.UnitState(uid="atk", card=cards.CONSCRIPT, owner=user, current_hp=100, mode=model.Mode.ATTACK)
    u_def = model.UnitState(uid="def", card=cards.CONSCRIPT, owner=ai, current_hp=100, mode=model.Mode.DEFENSE)
    user.unit_zones[0] = u_atk
    ai.unit_zones[0] = u_def

    tm.validate_and_execute(state, {"action": "attack", "attacker_id": u_atk.uid, "defender_id": u_def.uid})

    # Remove defense target
    ai.unit_zones[0] = None

    # Resolve
    res = tm.validate_and_execute(state, {"action": "pass_response"})
    assert_equal(res["status"], "fizzled", "S9: Attack should fail to resolve if defense target is gone")

def test_s10_counter_destroys_attacker():
    print("S10: Counter destroys attacker -> Attack fails to resolve")
    state, tm, user, ai = setup_game()
    u_atk = model.UnitState(uid="atk", card=cards.CONSCRIPT, owner=user, current_hp=100, mode=model.Mode.ATTACK)
    user.unit_zones[0] = u_atk
    ai.support_zones[0] = cards.S_COUNTER

    tm.validate_and_execute(state, {"action": "attack", "attacker_id": u_atk.uid, "defender_id": None})

    # Simulation: Counter destroys the attacker
    u_atk.current_hp = -1
    user.unit_zones[0] = None

    # We use _resolve_event to bypass the 'counter' cancellation for the purpose of verifying the resolver
    res = tm._resolve_event(state)
    assert_equal(res["status"], "fizzled", "S10: Attack should fail to resolve if attacker was destroyed")

def test_s11_no_secondary_counter():
    print("S11: Counter effect destroys something -> NO second counter window")
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_NORMAL]
    ai.support_zones[0] = cards.S_COUNTER

    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})
    tm.validate_and_execute(state, {"action": "counter_support", "card_id": cards.S_COUNTER.id})

    assert_equal(state.pending_event, None, "S11: No secondary response window should open")

def test_s12_zero_mutation():
    print("S12: Illegal action -> Zero state mutation")
    state, tm, user, ai = setup_game()
    import copy
    snapshot = copy.deepcopy(state)

    try:
        tm.validate_and_execute(state, {"action": "attack", "attacker_id": "nonexistent", "defender_id": None})
    except ValueError:
        pass

    assert state.active_idx == snapshot.active_idx
    assert state.turn_number == snapshot.turn_number
    assert state.phase == snapshot.phase
    assert len(user.hand) == len(snapshot.active.hand)
    assert len(ai.hand) == len(snapshot.opponent.hand)
    assert state.pending_event == snapshot.pending_event

def test_s13_legal_actions_pending():
    print("S13: legal_actions() -> Only response actions when pending")
    from mcp_server import VallenMCPServer
    state, tm, user, ai = setup_game()
    user.hand = [cards.S_NORMAL]
    ai.support_zones[0] = cards.S_COUNTER
    server = VallenMCPServer(state)

    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})
    legals = server.get_legal_actions_canonical()

    for act in legals:
        assert act["action"] in ["counter_support", "pass_response"], f"S13: Illegal action {act['action']} in pending state"

    assert any(a["action"] == "pass_response" for a in legals), "S13: Missing pass_response"
    assert any(a["action"] == "counter_support" for a in legals), "S13: Missing counter_support"

def test_s14_absolute_zero_mutation():
    print("S14: Absolute Zero Mutation (Agent Boundary)")
    state, tm, user, ai = setup_game()
    import copy
    snapshot = copy.deepcopy(state)

    adversarial = [
        {"action": "attack", "attacker_id": "garbage", "defender_id": "garbage"},
        {"action": "normal_summon", "card_id": "garbage"},
        {"action": "jump_to_win_screen"},
        {"action": "set_lp", "value": 9999},
        None,
        "Not a dict"
    ]

    for inp in adversarial:
        try:
            if isinstance(inp, dict):
                tm.validate_and_execute(state, inp)
        except (ValueError, Exception):
            pass

    assert state.active_idx == snapshot.active_idx
    assert state.turn_number == snapshot.turn_number
    assert state.phase == snapshot.phase
    assert state.pending_event == snapshot.pending_event
    assert len(user.hand) == len(snapshot.active.hand)
    assert len(ai.hand) == len(snapshot.opponent.hand)
    assert state.players[0].lp == snapshot.players[0].lp
    assert state.players[1].lp == snapshot.players[1].lp

if __name__ == "__main__":
    try:
        test_s1_normal_support_resolve()
        test_s2_normal_support_counter()
        test_s3_equip_support_resolve()
        test_s4_equip_support_counter()
        test_s5_field_support_resolve()
        test_s6_field_support_counter()
        test_s7_attack_spent_rule()
        test_s8_no_pivoting()
        test_s9_defense_target_removal()
        test_s10_counter_destroys_attacker()
        test_s11_no_secondary_counter()
        test_s12_zero_mutation()
        test_s13_legal_actions_pending()
        test_s14_absolute_zero_mutation()
        print("\n==========================================")
        print("SUPPORT ACCEPTANCE: PASSED (S1-S14)")
        print("==========================================")
    except Exception as e:
        print(f"\nACCEPTANCE FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
