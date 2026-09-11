"""
Native Anthropic Messages API provider tests.

Transport is mocked at the provider boundary. No live API required.
Mirrors test_real_provider.py's R-series conventions for the OpenAI-
compatible provider, applied to the native wire format instead.
"""

from __future__ import annotations

import json
import os
import sys

import cards
from turn_manager import TurnManager
from match_runner import build_deterministic_opening
from llm_adapter import (
    AnthropicProvider,
    ProviderConfig,
    ProviderError,
    LLMAdapter,
    RejectedAction,
    build_provider,
    enumerate_legal_actions,
    action_in_legal_set,
)


def assert_equal(a, b, msg):
    if a != b:
        raise AssertionError(f"{msg} | Expected {b!r}, got {a!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


DEFAULT_CFG = ProviderConfig(
    provider="anthropic",
    api_url="https://api.anthropic.com/v1/messages",
    api_key_env="VALLEN_ANTHROPIC_API_KEY",
    model="test-model",
)


def _envelope(text: str) -> str:
    return json.dumps({
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "test-model",
        "stop_reason": "end_turn",
    })


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

def test_build_provider_returns_anthropic_provider():
    print("A1: build_provider('anthropic') returns AnthropicProvider, not OpenAI-compatible")
    p = build_provider(DEFAULT_CFG, api_key="sk-ant-test")
    assert_true(isinstance(p, AnthropicProvider), "type")


def test_native_headers_and_body_shape():
    print("A2: native request uses x-api-key / anthropic-version, not Bearer")
    seen = {}

    def transport(method, url, headers, body, timeout):
        seen["headers"] = headers
        seen["body"] = json.loads(body.decode("utf-8"))
        return 200, _envelope(json.dumps({"action": "end_phase"}))

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    p.complete("hello")

    assert_true("x-api-key" in seen["headers"], "x-api-key header present")
    assert_equal(seen["headers"]["x-api-key"], "sk-ant-test", "key value")
    assert_true("Authorization" not in seen["headers"], "no Bearer header")
    assert_equal(seen["headers"]["anthropic-version"], "2023-06-01", "version header")
    assert_true("system" in seen["body"], "top-level system field")
    assert_true("max_tokens" in seen["body"], "max_tokens required field present")
    assert_equal(seen["body"]["messages"], [{"role": "user", "content": "hello"}], "no system-role message")


def test_successful_provider_response():
    print("A3: successful native response extracts text block")
    content = json.dumps({"action": "end_phase"})

    def transport(method, url, headers, body, timeout):
        return 200, _envelope(content)

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    raw = p.complete("hello")
    assert_equal(raw, content, "content extracted")


def test_multi_block_response_takes_first_text_block():
    print("A4: content array with non-text blocks first still finds the text block")
    content = json.dumps({"action": "end_phase"})
    envelope = json.dumps({
        "content": [
            {"type": "tool_use", "id": "x", "name": "noop", "input": {}},
            {"type": "text", "text": content},
        ]
    })

    def transport(method, url, headers, body, timeout):
        return 200, envelope

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    assert_equal(p.complete("hello"), content, "text block found past other blocks")


# ---------------------------------------------------------------------------
# Error handling (auth / rate limit / overload / timeout / malformed)
# ---------------------------------------------------------------------------

def test_api_key_absent_from_env():
    print("A5: missing API key -> ProviderError at construction")
    old = os.environ.pop("VALLEN_ANTHROPIC_API_KEY_TEST_ABSENT", None)
    cfg = ProviderConfig(
        provider="anthropic",
        api_url="https://api.anthropic.com/v1/messages",
        api_key_env="VALLEN_ANTHROPIC_API_KEY_TEST_ABSENT",
        model="m",
    )
    try:
        AnthropicProvider(cfg)
        raise AssertionError("should fail without key")
    except ProviderError as e:
        assert_true("not found" in e.reason.lower() or "API key" in e.reason, e.reason)
    finally:
        if old is not None:
            os.environ["VALLEN_ANTHROPIC_API_KEY_TEST_ABSENT"] = old


def test_api_key_never_in_errors():
    print("A6: API key never appears in errors")
    secret = "sk-ant-SUPER-SECRET-XYZ"

    def transport(method, url, headers, body, timeout):
        return 500, f"error token={secret} key={headers.get('x-api-key')}"

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key=secret)
    try:
        p.complete("prompt")
        raise AssertionError("expected ProviderError")
    except ProviderError as e:
        assert_true(secret not in str(e), f"key leaked: {e}")


def test_auth_failure():
    print("A7: 401/403 -> ProviderError classified as auth failure")
    def transport(method, url, headers, body, timeout):
        return 401, json.dumps({"type": "error", "error": {"type": "authentication_error"}})

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    try:
        p.complete("x")
        raise AssertionError("expected auth failure")
    except ProviderError as e:
        assert_true("auth" in e.reason.lower(), e.reason)


