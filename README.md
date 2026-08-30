# Vallen — Rules Engine

Frozen rules-engine baseline for **Vallen**.

> **Vallen** — the rite by which the Fallen pass judgment.  
> In the Vallen, worth is weighed, allegiance is tested, and judgment is rendered without appeal.

The game inherits its name from this ancient Fallen Holy ritual.

## Architecture

```
model.py      → pure data structures
engine.py     → all mutations + legality assertions
interface.py  → pure enumeration of currently legal choices
cards.py      → test fixture card definitions (4 factions)
test_scenarios.py → regression suite
```

**Design rule:** Interface enumerates; engine enforces.  
Legality is checked twice by design.

## Locked invariants

1. `ResourcePileCard.value` is always `1` (regardless of printed level).
2. If any opposing unit is in Defense Mode, every attack must target a Defense Mode unit. Direct attacks and attacks against Attack Mode units are illegal while a taunt exists.
3. Illegal battle attempts raise `InvariantError` and perform zero state mutation.
4. Only Attack Mode units on the active player's field may initiate attacks.

## Run tests

```bash
python test_scenarios.py
```

## Status

- Freeze gate: **GREEN** (2026-08-26)
- No Supports implementation yet
- No UI / networking / persistence
- LP value still a simulation candidate (not canon)
- Canonical title locked: **Vallen** (2026-08-30)
