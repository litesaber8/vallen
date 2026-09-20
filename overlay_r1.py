"""
overlay_r1.py — Isolated experimental overlay: R1 "First Level-Up Delay".

Frozen spec: experiments/r1-first-level-up-delay.md
(mirrored in Notion: Balance Investigation v1 -> R1 -- First Level-Up
Delay -- Frozen Spec)

    After a player performs their first Normal Summon of the game, that
    player cannot perform a Level-Up Summon on their immediately
    following turn. Beginning with the subsequent turn, Level-Up Summons
    are unrestricted. Symmetric across both players.

Isolation guarantees (see freeze doc section 3):
  * model.py, engine.py, turn_manager.py, and heuristic.py are never
    edited by this module and are not required to change at all.
  * interface.py is NOT edited on disk. When the overlay is enabled this
    module monkeypatches interface.legal_level_ups with a thin wrapper
    that calls the untouched original implementation and then filters
    its result. When disabled (the default, and always true until
    enable() is called), the wrapper -- if installed at all -- is an
    exact passthrough, so baseline behavior is bit-identical to
    interface.py as shipped.
  * All R1 bookkeeping lives in this module's own dictionaries, keyed by
    player object identity (id(player)). Nothing is written onto
    GameState or Player. The production schema is untouched.

Usage (from a harness):
    import overlay_r1
    overlay_r1.enable()          # turns the rule on, installs the patch
    overlay_r1.reset()           # call once per new game
    ...
    overlay_r1.observe(state)    # call once per decision point, BEFORE
                                  # the active player's legal actions are
                                  # consumed by an agent
    ...
    overlay_r1.get_metadata()    # -> dict of R1 diagnostic fields
    overlay_r1.disable()         # turns the rule back off
"""

from typing import Any, Dict, Optional, Set

import model
import interface


_ENABLED: bool = False
_PATCHED: bool = False
_ORIGINAL_LEGAL_LEVEL_UPS = interface.legal_level_ups

# Per-player bookkeeping, keyed by id(player). Cleared by reset().
_first_normal_summon_turn: Dict[int, int] = {}
_last_field_uids: Dict[int, Set[str]] = {}
_last_seen_turn_number: Optional[int] = None

_metadata: Dict[str, Any] = {}


def enable() -> None:
    """Turn the R1 overlay on and install the interface.py patch (idempotent)."""
    global _ENABLED
    _ENABLED = True
    _install_patch()


def disable() -> None:
    """
    Turn the R1 overlay off. interface.legal_level_ups reverts to exactly
    its original behavior -- the installed wrapper (if any) checks
    _ENABLED on every call and passes through unmodified when False.
    """
    global _ENABLED
    _ENABLED = False


def is_enabled() -> bool:
    return _ENABLED


def reset() -> None:
    """Clear all bookkeeping. Call once at the start of each new game."""
    global _last_seen_turn_number
    _first_normal_summon_turn.clear()
    _last_field_uids.clear()
    _last_seen_turn_number = None
    _metadata.clear()
    _metadata["overlay"] = "R1_first_level_up_delay"
    _metadata["first_normal_summon_turn"] = {}
    _metadata["level_up_restricted_turns"] = []


def get_metadata() -> Dict[str, Any]:
    """Diagnostic metadata for the current game (a safe copy)."""
    out = dict(_metadata)
    out["enabled"] = _ENABLED
    return out


def observe(state: "model.GameState") -> None:
    """
    Update R1 bookkeeping from the current GameState. Call once per
    decision point (e.g. once per MatchRunner.step_once), before the
    active player's legal actions are used by an agent.

    No-op when the overlay is disabled, so it is always safe to call
    unconditionally from a harness regardless of --overlay-r1.
    """
    global _last_seen_turn_number
    if not _ENABLED:
        return

    player = state.active
    key = id(player)

    current_uids = {u.uid for u in player.field_units()}
    previous_uids = _last_field_uids.get(key, set())
    new_uids = current_uids - previous_uids
    _last_field_uids[key] = current_uids

    if key not in _first_normal_summon_turn and new_uids:
        for u in player.field_units():
            # built_from is None only for units created via Normal Summon;
            # Level-Up units always set built_from to the material's card
            # (engine.py do_level_up). This lets us identify "first Normal
            # Summon" without touching engine.py at all.
            if u.uid in new_uids and u.built_from is None:
                _first_normal_summon_turn[key] = state.turn_number
                _metadata["first_normal_summon_turn"][player.name] = state.turn_number
                break

    _last_seen_turn_number = state.turn_number


def _is_restricted(player: "model.Player") -> bool:
    """
    True iff `player` is currently in their immediately-following turn
    after their first Normal Summon (per the R1 spec), based on the most
    recent state passed to observe().
    """
    if not _ENABLED:
        return False
    key = id(player)
    first_turn = _first_normal_summon_turn.get(key)
    if first_turn is None or _last_seen_turn_number is None:
        return False

    restricted = _last_seen_turn_number == first_turn + 2
    if restricted:
        record = {"player": player.name, "turn_number": _last_seen_turn_number}
        marked = _metadata.setdefault("level_up_restricted_turns", [])
        if record not in marked:
            marked.append(record)
    return restricted


def _install_patch() -> None:
    """Install the interface.legal_level_ups wrapper exactly once."""
    global _PATCHED
    if _PATCHED:
        return

    def _wrapped_legal_level_ups(player):
        legal = _ORIGINAL_LEGAL_LEVEL_UPS(player)
        if not _ENABLED:
            return legal
        if _is_restricted(player):
            return []
        return legal

    interface.legal_level_ups = _wrapped_legal_level_ups
    _PATCHED = True
