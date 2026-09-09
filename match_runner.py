"""
Vallen — Phase 4 Agent-vs-Agent Match Runner.

Both players are Canonical Action Producers (heuristic by default).
The only path to mutation is:

    Agent → Canonical Action → TurnManager.validate_and_execute → engine

No agent may call engine.* directly. The runner is the sole orchestrator
of pending-event response windows and turn transitions.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
import model
import cards
import heuristic
from turn_manager import TurnManager


# Type for an agent: (GameState) -> Canonical Action dict
AgentFn = Callable[[model.GameState], Dict[str, Any]]


def default_main_agent(state: model.GameState) -> Dict[str, Any]:
    return heuristic.choose_action(state)


def default_response_agent(state: model.GameState) -> Dict[str, Any]:
    return heuristic.choose_response(state)


def _all_fixture_cards() -> List[model.Card]:
    out = []
    for attr in dir(cards):
        val = getattr(cards, attr)
        if isinstance(val, model.Card):
            out.append(val)
    return out


def build_deterministic_opening(
    lp: int = 800,
) -> Tuple[model.GameState, model.Player, model.Player]:
    """
    Fixed opening hands/fields so two heuristic agents produce a reproducible match.
    LP defaults to the provisional 3-Zone value (800).
    """
    p0 = model.Player(name="AgentA", faction="Humanity", deck=[], lp=lp)
    p1 = model.Player(name="AgentB", faction="Iron Recursion", deck=[], lp=lp)

    # Deterministic mixed hands: units + one of each support type where possible
    p0.hand = [
        cards.CONSCRIPT,
        cards.VETERAN_A,
        cards.RENNE,
        cards.S_NORMAL,
        cards.S_EQUIP,
        cards.S_FIELD,
    ]
    p1.hand = [
        cards.SCOUT_MK1,
        cards.ANALYSIS_DRONE,
        cards.TACTICAL_ENGINE_VOSS,
        cards.S_NORMAL,
        cards.S_COUNTER,  # settable via... we don't have a "set counter" action yet;
                          # Counter is placed in support zone for response tests
        cards.S_EQUIP,
    ]
    # Pre-set one Counter on B so response windows can be exercised if A plays Support
    p1.support_zones[0] = cards.S_COUNTER
    # Remove the duplicate from hand if present
    if cards.S_COUNTER in p1.hand:
        p1.hand.remove(cards.S_COUNTER)

    state = model.GameState(players=(p0, p1), turn_number=1, phase=model.Phase.MAIN)
    return state, p0, p1


class MatchRunner:
    """
    Orchestrates a complete legal game between two Canonical Action Producers.
    """

    def __init__(
        self,
        state: model.GameState,
        main_agent: AgentFn = default_main_agent,
        response_agent: AgentFn = default_response_agent,
        max_turns: int = 40,
        max_actions_per_turn: int = 30,
    ):
        self.state = state
        self.tm = TurnManager()
        self.main_agent = main_agent
        self.response_agent = response_agent
        self.max_turns = max_turns
        self.max_actions_per_turn = max_actions_per_turn
        self.action_log: List[Dict[str, Any]] = []
        self.provenance_violations: List[str] = []

    def _check_terminal(self) -> bool:
        """LP-based win + game_over flag. Does not invent extra rules."""
        for p in self.state.players:
            if p.lp <= 0:
                self.state.game_over = True
                self.state.winner = self.state.players[1 - self.state.players.index(p)].name
                return True
        if self.state.game_over:
            return True
        return False

    def _record(self, actor: str, action: Dict[str, Any], result: Any) -> None:
        entry = {
            "turn": self.state.turn_number,
            "actor": actor,
            "action": dict(action),
            "result_status": (
                result.get("status") if isinstance(result, dict) else str(result)
            ),
        }
        self.action_log.append(entry)

    def step_once(self) -> Dict[str, Any]:
        """
        Execute one agent decision through the canonical boundary.
        Returns a small status dict.
        """
        if self._check_terminal():
            return {"status": "terminal", "winner": self.state.winner}

        state = self.state

        # Response window is owned by the runner (orchestrator), not the agent.
        # Agents never read pending_event; the runner selects which agent entry point.
        if state.pending_event is not None:
            action = self.response_agent(state)
            actor = "response"
        else:
            action = self.main_agent(state)
            actor = state.active.name

        # Provenance: action must be a plain dict with an "action" key
        if not isinstance(action, dict) or "action" not in action:
            self.provenance_violations.append(f"Non-canonical action from agent: {action!r}")
            raise AssertionError(f"Agent returned non-canonical action: {action!r}")

        # end_phase → turn transition
        if action.get("action") == "end_phase" and state.pending_event is None:
            result = self.tm.validate_and_execute(state, action)
            self._record(actor, action, result)
            self.tm.next_turn(state)
            self._check_terminal()
            return {"status": "turn_end", "turn": state.turn_number}

        result = self.tm.validate_and_execute(state, action)
        self._record(actor, action, result)
        self._check_terminal()
        return {
            "status": "ok",
            "action": action,
            "result": result,
            "pending": state.pending_event is not None,
        }

    def run(self) -> Dict[str, Any]:
        """
        Play until terminal or limits. Returns a summary.
        """
        actions_this_turn = 0
        while not self._check_terminal():
            if self.state.turn_number > self.max_turns:
                self.state.game_over = True
                self.state.winner = "draw_max_turns"
                break

            info = self.step_once()
            if info.get("status") == "turn_end":
                actions_this_turn = 0
                continue

            actions_this_turn += 1
            if actions_this_turn > self.max_actions_per_turn:
                # Force end phase to avoid infinite loops from a stuck policy
                if self.state.pending_event is None:
                    forced = {"action": "end_phase"}
                    self.tm.validate_and_execute(self.state, forced)
                    self._record(self.state.active.name, forced, "PHASE_END_FORCED")
                    self.tm.next_turn(self.state)
                    actions_this_turn = 0
                else:
                    # Force pass response
                    forced = {"action": "pass_response"}
                    self.tm.validate_and_execute(self.state, forced)
                    self._record("response", forced, "PASS_FORCED")

        return {
            "winner": self.state.winner,
            "turns": self.state.turn_number,
            "actions": len(self.action_log),
            "log": self.action_log,
            "game_over": self.state.game_over,
            "lp": {p.name: p.lp for p in self.state.players},
            "provenance_violations": self.provenance_violations,
        }


def run_heuristic_vs_heuristic(
    lp: int = 800,
    max_turns: int = 40,
) -> Dict[str, Any]:
    """Convenience: two identical deterministic heuristics, full match."""
    state, _, _ = build_deterministic_opening(lp=lp)
    runner = MatchRunner(state, max_turns=max_turns)
    return runner.run()
