"""
Phase 5 — LLM Canonical Action Adapter acceptance tests.

Green criterion:
  A mock LLM can play through the same TurnManager boundary as the heuristic,
  while malformed, stale, and illegal model output can never mutate GameState.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import sys

import model
import cards
import engine
import heuristic
from turn_manager import TurnManager
from match_runner import build_deterministic_opening, MatchRunner
from llm_adapter import (
    MockProvider,
    LLMAdapter,
    RejectedAction,
    enumerate_legal_actions,
    parse_canonical_action,
    validate_against_legality,
    action_in_legal_set,
)


def assert_equal(a, b, msg):
    if a != b:
        raise AssertionError(f"{msg} | Expected {b!r}, got {a!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def snapshot_state(state: model.GameState):
    return copy.deepcopy(state)


def states_equivalent(a: model.GameState, b: model.GameState) -> bool:
    if a.active_idx != b.active_idx or a.turn_number != b.turn_number:
        return False
    if (a.pending_event is None) != (b.pending_event is None):
        return False
    for pa, pb in zip(a.players, b.players):
        if pa.lp != pb.lp:
            return False
        if [c.id for c in pa.hand] != [c.id for c in pb.hand]:
            return False
        if len(pa.field_units()) != len(pb.field_units()):
            return False
        if [c.id if c else None for c in pa.support_zones] != [
            c.id if c else None for c in pb.support_zones
        ]:
            return False
    return True


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def test_adapter_does_not_import_engine():
    print("L1: llm_adapter.py must not import engine")
    path = os.path.join(os.path.dirname(__file__), "..", "llm_adapter.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="llm_adapter.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert_true(
                    alias.name != "engine" and not alias.name.startswith("engine."),
                    f"llm_adapter imports engine: {alias.name}",
                )
        if isinstance(node, ast.ImportFrom):
            assert_true(node.module != "engine", "from engine import ...")


# ---------------------------------------------------------------------------
# Parse / reject
# ---------------------------------------------------------------------------

def test_malformed_json_rejected():
    print("L2: malformed JSON rejected")
    for raw in ["", "not json", "{", "[]", "null", "42", '"string"']:
        try:
            parse_canonical_action(raw)
            raise AssertionError(f"Should reject: {raw!r}")
        except RejectedAction:
            pass


def test_unknown_action_type_rejected():
    print("L3: unknown action type rejected")
    try:
        parse_canonical_action('{"action": "teleport"}')
        raise AssertionError("Should reject unknown type")
    except RejectedAction as e:
        assert_true("unknown" in e.reason.lower(), e.reason)


def test_missing_action_field_rejected():
    print("L4: missing action field rejected")
    try:
        parse_canonical_action('{"card_id": "h1"}')
        raise AssertionError("Should reject missing action")
    except RejectedAction:
        pass


def test_valid_parse():
    print("L5: valid Canonical Action parses")
    a = parse_canonical_action('{"action": "end_phase"}')
    assert_equal(a["action"], "end_phase", "action field")


# ---------------------------------------------------------------------------
# Legality membership — no repair
# ---------------------------------------------------------------------------

def test_illegal_not_in_surface_rejected():
    print("L6: action not in legality surface rejected (no repair)")
    state, p0, p1 = build_deterministic_opening()
    legal = enumerate_legal_actions(state)
    # Stale / wrong id
    bad = {"action": "normal_summon", "card_id": "does_not_exist"}
    assert_true(not action_in_legal_set(bad, legal), "must not be legal")
    try:
        validate_against_legality(bad, legal)
        raise AssertionError("Should reject stale id")
    except RejectedAction:
        pass


def test_no_repair_of_wrong_attacker():
    print("L7: wrong attacker_id is rejected, not repaired")
    state, p0, p1 = build_deterministic_opening()
    atk = model.UnitState(
        uid="real_atk", card=cards.CONSCRIPT, owner=p0,
        current_hp=100, mode=model.Mode.ATTACK, has_attacked=False,
    )
    p0.unit_zones[0] = atk
    p0.hand = []
    p1.support_zones = [None, None, None]
    legal = enumerate_legal_actions(state)
    wrong = {"action": "attack", "attacker_id": "wrong_id", "defender_id": None}
    assert_true(not action_in_legal_set(wrong, legal), "wrong id not legal")
    # Legal set should contain the real attacker
    assert_true(
        any(a.get("attacker_id") == "real_atk" for a in legal),
        "real attacker should be legal",
    )


def test_missing_fields_rejected_by_legality():
    print("L8: missing required fields → not in legality surface")
    state, p0, p1 = build_deterministic_opening()
    atk = model.UnitState(
        uid="a1", card=cards.CONSCRIPT, owner=p0,
        current_hp=100, mode=model.Mode.ATTACK, has_attacked=False,
    )
    p0.unit_zones[0] = atk
    p0.hand = []
    p1.support_zones = [None, None, None]
    legal = enumerate_legal_actions(state)
    incomplete = {"action": "attack"}  # missing attacker_id / defender_id
    assert_true(not action_in_legal_set(incomplete, legal), "incomplete rejected")


# ---------------------------------------------------------------------------
# Zero mutation on rejection
# ---------------------------------------------------------------------------

def test_rejection_zero_mutation():
    print("L9: every rejection produces zero state mutation")
    state, p0, p1 = build_deterministic_opening()
    legal = enumerate_legal_actions(state)
    tm = TurnManager()

    rejects = [
        "not json at all",
        '{"action": "teleport"}',
        '{"action": "normal_summon", "card_id": "ghost"}',
        '{"action": "attack", "attacker_id": "nope", "defender_id": null}',
        "",
    ]
    for raw in rejects:
        snap = snapshot_state(state)
        try:
            action = parse_canonical_action(raw)
            validate_against_legality(action, legal)
            # If somehow accepted, still don't execute — test is about reject path
            raise AssertionError(f"Expected rejection for {raw!r}")
        except RejectedAction:
            pass
        assert_true(states_equivalent(state, snap), f"Mutation after reject of {raw!r}")


def test_adapter_reject_does_not_call_turn_manager():
    print("L10: RejectedAction path never reaches TurnManager/engine")
    state, p0, p1 = build_deterministic_opening()
    provider = MockProvider(script=['{"action": "teleport"}'])
    adapter = LLMAdapter(provider)
    snap = snapshot_state(state)
    try:
        adapter.decide(state)
        raise AssertionError("Should have rejected")
    except RejectedAction:
        pass
    assert_true(states_equivalent(state, snap), "State unchanged after reject")


# ---------------------------------------------------------------------------
# Valid path through TurnManager
# ---------------------------------------------------------------------------

def test_valid_mock_action_executes():
    print("L11: valid scripted action executes via TurnManager")
    state, p0, p1 = build_deterministic_opening()
    # Script a legal end_phase
    provider = MockProvider(script=[{"action": "end_phase"}])
    adapter = LLMAdapter(provider)
    action = adapter.decide(state)
    assert_equal(action["action"], "end_phase", "end_phase")
    tm = TurnManager()
    result = tm.validate_and_execute(state, action)
    assert_equal(result, "PHASE_END", "TurnManager accepts end_phase")


def test_valid_summon_via_adapter():
    print("L12: valid normal_summon via adapter → engine mutation")
    state, p0, p1 = build_deterministic_opening()
    # Opening has Conscript; force that summon
    scripted = {"action": "normal_summon", "card_id": cards.CONSCRIPT.id}
    # Ensure it's legal
    legal = enumerate_legal_actions(state)
    assert_true(action_in_legal_set(scripted, legal), "Conscript summon must be legal")

    provider = MockProvider(script=[scripted])
    adapter = LLMAdapter(provider)
    action = adapter.decide(state)
    tm = TurnManager()
    before = len(p0.field_units())
    tm.validate_and_execute(state, action)
    assert_equal(len(p0.field_units()), before + 1, "Unit placed")
    assert_true(cards.CONSCRIPT not in p0.hand, "Card spent")


def test_response_window_counter_and_pass():
    print("L13: response-window counter_support / pass_response protocol")
    state, p0, p1 = build_deterministic_opening()
    p0.hand = [cards.S_NORMAL]
    p0.unit_zones = [None, None, None]
    # B has Counter pre-set in opening
    tm = TurnManager()
    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})
    assert_true(state.pending_event is not None, "pending")

    legal = enumerate_legal_actions(state)
    assert_true(any(a["action"] == "pass_response" for a in legal), "pass legal")
    assert_true(
        any(a["action"] == "counter_support" for a in legal),
        "counter legal",
    )

    # Counter path
    provider = MockProvider(script=[{
        "action": "counter_support",
        "card_id": cards.S_COUNTER.id,
    }])
    adapter = LLMAdapter(provider)
    action = adapter.decide(state)
    res = tm.validate_and_execute(state, action)
    assert_equal(res["status"], "countered", "countered")

    # Pass path on a fresh pending
    state2, a0, a1 = build_deterministic_opening()
    a0.hand = [cards.S_FIELD]
    a0.unit_zones = [None, None, None]
    a1.support_zones = [None, None, None]
    tm2 = TurnManager()
    tm2.validate_and_execute(state2, {"action": "field_support", "card_id": cards.S_FIELD.id})
    provider2 = MockProvider(script=[{"action": "pass_response"}])
    adapter2 = LLMAdapter(provider2)
    action2 = adapter2.decide(state2)
    assert_equal(action2["action"], "pass_response", "pass")
    tm2.validate_and_execute(state2, action2)
    assert_true(cards.S_FIELD in a0.support_zones, "Field resolved")


# ---------------------------------------------------------------------------
# Determinism + same boundary as heuristic
# ---------------------------------------------------------------------------

def test_mock_determinism():
    print("L14: identical script + state → identical accepted action")
    state, _, _ = build_deterministic_opening()
    script = [{"action": "end_phase"}]
    a1 = LLMAdapter(MockProvider(script=script)).decide(state)
    a2 = LLMAdapter(MockProvider(script=script)).decide(state)
    assert_equal(a1, a2, "deterministic")


def test_heuristic_and_adapter_share_turnmanager_boundary():
    print("L15: heuristic and LLM adapter converge on same TurnManager boundary")
    state, p0, p1 = build_deterministic_opening()
    p0.hand = [cards.CONSCRIPT]
    p0.unit_zones = [None, None, None]
    p1.support_zones = [None, None, None]

    h_action = heuristic.choose_action(state)
    # Script the same action the heuristic chose (or end_phase if different)
    # Regardless, both must only mutate via TM
    provider = MockProvider(script=[h_action])
    adapter = LLMAdapter(provider)
    l_action = adapter.decide(state)
    assert_equal(h_action, l_action, "adapter can reproduce heuristic choice")

    tm = TurnManager()
    # Execute once
    snap_before = len(p0.field_units())
    tm.validate_and_execute(state, l_action)
    if l_action["action"] == "normal_summon":
        assert_equal(len(p0.field_units()), snap_before + 1, "shared boundary mutates once")


def test_stale_id_zero_mutation_even_if_forced_through_tm():
    print("L16: stale id rejected by adapter before TM; TM also rejects if bypassed")
    state, p0, p1 = build_deterministic_opening()
    legal = enumerate_legal_actions(state)
    stale = {"action": "normal_summon", "card_id": "stale_card_xyz"}
    assert_true(not action_in_legal_set(stale, legal), "stale not legal")

    provider = MockProvider(script=[stale])
    adapter = LLMAdapter(provider)
    snap = snapshot_state(state)
    try:
        adapter.decide(state)
        raise AssertionError("adapter must reject stale")
    except RejectedAction:
        pass
    assert_true(states_equivalent(state, snap), "no mutation")

    # If someone bypassed the adapter and hit TM directly:
    tm = TurnManager()
    try:
        tm.validate_and_execute(state, stale)
        # May raise ValueError
    except (ValueError, Exception):
        pass
    assert_true(states_equivalent(state, snap), "TM path also no successful mutation")


def test_scripted_mini_match_with_adapter():
    print("L17: scripted mock LLM plays several steps via MatchRunner boundary")
    state, p0, p1 = build_deterministic_opening(lp=800)
    # Script: summon, end, (response if any handled by runner)
    script = [
        {"action": "normal_summon", "card_id": cards.CONSCRIPT.id},
        {"action": "end_phase"},
        {"action": "end_phase"},
        {"action": "end_phase"},
    ]
    adapter = LLMAdapter(MockProvider(script=script))

    def main_agent(s):
        try:
            return adapter.decide(s)
        except RejectedAction:
            return {"action": "end_phase"}

    def response_agent(s):
        try:
            return adapter.decide(s)
        except RejectedAction:
            return {"action": "pass_response"}

    runner = MatchRunner(
        state,
        main_agent=main_agent,
        response_agent=response_agent,
        max_turns=6,
        max_actions_per_turn=10,
    )
    # A few steps
    for _ in range(8):
        if state.game_over:
            break
        runner.step_once()
    assert_true(len(runner.action_log) > 0, "actions recorded")
    # Conscript should have been summoned at some point if script accepted
    # (may be countered if B had counter and a support was played — opening has units path)
    assert_equal(runner.provenance_violations, [], "no provenance issues")


if __name__ == "__main__":
    try:
        test_adapter_does_not_import_engine()
        test_malformed_json_rejected()
        test_unknown_action_type_rejected()
        test_missing_action_field_rejected()
        test_valid_parse()
        test_illegal_not_in_surface_rejected()
        test_no_repair_of_wrong_attacker()
        test_missing_fields_rejected_by_legality()
        test_rejection_zero_mutation()
        test_adapter_reject_does_not_call_turn_manager()
        test_valid_mock_action_executes()
        test_valid_summon_via_adapter()
        test_response_window_counter_and_pass()
        test_mock_determinism()
        test_heuristic_and_adapter_share_turnmanager_boundary()
        test_stale_id_zero_mutation_even_if_forced_through_tm()
        test_scripted_mini_match_with_adapter()
        print("\n==========================================")
        print("LLM ADAPTER: PASSED (L1-L17)")
        print("==========================================")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
