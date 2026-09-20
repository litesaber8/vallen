"""
Vallen Balance Investigation v1 — seeded opening builders.

Pure, deterministic, auditable. Seed selects/permutates a predefined card
pool within an opening family; it does NOT introduce gameplay RNG.

Frozen layers (engine, interface, TurnManager, heuristic) are never imported
for mutation — only model + cards for construction.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import cards
import model
from match_runner import build_deterministic_opening


# ---------------------------------------------------------------------------
# Card pools per family (from actual fixture pool in cards.py)
# ---------------------------------------------------------------------------

# A — Balanced Curve: normal LV1 → LV2 → LV3 progression available
_A_POOL_P0 = [
    cards.CONSCRIPT,       # L1
    cards.VETERAN_A,       # L2
    cards.RENNE,           # L3
    cards.S_NORMAL,
    cards.S_EQUIP,
]
_A_POOL_P1 = [
    cards.SCOUT_MK1,       # L1
    cards.ANALYSIS_DRONE,  # L2
    cards.TACTICAL_ENGINE_VOSS,  # L3
    cards.S_NORMAL,
    cards.S_EQUIP,
]

# B — Fast Swarm: multiple cheap / low-level units
_B_POOL_P0 = [
    cards.CONSCRIPT,       # L1
    cards.CREEPING_VINE_A, # L1
    cards.CREEPING_VINE_B, # L1
    cards.VETERAN_A,       # L2
    cards.RIFLE_SQUAD,     # L2
    cards.S_NORMAL,
]
_B_POOL_P1 = [
    cards.SCOUT_MK1,       # L1
    cards.LESSER_SERAPH,   # L1
    cards.ANALYSIS_DRONE,  # L2
    cards.DIVINE_ENFORCER, # L2
    cards.SPORE_CLOUD,     # L2
    cards.S_NORMAL,
]

# C — Power Curve: fewer, stronger units (slower first board)
_C_POOL_P0 = [
    cards.VETERAN_A,       # L2
    cards.RENNE,           # L3
    cards.COMBAT_ENGINEER, # L3
    cards.SIEGE_ARCHITECT, # L4 (Iron, but available as high-impact option)
    cards.S_EQUIP,
    cards.S_FIELD,
]
_C_POOL_P1 = [
    cards.ANALYSIS_DRONE,  # L2
    cards.TACTICAL_ENGINE_VOSS,  # L3
    cards.RECLAIMER_UNIT,  # L3
    cards.THRONE_GUARDIAN, # L4
    cards.S_EQUIP,
    cards.S_FIELD,
]

# D — Mixed / Interaction: cheap units + one higher-impact + accessible Support
_D_POOL_P0 = [
    cards.CONSCRIPT,       # L1
    cards.VETERAN_A,       # L2
    cards.RENNE,           # L3
    cards.S_NORMAL,
    cards.S_EQUIP,
    cards.S_FIELD,
]
_D_POOL_P1 = [
    cards.SCOUT_MK1,       # L1
    cards.ANALYSIS_DRONE,  # L2
    cards.INQUISITOR_VALE, # L3 (higher-impact ability)
    cards.S_NORMAL,
    cards.S_COUNTER,
    cards.S_EQUIP,
]

_FAMILY_POOLS: Dict[str, Tuple[List[model.Card], List[model.Card]]] = {
    "A": (_A_POOL_P0, _A_POOL_P1),
    "B": (_B_POOL_P0, _B_POOL_P1),
    "C": (_C_POOL_P0, _C_POOL_P1),
    "D": (_D_POOL_P0, _D_POOL_P1),
}

# Factions used for naming (cosmetic; does not affect rules)
_FAMILY_FACTIONS: Dict[str, Tuple[str, str]] = {
    "A": ("Humanity", "Iron Recursion"),
    "B": ("Humanity", "Verdant"),
    "C": ("Humanity", "Iron Recursion"),
    "D": ("Humanity", "Fallen Holy"),
}


def _seeded_permute(pool: List[model.Card], seed: int) -> List[model.Card]:
    """
    Deterministic permutation of the pool driven by seed.
    Uses a simple LCG so the mapping is pure and reproducible without
    importing random (and without any gameplay RNG).
    """
    if not pool:
        return []
    n = len(pool)
    # LCG parameters (Numerical Recipes)
    a, c, m = 1664525, 1013904223, 2**32
    x = seed & 0xFFFFFFFF
    indices = list(range(n))
    # Fisher–Yates driven by LCG
    for i in range(n - 1, 0, -1):
        x = (a * x + c) % m
        j = x % (i + 1)
        indices[i], indices[j] = indices[j], indices[i]
    return [pool[i] for i in indices]


def _take_hand(pool: List[model.Card], seed: int, size: int = 5) -> List[model.Card]:
    """Take the first `size` cards of the seeded permutation (hand size ~5–6)."""
    perm = _seeded_permute(pool, seed)
    return list(perm[: min(size, len(perm))])


def build_opening(
    family: str,
    seed: int,
    initiative: str = "A",
    lp: int = 800,
) -> Tuple[model.GameState, model.Player, model.Player]:
    """
    Build a pure, deterministic opening for the given family/seed/initiative.

    family: "A" | "B" | "C" | "D"
    seed: integer that selects the hand permutation within the family pool
    initiative: "A" → players[0] starts; "B" → players[1] starts (swap)
    lp: starting life points (default provisional 800)

    Returns (state, p0, p1) where p0 is always the named AgentA configuration
    before any initiative swap; after swap the GameState.players order reflects
    who has initiative.
    """
    family = family.upper()
    if family not in _FAMILY_POOLS:
        raise ValueError(f"Unknown opening family: {family!r}. Expected A/B/C/D.")
    if initiative not in ("A", "B"):
        raise ValueError(f"initiative must be 'A' or 'B', got {initiative!r}")

    pool0, pool1 = _FAMILY_POOLS[family]
    fac0, fac1 = _FAMILY_FACTIONS[family]

    # Distinct seeds for each side so both hands vary with the same seed key
    hand0 = _take_hand(pool0, seed, size=5)
    hand1 = _take_hand(pool1, seed + 7919, size=5)  # offset keeps sides independent

    p0 = model.Player(name="AgentA", faction=fac0, deck=[], lp=lp)
    p1 = model.Player(name="AgentB", faction=fac1, deck=[], lp=lp)
    p0.hand = hand0
    p1.hand = hand1

    if initiative == "A":
        state = model.GameState(
            players=(p0, p1), turn_number=1, phase=model.Phase.MAIN
        )
    else:
        # Swap seat order so AgentB has initiative; names stay attached to configs
        state = model.GameState(
            players=(p1, p0), turn_number=1, phase=model.Phase.MAIN
        )

    return state, p0, p1


def build_control(
    initiative: str = "A",
    lp: int = 800,
) -> Tuple[model.GameState, model.Player, model.Player]:
    """
    Known-FPA control: the existing deterministic opening, unchanged.

    Identifier: CONTROL_DETERMINISTIC
    """
    state, p0, p1 = build_deterministic_opening(lp=lp)
    if initiative == "B":
        # Re-order so original AgentB sits in seat 0
        state = model.GameState(
            players=(p1, p0), turn_number=1, phase=model.Phase.MAIN
        )
    return state, p0, p1


def opening_hand_ids(
    family: str, seed: int, initiative: str = "A"
) -> Tuple[List[str], List[str]]:
    """Convenience for validation: return (active_hand_ids, opponent_hand_ids)."""
    state, _, _ = build_opening(family, seed, initiative=initiative)
    active = [c.id for c in state.players[0].hand]
    opp = [c.id for c in state.players[1].hand]
    return active, opp
