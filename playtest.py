"""
Vallen — Phase 7 LLM Playtest harness.

Evaluation only. Does not change frozen gameplay layers.
Experimental variable: the LLM provider (MockProvider for regression,
real provider for live experiments).

Fail-closed policy (explicit, never silent retry):
  On ProviderError / RejectedAction:
    1. record the failure class
    2. do not mutate from the invalid proposal
    3. apply runner fail-closed action:
         response window → pass_response
         main window    → end_phase
    4. tag the forced action so it is NOT counted as an accepted LLM decision
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

import model
import heuristic
from match_runner import MatchRunner, build_deterministic_opening
from llm_adapter import (
    LLMAdapter,
    LLMProvider,
    MockProvider,
    ProviderError,
    RejectedAction,
    parse_canonical_action,
    enumerate_legal_actions,
    action_in_legal_set,
)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

@dataclass
class LLMTelemetry:
    provider_errors: int = 0
    malformed_outputs: int = 0
    illegal_actions: int = 0
    stale_actions: int = 0
    rejected_actions: int = 0  # total rejects (sum of classes above, + unclassified)
    accepted_actions: int = 0
    forced_fail_closed: int = 0
    rejection_log: List[Dict[str, Any]] = field(default_factory=list)

    def total_llm_decisions(self) -> int:
        return self.accepted_actions + self.rejected_actions

    def illegal_action_rate(self) -> float:
        total = self.total_llm_decisions()
        if total == 0:
            return 0.0
        return self.illegal_actions / total


@dataclass
class DecisionCounts:
    normal_summons: int = 0
    level_ups: int = 0
    supports: int = 0
    equip_supports: int = 0
    field_supports: int = 0
    counter_supports: int = 0
    mode_switches: int = 0
    attacks: int = 0
    direct_attacks: int = 0
    end_phases: int = 0
    pass_responses: int = 0

    def record(self, action: Dict[str, Any]) -> None:
        t = action.get("action")
        if t == "normal_summon":
            self.normal_summons += 1
        elif t == "level_up":
            self.level_ups += 1
        elif t == "normal_support":
            self.supports += 1
        elif t == "equip_support":
            self.equip_supports += 1
        elif t == "field_support":
            self.field_supports += 1
        elif t == "counter_support":
            self.counter_supports += 1
        elif t == "switch_mode":
            self.mode_switches += 1
        elif t == "attack":
            self.attacks += 1
            if action.get("defender_id") is None:
                self.direct_attacks += 1
        elif t == "end_phase":
            self.end_phases += 1
        elif t == "pass_response":
            self.pass_responses += 1


@dataclass
class MatchReport:
    match_id: str
    provider: str
    winner: Optional[str]
    turns: int
    actions: int
    terminal_reason: str
    lp: Dict[str, int]
    llm: Dict[str, Any]
    decisions_llm: Dict[str, int]
    decisions_heuristic: Dict[str, int]
    illegal_action_rate: float
    action_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _classify_rejection(exc: RejectedAction, state: model.GameState) -> str:
    """Distinguish malformed vs illegal vs stale for telemetry."""
    reason = (exc.reason or "").lower()
    if "malformed" in reason or "empty" in reason or "missing 'action'" in reason:
        return "malformed_output"
    if "unknown action type" in reason:
        return "malformed_output"

    raw = exc.raw
    action = raw if isinstance(raw, dict) else None
    if action is None and isinstance(exc.raw, str):
        try:
            action = parse_canonical_action(exc.raw)
        except RejectedAction:
            return "malformed_output"

    if not isinstance(action, dict):
        return "malformed_output"

    legal = enumerate_legal_actions(state)
    if action_in_legal_set(action, legal):
        return "illegal_action"  # shouldn't happen if validate raised

    # Stale: well-formed known type, plausible fields, not currently legal
    act = action.get("action")
    if act in ("normal_summon", "level_up", "attack", "equip_support",
               "normal_support", "field_support", "counter_support",
               "switch_mode"):
        # Heuristic: id-like fields present but not in surface → stale or illegal
        for key in ("card_id", "unit_id", "attacker_id", "defender_id"):
            val = action.get(key)
            if isinstance(val, str) and val and ("ghost" in val or "stale" in val
                                                  or "wrong" in val or "nope" in val):
                return "stale_actions"
        return "illegal_action"
    return "illegal_action"


def _fail_closed_action(response_window: bool) -> Dict[str, Any]:
    if response_window:
        return {"action": "pass_response"}
    return {"action": "end_phase"}


class InstrumentedLLMAgent:
    """
    Wraps LLMAdapter. On failure: record + fail-closed. Never retries.
    """

    def __init__(self, adapter: LLMAdapter, telemetry: LLMTelemetry, side: str = "llm"):
        self.adapter = adapter
        self.telemetry = telemetry
        self.side = side
        self.decision_counts = DecisionCounts()
        self.last_was_forced = False

    def _decide(self, state: model.GameState, response_window: bool) -> Dict[str, Any]:
        self.last_was_forced = False
        try:
            action = self.adapter.decide(state)
            self.telemetry.accepted_actions += 1
            self.decision_counts.record(action)
            return action
        except ProviderError as e:
            self.telemetry.provider_errors += 1
            self.telemetry.rejected_actions += 1
            self.telemetry.forced_fail_closed += 1
            self.telemetry.rejection_log.append({
                "class": "provider_error",
                "reason": e.reason,
                "response_window": response_window,
            })
            self.last_was_forced = True
            forced = _fail_closed_action(response_window)
            return forced
        except RejectedAction as e:
            klass = _classify_rejection(e, state)
            if klass == "malformed_output":
                self.telemetry.malformed_outputs += 1
            elif klass == "stale_actions":
                self.telemetry.stale_actions += 1
            else:
                self.telemetry.illegal_actions += 1
            self.telemetry.rejected_actions += 1
            self.telemetry.forced_fail_closed += 1
            self.telemetry.rejection_log.append({
                "class": klass,
                "reason": e.reason,
                "raw": e.raw if not isinstance(e.raw, str) or len(e.raw) < 200 else e.raw[:200],
                "response_window": response_window,
            })
            self.last_was_forced = True
            return _fail_closed_action(response_window)

    def choose_action(self, state: model.GameState) -> Dict[str, Any]:
        return self._decide(state, response_window=False)

    def choose_response(self, state: model.GameState) -> Dict[str, Any]:
        return self._decide(state, response_window=True)


class InstrumentedHeuristicAgent:
    def __init__(self):
        self.decision_counts = DecisionCounts()

    def choose_action(self, state: model.GameState) -> Dict[str, Any]:
        action = heuristic.choose_action(state)
        self.decision_counts.record(action)
        return action

    def choose_response(self, state: model.GameState) -> Dict[str, Any]:
        action = heuristic.choose_response(state)
        self.decision_counts.record(action)
        return action


def _terminal_reason(state: model.GameState, max_turns: int) -> str:
    if state.winner == "draw_max_turns":
        return "draw_max_turns"
    if state.game_over and state.winner:
        return "lp_depleted"
    if state.turn_number > max_turns:
        return "draw_max_turns"
    return "unknown"


def run_playtest_match(
    llm_provider: LLMProvider,
    provider_name: str = "mock",
    lp: int = 800,
    max_turns: int = 40,
    max_actions_per_turn: int = 30,
    llm_side: str = "B",
    match_id: Optional[str] = None,
) -> MatchReport:
    """
    One fixed-condition match: Heuristic vs LLM.

    llm_side: "A" = LLM is AgentA (first player), "B" = LLM is AgentB.
    """
    mid = match_id or str(uuid.uuid4())[:8]
    state, p0, p1 = build_deterministic_opening(lp=lp)
    # Rename for clarity in reports
    p0.name = "Heuristic" if llm_side == "B" else "LLM"
    p1.name = "LLM" if llm_side == "B" else "Heuristic"

    telemetry = LLMTelemetry()
    llm_agent = InstrumentedLLMAgent(LLMAdapter(llm_provider), telemetry, side="llm")
    heur_agent = InstrumentedHeuristicAgent()

    def main_agent(s: model.GameState) -> Dict[str, Any]:
        if s.active.name == "LLM":
            return llm_agent.choose_action(s)
        return heur_agent.choose_action(s)

    def response_agent(s: model.GameState) -> Dict[str, Any]:
        # Responder is the non-initiator.
        initiator = s.pending_event.get("initiator") if s.pending_event else None
        if initiator is not None and initiator in s.players:
            responder = s.players[1 - s.players.index(initiator)]
        else:
            responder = s.opponent
        if responder.name == "LLM":
            return llm_agent.choose_response(s)
        return heur_agent.choose_response(s)

    runner = MatchRunner(
        state,
        main_agent=main_agent,
        response_agent=response_agent,
        max_turns=max_turns,
        max_actions_per_turn=max_actions_per_turn,
    )
    result = runner.run()

    term = _terminal_reason(state, max_turns)
    if result.get("winner") == "draw_max_turns":
        term = "draw_max_turns"

    return MatchReport(
        match_id=mid,
        provider=provider_name,
        winner=result.get("winner"),
        turns=result.get("turns", state.turn_number),
        actions=result.get("actions", 0),
        terminal_reason=term,
        lp=result.get("lp", {p.name: p.lp for p in state.players}),
        llm={
            "provider_errors": telemetry.provider_errors,
            "malformed_outputs": telemetry.malformed_outputs,
            "illegal_actions": telemetry.illegal_actions,
            "stale_actions": telemetry.stale_actions,
            "rejected_actions": telemetry.rejected_actions,
            "accepted_actions": telemetry.accepted_actions,
            "forced_fail_closed": telemetry.forced_fail_closed,
            "rejection_log": telemetry.rejection_log[:50],
        },
        decisions_llm=asdict(llm_agent.decision_counts),
        decisions_heuristic=asdict(heur_agent.decision_counts),
        illegal_action_rate=telemetry.illegal_action_rate(),
        action_log=result.get("log", []),
    )


def run_playtest_batch(
    n: int = 10,
    llm_provider_factory: Optional[Callable[[], LLMProvider]] = None,
    provider_name: str = "mock",
    lp: int = 800,
    max_turns: int = 40,
    llm_side: str = "B",
) -> Dict[str, Any]:
    """
    Fixed-condition batch. Default provider factory yields empty-script MockProvider
    (always end_phase) for offline harness tests — pass a factory for real experiments.
    """
    if llm_provider_factory is None:
        llm_provider_factory = lambda: MockProvider(script=None)

    reports: List[MatchReport] = []
    for i in range(n):
        provider = llm_provider_factory()
        report = run_playtest_match(
            llm_provider=provider,
            provider_name=provider_name,
            lp=lp,
            max_turns=max_turns,
            llm_side=llm_side,
            match_id=f"{provider_name}-{i+1:03d}",
        )
        reports.append(report)

    winners: Dict[str, int] = {}
    for r in reports:
        winners[r.winner or "none"] = winners.get(r.winner or "none", 0) + 1

    total_accepted = sum(r.llm["accepted_actions"] for r in reports)
    total_rejected = sum(r.llm["rejected_actions"] for r in reports)
    total_illegal = sum(r.llm["illegal_actions"] for r in reports)
    total_malformed = sum(r.llm["malformed_outputs"] for r in reports)
    total_provider_err = sum(r.llm["provider_errors"] for r in reports)
    total_stale = sum(r.llm["stale_actions"] for r in reports)

    return {
        "batch_size": n,
        "provider": provider_name,
        "lp": lp,
        "max_turns": max_turns,
        "llm_side": llm_side,
        "winners": winners,
        "terminal_reasons": _count_by(reports, lambda r: r.terminal_reason),
        "totals": {
            "accepted_actions": total_accepted,
            "rejected_actions": total_rejected,
            "illegal_actions": total_illegal,
            "malformed_outputs": total_malformed,
            "stale_actions": total_stale,
            "provider_errors": total_provider_err,
            "illegal_action_rate": (
                total_illegal / (total_accepted + total_rejected)
                if (total_accepted + total_rejected) else 0.0
            ),
        },
        "matches": [r.to_dict() for r in reports],
    }


def _count_by(reports: List[MatchReport], key_fn) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in reports:
        k = key_fn(r)
        out[k] = out.get(k, 0) + 1
    return out


if __name__ == "__main__":
    # Offline smoke: MockProvider that mostly plays end_phase
    batch = run_playtest_batch(n=3, provider_name="mock", max_turns=12)
    print(json.dumps({
        "batch_size": batch["batch_size"],
        "winners": batch["winners"],
        "terminal_reasons": batch["terminal_reasons"],
        "totals": batch["totals"],
    }, indent=2))