def test_rate_limit_and_overload():
    print("A8: 429 rate-limit and 529 overloaded are distinct ProviderErrors, no retry")
    def transport_429(method, url, headers, body, timeout):
        return 429, json.dumps({"type": "error", "error": {"type": "rate_limit_error"}})

    p = AnthropicProvider(DEFAULT_CFG, transport=transport_429, api_key="sk-ant-test")
    try:
        p.complete("x")
        raise AssertionError("expected rate limit error")
    except ProviderError as e:
        assert_true("rate limit" in e.reason.lower(), e.reason)

    def transport_529(method, url, headers, body, timeout):
        return 529, json.dumps({"type": "error", "error": {"type": "overloaded_error"}})

    p2 = AnthropicProvider(DEFAULT_CFG, transport=transport_529, api_key="sk-ant-test")
    try:
        p2.complete("x")
        raise AssertionError("expected overloaded error")
    except ProviderError as e:
        assert_true("overload" in e.reason.lower(), e.reason)


def test_timeout_network_failure():
    print("A9: timeout/network failure -> ProviderError")
    def transport_timeout(method, url, headers, body, timeout):
        raise ProviderError("timeout")

    p = AnthropicProvider(DEFAULT_CFG, transport=transport_timeout, api_key="sk-ant-test")
    try:
        p.complete("x")
        raise AssertionError("expected timeout")
    except ProviderError as e:
        assert_true("timeout" in e.reason.lower(), e.reason)


def test_malformed_envelope():
    print("A10: non-JSON body -> ProviderError")
    def transport(method, url, headers, body, timeout):
        return 200, "not-json"

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    try:
        p.complete("x")
        raise AssertionError("expected envelope failure")
    except ProviderError as e:
        assert_true("non-JSON" in e.reason or "envelope" in e.reason.lower(), e.reason)


def test_missing_content_array():
    print("A11: response missing 'content' array -> ProviderError")
    def transport(method, url, headers, body, timeout):
        return 200, json.dumps({"type": "message", "role": "assistant"})

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    try:
        p.complete("x")
        raise AssertionError("expected missing-content failure")
    except ProviderError as e:
        assert_true("content" in e.reason.lower(), e.reason)


def test_no_text_block_present():
    print("A12: content array with no text block -> ProviderError")
    def transport(method, url, headers, body, timeout):
        return 200, json.dumps({"content": [{"type": "tool_use", "id": "x", "name": "n", "input": {}}]})

    p = AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    try:
        p.complete("x")
        raise AssertionError("expected no-text-block failure")
    except ProviderError as e:
        assert_true("text block" in e.reason.lower(), e.reason)


# ---------------------------------------------------------------------------
# End-to-end: adapter + TurnManager, same path as mock/OpenAI-compatible
# ---------------------------------------------------------------------------

def test_valid_provider_action_same_tm_path_as_mock():
    print("A13: valid native provider action -> same TurnManager path as MockProvider")
    from llm_adapter import MockProvider

    state, p0, p1 = build_deterministic_opening()
    p0.hand = [cards.CONSCRIPT]
    p0.unit_zones = [None, None, None]
    p1.support_zones = [None, None, None]

    scripted = {"action": "normal_summon", "card_id": cards.CONSCRIPT.id}
    legal = enumerate_legal_actions(state)
    assert_true(action_in_legal_set(scripted, legal), "must be legal")

    state_m, pm0, _ = build_deterministic_opening()
    pm0.hand = [cards.CONSCRIPT]
    pm0.unit_zones = [None, None, None]
    mock_action = LLMAdapter(MockProvider(script=[scripted])).decide(state_m)

    def transport(method, url, headers, body, timeout):
        return 200, _envelope(json.dumps(scripted))

    real_adapter = LLMAdapter(
        AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    )
    real_action = real_adapter.decide(state)
    assert_equal(mock_action, real_action, "same Canonical Action")

    tm = TurnManager()
    tm.validate_and_execute(state, real_action)
    assert_equal(len(p0.field_units()), 1, "unit placed via TM")
    assert_true(cards.CONSCRIPT not in p0.hand, "card spent")


def test_illegal_content_rejected_no_mutation():
    print("A14: well-formed but illegal action -> RejectedAction, no mutation")
    import copy
    state, _, _ = build_deterministic_opening()
    snap = copy.deepcopy(state)
    illegal = {"action": "normal_summon", "card_id": "ghost-id"}

    def transport(method, url, headers, body, timeout):
        return 200, _envelope(json.dumps(illegal))

    adapter = LLMAdapter(
        AnthropicProvider(DEFAULT_CFG, transport=transport, api_key="sk-ant-test")
    )
    try:
        adapter.decide(state)
        raise AssertionError("expected RejectedAction")
    except RejectedAction:
        pass
    assert_equal(state.active_idx, snap.active_idx, "no mutation")
    assert_equal([c.id for c in state.active.hand], [c.id for c in snap.active.hand], "hand unchanged")


if __name__ == "__main__":
    try:
        test_build_provider_returns_anthropic_provider()
        test_native_headers_and_body_shape()
        test_successful_provider_response()
        test_multi_block_response_takes_first_text_block()
        test_api_key_absent_from_env()
        test_api_key_never_in_errors()
        test_auth_failure()
        test_rate_limit_and_overload()
        test_timeout_network_failure()
        test_malformed_envelope()
        test_missing_content_array()
        test_no_text_block_present()
        test_valid_provider_action_same_tm_path_as_mock()
        test_illegal_content_rejected_no_mutation()
        print("\n==========================================")
        print("ANTHROPIC PROVIDER: PASSED (A1-A14)")
        print("==========================================")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
