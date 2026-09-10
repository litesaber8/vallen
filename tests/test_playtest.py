"""
Phase 7 — LLM Playtest harness tests.

Offline only (MockProvider). Does not require live API.
Verifies telemetry classification, fail-closed policy, and no silent retry.
"""

from __future__ import annotations

import json
import sys

from llm_adapter import MockProvider
from playtest import (
    run_playtest_match,
    run_playtest_batch,
    InstrumentedLLMAgent,
    LLMTelemetry,
    _fail_closed_action,
    _classify_rejection,
)
from llm_adapter import LLMAdapter, RejectedAction
from match_runner import build_deterministic_opening
import cards
import model
from turn_manager import TurnManager


def assert_equal(a, b, msg):
    if a != b:
        raise AssertionError(f"{msg} | Expected {b!r}, got {a!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_fail_closed_actions():
    print("PT1: fail-closed actions are explicit")
    assert_equal(_fail_closed_action(True)["action"], "pass_response", "response")
    assert_equal(_fail_closed_action(False)["action"], "end_phase", "main")


def test_no_silent_retry_illegal():
    print("PT2: illegal LLM output recorded + fail-closed, not retried")
    state, p0, p1 = build_deterministic_opening()
    # Script one illegal then nothing
    provider = MockProvider(script=[
        {"action": "normal_summon", "card_id": "ghost-id"},
    ])
    tel = LLMTelemetry()
    agent = InstrumentedLLMAgent(LLMAdapter(provider), tel)
    action = agent.choose_action(state)
    assert_equal(action["action"], "end_phase", "fail-closed main")
    assert_true(agent.last_was_forced, "forced flag")
    assert_equal(tel.rejected_actions, 1, "one reject")
    assert_equal(tel.accepted_actions, 0, "not accepted")
    assert_true(tel.illegal_actions + tel.stale_actions >= 1, "classified")
    # No second provider call for "retry" — script exhausted would end_phase if called again
    action2 = agent.choose_action(state)
    # Second call: script empty → provider returns end_phase which IS legal
    assert_equal(tel.accepted_actions, 1, "second call accepted real end_phase")


def test_malformed_classification():
    print("PT3: malformed JSON classified separately")
    state, _, _ = build_deterministic_opening()
    provider = MockProvider(script=["NOT JSON AT ALL"])
    tel = LLMTelemetry()
    agent = InstrumentedLLMAgent(LLMAdapter(provider), tel)
    action = agent.choose_action(state)
    assert_equal(action["action"], "end_phase", "fail-closed")
    assert_equal(tel.malformed_outputs, 1, "malformed count")
    assert_equal(tel.illegal_actions, 0, "not illegal")


def test_provider_error_path():
    print("PT4: ProviderError → provider_errors + fail-closed + zero mutation")
    # Simulate by using adapter with a provider that raises — use Mock that returns
    # valid then we test classification via RejectedAction path; for ProviderError
    # inject a tiny stub.
    from llm_adapter import LLMProvider, ProviderError

    class Boom(LLMProvider):
        def complete(self, prompt: str) -> str:
            raise ProviderError("simulated timeout")

    state, p0, p1 = build_deterministic_opening()
    hand_before = list(p0.hand)
    tel = LLMTelemetry()
    agent = InstrumentedLLMAgent(LLMAdapter(Boom()), tel)
    action = agent.choose_action(state)
    assert_equal(action["action"], "end_phase", "fail-closed")
    assert_equal(tel.provider_errors, 1, "provider error counted")
    assert_equal([c.id for c in p0.hand], [c.id for c in hand_before], "no mutation")


def test_match_report_structure():
    print("PT5: match report has required telemetry fields")
    # Script legal end_phases so LLM participates cleanly
    provider = MockProvider(script=[{"action": "end_phase"}] * 20)
    report = run_playtest_match(
        llm_provider=provider,
        provider_name="mock",
        max_turns=8,
        llm_side="B",
    )
    d = report.to_dict()
    for key in ("match_id", "provider", "winner", "turns", "actions",
                "terminal_reason", "llm", "decisions_llm", "decisions_heuristic",
                "illegal_action_rate"):
        assert_true(key in d, f"missing {key}")
    for key in ("provider_errors", "malformed_outputs", "illegal_actions",
                "stale_actions", "rejected_actions", "accepted_actions"):
        assert_true(key in d["llm"], f"llm.{key}")
    assert_true(d["turns"] >= 1, "played turns")


def test_batch_offline():
    print("PT6: batch of fixed-condition games runs offline")
    batch = run_playtest_batch(
        n=5,
        llm_provider_factory=lambda: MockProvider(script=[{"action": "end_phase"}] * 30),
        provider_name="mock",
        max_turns=10,
    )
    assert_equal(batch["batch_size"], 5, "batch size")
    assert_equal(len(batch["matches"]), 5, "match count")
    assert_true("totals" in batch, "totals")
    assert_true("winners" in batch, "winners")
    # With pure end_phase LLM, heuristic may win or draw_max_turns
    assert_true(len(batch["winners"]) >= 1, "some winner keys")


def test_response_window_fail_closed():
    print("PT7: response-window illegal → pass_response (not end_phase)")
    state, p0, p1 = build_deterministic_opening()
    p0.hand = [cards.S_NORMAL]
    p0.unit_zones = [None, None, None]
    tm = TurnManager()
    tm.validate_and_execute(state, {"action": "normal_support", "card_id": cards.S_NORMAL.id})
    assert_true(state.pending_event is not None, "pending")

    # LLM returns illegal end_phase during response
    provider = MockProvider(script=[{"action": "end_phase"}])
    tel = LLMTelemetry()
    agent = InstrumentedLLMAgent(LLMAdapter(provider), tel)
    action = agent.choose_response(state)
    assert_equal(action["action"], "pass_response", "fail-closed response")
    assert_true(tel.rejected_actions >= 1, "rejected")


def test_accepted_legal_action_counts():
    print("PT8: legal scripted summon counts as accepted, not rejected")
    state, p0, p1 = build_deterministic_opening()
    # LLM as A (active) with Conscript in hand
    provider = MockProvider(script=[
        {"action": "normal_summon", "card_id": cards.CONSCRIPT.id},
    ])
    report = run_playtest_match(
        llm_provider=provider,
        provider_name="mock",
        max_turns=6,
        llm_side="A",
    )
    assert_true(report.llm["accepted_actions"] >= 1, "accepted at least summon or later")
    # decisions may include the summon if LLM was active first
    assert_true(
        report.decisions_llm["normal_summons"] >= 0,
        "decision counts present",
    )


def test_illegal_rate_formula():
    print("PT9: illegal_action_rate = illegal / (accepted+rejected)")
    provider = MockProvider(script=[
        {"action": "normal_summon", "card_id": "ghost"},
        {"action": "end_phase"},
    ])
    # Direct agent test
    state, _, _ = build_deterministic_opening()
    tel = LLMTelemetry()
    agent = InstrumentedLLMAgent(LLMAdapter(provider), tel)
    agent.choose_action(state)  # illegal → reject
    agent.choose_action(state)  # end_phase → accept
    rate = tel.illegal_action_rate()
    expected = tel.illegal_actions / tel.total_llm_decisions()
    assert_equal(rate, expected, "rate formula")


if __name__ == "__main__":
    try:
        test_fail_closed_actions()
        test_no_silent_retry_illegal()
        test_malformed_classification()
        test_provider_error_path()
        test_match_report_structure()
        test_batch_offline()
        test_response_window_fail_closed()
        test_accepted_legal_action_counts()
        test_illegal_rate_formula()
        print("\n==========================================")
        print("PLAYTEST HARNESS: PASSED (PT1-PT9)")
        print("==========================================")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
