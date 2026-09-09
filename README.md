# Vallen — Support-Integrated Baseline

Canonical rules engine for **Vallen**.

> **Vallen** — the rite by which the Fallen pass judgment.  
> In the Vallen, worth is weighed, allegiance is tested, and judgment is rendered without appeal.

The game inherits its name from this ancient Fallen Holy ritual.

## Architecture

One implementation of each layer. No parallel turn managers, MCP protocols, or identity schemes.

```
model.py         → pure data structures (Card immutable; UnitState/SupportState hold mutable state)
engine.py        → all mutations + legality assertions
interface.py     → pure enumeration of currently legal choices
turn_manager.py  → canonical flow + Atomic Event (Declare → Respond → Resolve)
mcp_server.py    → canonical external interface
cards.py         → test fixture card definitions (4 of 8 factions)
```

**Design rule:** Interface enumerates; engine enforces.  
Legality is checked twice by design.

**Identity:** Units are identified by stable `uid` (not card definition id).

## Locked invariants

1. `ResourcePileCard.value` is always `1` (regardless of printed level).
2. If any opposing unit is in Defense Mode, every attack must target a Defense Mode unit. Direct attacks and attacks against Attack Mode units are illegal while a taunt exists.
3. Illegal battle attempts raise `InvariantError` and perform zero state mutation.
4. Only Attack Mode units on the active player's field may initiate attacks.
5. Counterable actions use the Atomic Event model: one `validate_and_execute` call *declares*; resolution waits for `pass_response` or a legal Counter.

## Support system

Normal / Equip / Field / Counter supports are specified and partially exercised through acceptance tests.  
See `support_spec.md` and `tests/support_acceptance.py`.

## Regression gates

```bash
python test_scenarios.py
python test_turn_manager.py
python -m pytest tests/integration_test.py tests/support_acceptance.py tests/agent_ready_gate.py -v
```

(Or run the individual scripts under `tests/` if pytest is unavailable.)

## Status

- **Support-Integrated Baseline** — frozen 2026-09-09
- Previous freeze (2026-08-26) remains in history as the pre-Support core
- UID-based identity is canonical
- Atomic Event / Response Window is canonical
- Agent-Ready + Support acceptance tests are regression gates
- LP 800 remains provisional pending human playtest
- No UI / networking / persistence yet
- Future work (LLM battles, human play loop, additional Supports) builds on this baseline only
