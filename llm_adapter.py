"""
Vallen — Phase 5 LLM Canonical Action Adapter.

Responsibility:
  Translate untrusted model output into a Canonical Action — or reject it.

Does NOT:
  - repair actions
  - invent targets
  - call engine.py
  - mutate GameState

Pipeline:
  Serialized GameState + Legal Actions
            ↓
      LLM / Mock Provider
            ↓
        JSON output
            ↓
    Canonical Action parser + legality check
            ↓
  TurnManager.validate_and_execute()   (caller only, on accept)
            ↓
         engine.py
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence

import model
import interface


# ---------------------------------------------------------------------------
# Errors — rejection never mutates state; caller must not invoke TurnManager
# ---------------------------------------------------------------------------

class RejectedAction(Exception):
    """Model output could not be accepted as a Canonical Action."""

    def __init__(self, reason: str, raw: Any = None):
        self.reason = reason
        self.raw = raw
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Return raw text (expected to be a JSON object)."""
        pass


class MockProvider(LLMProvider):
    """
    Deterministic scripted provider.
    Responses are consumed in order; exhausted queue yields end_phase.
    """

    def __init__(self, script: Optional[Sequence[Any]] = None):
        """
        script items may be:
          - dict  → json-dumped as the response
          - str   → used as raw response (may be malformed on purpose)
          - None  → empty string
        """
        self._script: List[Any] = list(script) if script is not None else []
        self._idx = 0
        self.prompts: List[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._idx >= len(self._script):
            return json.dumps({"action": "end_phase"})
        item = self._script[self._idx]
        self._idx += 1
        if item is None:
            return ""
        if isinstance(item, str):
            return item
        return json.dumps(item)


# ---------------------------------------------------------------------------
# Legality surface (Canonical Action list)
# ---------------------------------------------------------------------------

def enumerate_legal_actions(state: model.GameState) -> List[Dict[str, Any]]:
    """
    Complete agent-facing legality surface as Canonical Action dicts.
    Response window: only counter_support / pass_response.
    Main window: summons, level-ups, switches, attacks, supports, end_phase.
    """
    actions: List[Dict[str, Any]] = []

    if state.pending_event is not None:
        for card, _event in interface.legal_counters(state):
            actions.append({"action": "counter_support", "card_id": card.id})
        actions.append({"action": "pass_response"})
        return actions

    player = state.active

    for card, _tributes in interface.legal_normal_summons(player):
        actions.append({"action": "normal_summon", "card_id": card.id})

    for material, card in interface.legal_level_ups(player):
        actions.append({
            "action": "level_up",
            "unit_id": material.uid,
            "card_id": card.id,
        })

    for unit in interface.legal_mode_switches(player):
        actions.append({"action": "switch_mode", "unit_id": unit.uid})

    for attacker, defender in interface.legal_attacks(state):
        actions.append({
            "action": "attack",
            "attacker_id": attacker.uid,
            "defender_id": defender.uid if defender is not None else None,
        })

    for card, target in interface.legal_normal_supports(player):
        entry: Dict[str, Any] = {"action": "normal_support", "card_id": card.id}
        if target is not None:
            entry["target"] = target.uid
        actions.append(entry)

    for card, unit in interface.legal_equips(player):
        actions.append({
            "action": "equip_support",
            "card_id": card.id,
            "unit_id": unit.uid,
        })

    for card in interface.legal_fields(player):
        actions.append({"action": "field_support", "card_id": card.id})

    actions.append({"action": "end_phase"})
    return actions


def serialize_state_for_prompt(state: model.GameState) -> Dict[str, Any]:
    """Minimal structured view for the provider prompt (not authoritative)."""
    def unit_view(u: Optional[model.UnitState]):
        if u is None:
            return None
        return {
            "uid": u.uid,
            "card_id": u.card.id,
            "name": u.card.name,
            "hp": u.current_hp,
            "mode": u.mode.name,
            "has_attacked": u.has_attacked,
        }

    def player_view(p: model.Player) -> Dict[str, Any]:
        return {
            "name": p.name,
            "lp": p.lp,
            "hand": [{"id": c.id, "name": c.name, "type": c.card_type.name,
                       "support_type": c.support_type.name if c.support_type else None}
                      for c in p.hand],
            "field": [unit_view(u) for u in p.unit_zones],
            "support_zones": [
                {"id": c.id, "name": c.name} if c else None for c in p.support_zones
            ],
        }

    return {
        "turn": state.turn_number,
        "phase": state.phase.name,
        "active": state.active.name,
        "pending": state.pending_event is not None,
        "players": [player_view(p) for p in state.players],
    }


def build_prompt(state: model.GameState, legal: List[Dict[str, Any]]) -> str:
    return (
        "You are playing Vallen. Respond with ONLY a single JSON object chosen "
        "from LEGAL ACTIONS. No explanation.\n\n"
        f"STATE:\n{json.dumps(serialize_state_for_prompt(state), indent=2)}\n\n"
        f"LEGAL ACTIONS:\n{json.dumps(legal, indent=2)}\n"
    )


# ---------------------------------------------------------------------------
# Parse + validate (no repair)
# ---------------------------------------------------------------------------

_KNOWN_ACTION_TYPES = frozenset({
    "normal_summon",
    "level_up",
    "switch_mode",
    "attack",
    "normal_support",
    "equip_support",
    "field_support",
    "counter_support",
    "pass_response",
    "end_phase",
})


def parse_canonical_action(raw: str) -> Dict[str, Any]:
    """
    Parse raw provider text into a dict. Rejects malformed JSON and
    non-object roots. Does not validate legality or fields beyond type.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise RejectedAction("empty response", raw)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise RejectedAction(f"malformed JSON: {e}", raw) from e
    if not isinstance(data, dict):
        raise RejectedAction("JSON root must be an object", raw)
    if "action" not in data:
        raise RejectedAction("missing 'action' field", raw)
    if not isinstance(data["action"], str):
        raise RejectedAction("'action' must be a string", raw)
    if data["action"] not in _KNOWN_ACTION_TYPES:
        raise RejectedAction(f"unknown action type: {data['action']!r}", raw)
    return data


def _normalize_for_compare(action: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stable comparison form. Does not invent fields — only drops None-valued
    keys that are optional in the legality surface so {"defender_id": None}
    matches a legal entry that also has defender_id None.
    """
    return {k: v for k, v in action.items()}


def action_in_legal_set(
    action: Dict[str, Any],
    legal: List[Dict[str, Any]],
) -> bool:
    """
    Exact membership check. No fuzzy matching, no field repair, no closest-id.
    """
    target = _normalize_for_compare(action)
    for entry in legal:
        if _normalize_for_compare(entry) == target:
            return True
    return False


def validate_against_legality(
    action: Dict[str, Any],
    legal: List[Dict[str, Any]],
) -> None:
    """Raise RejectedAction if action is not an exact member of legal."""
    if not action_in_legal_set(action, legal):
        raise RejectedAction(
            f"action not in current legality surface: {action!r}",
            action,
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class LLMAdapter:
    """
    Canonical Action Producer backed by an LLMProvider.
    Same role as heuristic.choose_action: returns a Canonical Action dict
    or raises RejectedAction (caller must not mutate on reject).
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def decide(self, state: model.GameState) -> Dict[str, Any]:
        legal = enumerate_legal_actions(state)
        prompt = build_prompt(state, legal)
        raw = self.provider.complete(prompt)
        action = parse_canonical_action(raw)
        validate_against_legality(action, legal)
        return action

    # AgentFn-compatible wrappers for MatchRunner
    def choose_action(self, state: model.GameState) -> Dict[str, Any]:
        return self.decide(state)

    def choose_response(self, state: model.GameState) -> Dict[str, Any]:
        return self.decide(state)
