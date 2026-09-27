"""
determinism_shim.py -- Harness-only fix for a real reproducibility gap
found while building the R2 diagnostic on top of the R1 harness.

THE PROBLEM: heuristic.py explicitly documents "stable tie-break by
[...] uid" at two call sites (Level-Up material selection, attack
target selection). "Stable" there means consistent *within* one game
once uids are assigned -- it does NOT mean reproducible *across* runs.
engine.py assigns uid = str(uuid.uuid4()) on every unit creation, and
uuid4() draws from os.urandom, unaffected by PYTHONHASHSEED or anything
else. Confirmed empirically: the identical matched-diagnostic
configuration (family B, all seeds/initiatives) produced
outcome_changed_count of 0 in some process runs and 1 in others, purely
from which random uid string won a tie in the underlying heuristic --
not from the R1 overlay. This is the same "aggregate result that looks
meaningful but isn't" failure class as the original unmatched-Family-B
episode, one layer deeper (tie-break noise instead of hand composition).

THE FIX (harness-only, additive, does not touch engine.py or
heuristic.py on disk): monkeypatch engine.uuid.uuid4 with a seeded
generator for the duration of a game. The seed is derived from the
opening's own identity (family, seed, first_mover) -- deliberately
EXCLUDING which arm (baseline/intervention) is running -- so that a
matched pair's two games draw the identical "random" uid stream right
up until the point an overlay actually causes a different action to be
taken. Any uid-stream divergence after that point is a genuine
consequence of the overlay, not independent noise layered on top of it.

Usage:
    import determinism_shim
    determinism_shim.enable()
    with determinism_shim.seeded_game(family, seed, first_mover):
        ... run one game ...
    determinism_shim.disable()
"""

import random
import uuid as _uuid_module
from contextlib import contextmanager
from typing import Optional

import engine


_ENABLED = False
_ORIGINAL_UUID4 = engine.uuid.uuid4
_RNG: Optional[random.Random] = None


def enable() -> None:
    global _ENABLED
    _ENABLED = True
    engine.uuid.uuid4 = _seeded_uuid4


def disable() -> None:
    global _ENABLED, _RNG
    _ENABLED = False
    _RNG = None
    engine.uuid.uuid4 = _ORIGINAL_UUID4


def is_enabled() -> bool:
    return _ENABLED


def _seeded_uuid4():
    if _RNG is None:
        # Not inside a seeded_game() context -- fall back to the real
        # uuid4 rather than silently returning predictable-but-wrong
        # values with no seed set.
        return _ORIGINAL_UUID4()
    return _uuid_module.UUID(int=_RNG.getrandbits(128), version=4)


@contextmanager
def seeded_game(family: Optional[str], seed: Optional[int], first_mover: str):
    """
    Seed the uid stream for one game. Deliberately does not include
    "arm" (baseline vs intervention) or overlay-enabled state in the
    derived seed key: a matched pair must draw the same uid sequence up
    to the point the overlay itself causes divergence, or a tie-break
    difference downstream of that point would be misread as an overlay
    effect (the exact bug this shim exists to remove).
    """
    global _RNG
    if not _ENABLED:
        yield
        return
    key = (family, seed, first_mover)
    _RNG = random.Random(str(key))
    try:
        yield
    finally:
        _RNG = None
