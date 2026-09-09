"""
Phase 6 — Real Provider Integration tests.

Transport is mocked at the provider boundary. No live API required.
Smoke tests (live network) are out of band and not part of this freeze gate.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import sys

import model
import cards
from turn_manager import TurnManager
from match_runner import build_deterministic_opening
from llm_adapter import (
    MockProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    LLMAdapter,
    RejectedAction,
    build_provider,
    enumerate_legal_actions,
    action_in_legal_set,
    _redact,
)


def assert_equal(a, b, msg):
    if a != b:
        raise AssertionError(f"{msg} | Expected {b!r}, got {a!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def snapshot(state):
    return copy.deepcopy(state)


def equiv(a, b) -> bool:
    if a.active_idx != b.active_idx or a.turn_number != b.turn_number:
        return False
    for pa, pb in zip(a.players, b.players):
        if pa.lp != pb.lp:
            return False
        if [c.id for c in pa.hand] != [c.id for c in pb.hand]:
            return False
        if len(pa.field_units()) != len(pb.field_units()):
            return False
    return True


DEFAULT_CFG = ProviderConfig(
    provider="openai",
    api_url="https://example.test/v1/chat/completions",
    api_key_env="VALLEN_LLM_API_KEY",
    model="test-model",
)


def _envelope(content: str) -> str:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": content}}]
    })


# ---------------------------------------------------------------------------
# Provenance / config
# ---------------------------------------------------------------------------

def test_no_engine_import_in_adapter():
    print("R1: llm_adapter still does not import engine")
    path = os.path.join(os.path.dirname(__file__), "..", "llm_adapter.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert_true(alias.name != "engine", f"import {alias.name}")
        if isinstance(node, ast.ImportFrom):
            assert_true(node.module != "engine", "from engine")


def test_api_key_absent_from_env():
    print("R2: missing API key → ProviderError at construction")
    # Ensure env var is unset
    old = os.environ.pop("VALLEN_LLM_API_KEY_TEST_ABSENT", None)
    cfg = ProviderConfig(
        provider="openai",
        api_url="https://example.test/v1/chat/completions",
        api_key_env="VALLEN_LLM_API_KEY_TEST_ABSENT",
        model="m",
    )
    try:
        OpenAICompatibleProvider(cfg)
        raise AssertionError("Should fail without key")
    except ProviderError as e:
        assert_true("not found" in e.reason.lower() or "API key" in e.reason, e.reason)
        assert_true("sk-" not in e.reason, "no key material")
    finally:
        if old is not None:
            os.environ["VALLEN_LLM_API_KEY_TEST_ABSENT"] = old


def test_api_key_never_in_errors():
    print("R3: API key never appears in errors")
    secret = "sk-SUPER-SECRET-KEY-XYZ"
    cfg = DEFAULT_CFG

    def transport(method, url, headers, body, timeout):
        # Echo key back in body to tempt leakage
        return 500, f"error token={secret} auth={headers.get('Authorization')}"

    p = OpenAICompatibleProvider(cfg, transport=transport, api_key=secret)
    try:
        p.complete("prompt")
        raise AssertionError("expected ProviderError")
    except ProviderError as e:
        assert_true(secret not in str(e), f"key leaked in error: {e}")
        assert_true(secret not in e.reason, "key leaked in reason")
        assert_true("***" in e.reason or "HTTP 500" in e.reason, e.reason)


def test_redact_helper():
    print("R4: redact helper strips secrets")
    assert_equal(_redact("Bearer sk-abc and sk-abc", ["sk-abc"]), "Bearer *** and ***", "redact")


# ---------------------------------------------------------------------------
# Transport outcomes
# ---------------------------------------------------------------------------

def test_successful_provider_response():
    print("R5: successful provider response extracts content")
    content = json.dumps({"action": "end_phase"})

    def transport(method, url, headers, body, timeout):
        assert_equal(method, "POST", "method")
        assert_true("Authorization" in headers, "auth header")
        return 200, _envelope(content)

    p = OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    raw = p.complete("hello")
    assert_equal(raw, content, "content extracted")


def test_auth_failure():
    print("R6: API/auth failure → ProviderError")
    def transport(method, url, headers, body, timeout):
        return 401, '{"error":"unauthorized"}'

    p = OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    try:
        p.complete("x")
        raise AssertionError("expected auth failure")
    except ProviderError as e:
        assert_true("auth" in e.reason.lower(), e.reason)


def test_timeout_network_failure():
    print("R7: timeout/network failure → ProviderError")
    def transport_timeout(method, url, headers, body, timeout):
        raise ProviderError("timeout")

    p = OpenAICompatibleProvider(DEFAULT_CFG, transport=transport_timeout, api_key="sk-test")
    try:
        p.complete("x")
        raise AssertionError("expected timeout")
    except ProviderError as e:
        assert_true("timeout" in e.reason.lower(), e.reason)

    def transport_net(method, url, headers, body, timeout):
        raise ProviderError("network failure: simulated")

    p2 = OpenAICompatibleProvider(DEFAULT_CFG, transport=transport_net, api_key="sk-test")
    try:
        p2.complete("x")
        raise AssertionError("expected network failure")
    except ProviderError:
        pass


def test_malformed_provider_payload():
    print("R8: malformed provider envelope → ProviderError")
    def transport(method, url, headers, body, timeout):
        return 200, "not-json-envelope"

    p = OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    try:
        p.complete("x")
        raise AssertionError("expected envelope failure")
    except ProviderError as e:
        assert_true("non-JSON" in e.reason or "envelope" in e.reason.lower(), e.reason)


def test_provider_returns_valid_canonical_json():
    print("R9: provider content is valid Canonical Action JSON → adapter accepts")
    action = {"action": "end_phase"}
    def transport(method, url, headers, body, timeout):
        return 200, _envelope(json.dumps(action))

    provider = OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    adapter = LLMAdapter(provider)
    state, _, _ = build_deterministic_opening()
    result = adapter.decide(state)
    assert_equal(result["action"], "end_phase", "accepted")


def test_provider_returns_non_json_text():
    print("R10: provider content is non-JSON text → RejectedAction")
    def transport(method, url, headers, body, timeout):
        return 200, _envelope("Sure! I'll end the phase.")

    provider = OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    adapter = LLMAdapter(provider)
    state, _, _ = build_deterministic_opening()
    try:
        adapter.decide(state)
        raise AssertionError("expected RejectedAction")
    except RejectedAction as e:
        assert_true("malformed" in e.reason.lower() or "JSON" in e.reason, e.reason)


# ---------------------------------------------------------------------------
# Mutation boundary
# ---------------------------------------------------------------------------

def test_provider_failure_zero_mutation():
    print("R11: provider failure → no mutation")
    state, _, _ = build_deterministic_opening()
    snap = snapshot(state)

    def transport(method, url, headers, body, timeout):
        return 500, "boom"

    adapter = LLMAdapter(
        OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    )
    try:
        adapter.decide(state)
        raise AssertionError("expected failure")
    except ProviderError:
        pass
    assert_true(equiv(state, snap), "state unchanged")


def test_valid_provider_action_same_tm_path_as_mock():
    print("R12: valid provider action → same TurnManager path as MockProvider")
    state, p0, p1 = build_deterministic_opening()
    p0.hand = [cards.CONSCRIPT]
    p0.unit_zones = [None, None, None]
    p1.support_zones = [None, None, None]

    scripted = {"action": "normal_summon", "card_id": cards.CONSCRIPT.id}
    legal = enumerate_legal_actions(state)
    assert_true(action_in_legal_set(scripted, legal), "must be legal")

    # Mock path
    state_m, pm0, _ = build_deterministic_opening()
    pm0.hand = [cards.CONSCRIPT]
    pm0.unit_zones = [None, None, None]
    mock_adapter = LLMAdapter(MockProvider(script=[scripted]))
    mock_action = mock_adapter.decide(state_m)

    # Real provider path (mocked transport)
    def transport(method, url, headers, body, timeout):
        return 200, _envelope(json.dumps(scripted))

    real_adapter = LLMAdapter(
        OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    )
    real_action = real_adapter.decide(state)
    assert_equal(mock_action, real_action, "same Canonical Action")

    tm = TurnManager()
    tm.validate_and_execute(state, real_action)
    assert_equal(len(p0.field_units()), 1, "unit placed via TM")
    assert_true(cards.CONSCRIPT not in p0.hand, "card spent")


def test_build_provider_mock():
    print("R13: build_provider('mock') returns MockProvider offline")
    cfg = ProviderConfig(
        provider="mock",
        api_url="",
        api_key_env="UNUSED",
        model="",
    )
    p = build_provider(cfg)
    assert_true(isinstance(p, MockProvider), "mock type")
    assert_equal(json.loads(p.complete("x"))["action"], "end_phase", "default end")


def test_illegal_content_from_provider_rejected():
    print("R14: provider returns well-formed but illegal action → RejectedAction, no mutation")
    state, _, _ = build_deterministic_opening()
    snap = snapshot(state)
    illegal = {"action": "normal_summon", "card_id": "ghost-id"}

    def transport(method, url, headers, body, timeout):
        return 200, _envelope(json.dumps(illegal))

    adapter = LLMAdapter(
        OpenAICompatibleProvider(DEFAULT_CFG, transport=transport, api_key="sk-test")
    )
    try:
        adapter.decide(state)
        raise AssertionError("expected RejectedAction")
    except RejectedAction:
        pass
    assert_true(equiv(state, snap), "no mutation")


if __name__ == "__main__":
    try:
        test_no_engine_import_in_adapter()
        test_api_key_absent_from_env()
        test_api_key_never_in_errors()
        test_redact_helper()
        test_successful_provider_response()
        test_auth_failure()
        test_timeout_network_failure()
        test_malformed_provider_payload()
        test_provider_returns_valid_canonical_json()
        test_provider_returns_non_json_text()
        test_provider_failure_zero_mutation()
        test_valid_provider_action_same_tm_path_as_mock()
        test_build_provider_mock()
        test_illegal_content_from_provider_rejected()
        print("\n==========================================")
        print("REAL PROVIDER: PASSED (R1-R14)")
        print("==========================================")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
