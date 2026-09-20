# R1 — First Level-Up Delay — Frozen Spec

**Status:** Frozen
**Type:** Experimental overlay (non-production)
**Scope:** Balance Investigation v1

---

## 1. Rule Wording (LOCKED)

> **R1 — First Level-Up Delay:**
> After a player performs their first Normal Summon of the game, that player cannot perform a Level-Up Summon on their immediately following turn. Beginning with the subsequent turn, Level-Up Summons are unrestricted.

Preferred over the "exactly one unit" formulation because it tests timing directly rather than introducing a second-unit condition.

## 2. Scope — Both Players (LOCKED)

Applied symmetrically to each player's own first Level-Up window.

Rationale: restricting only FP would confound initiative with the intervention. The design goal is:

> same rule → same restriction → different initiative

Overlay tracks per-player state conceptually as `first_normal_summon_turn[player]`, rejecting Level-Up only when the current turn is that player's immediately following turn.

No other summon, attack, mode, Support, or resource behavior changes.

## 3. Architecture Constraints (LOCKED)

- **Production architecture unchanged**: `interface.py` remains the sole legal-action enumerator; `engine.py` remains the mutation/rules enforcement boundary.
- **Experimental overlay only**: R1 does not alter either frozen layer unconditionally. The overlay makes the R1 condition available to the legality layer, so `legal_actions` simply does not enumerate Level-Up during the restricted window.
- **No defensive `engine.py` mutation check** — not necessary since the overlay is only invoked through the canonical action pipeline. A second enforcement path would broaden the experimental diff beyond what's needed.
- **`TurnManager` untouched.**
- **`heuristic.py` untouched.** It reacts to the legal-action set; it does not independently decide to delay Level-Up.
- **State placement**: `first_normal_summon_turn` bookkeeping is kept in the experimental overlay/state metadata, not the permanent production `GameState`, to preserve the claim that the production `GameState` schema is frozen. A feature-gated state field is acceptable only if overlay architecture makes the above awkward, and must have zero effect when `overlay_r1_enabled=False`.

## 4. Acceptance Gate (LOCKED)

Run exactly: **A101–105 × both initiatives + CONTROL × both = 12 games.**

| Diagnostic result | Decision |
|---|---|
| FPA moves toward 45–55%, or meaningful board-control changes / non-binary outcomes appear | Promote to 40-game matrix |
| ≥70% / 100% FP and merely delayed | Fail |
| ≥70% / 100% SP | Fail — overcorrect |
| Excessive draws | Record as side effect; do not automatically promote |

### Recorded fields per game
- `T_first_level_up`
- `T_first_unit_destroyed`
- `first_board_owner`
- `first_board_owner == winner`
- `T_board_control_change`
- `T_lethal`
- residual LP
- forced-end reason
- intervention metadata

### Interpretation rule

If R1 changes the result from:

> FP first board → FP level-up → FP trade → FP control

to something like:

> FP first board → SP develops board → contested level-up/trade

that counts as a successful diagnostic even if FPA doesn't immediately land at 50%. The 45–55% band is the **promotion-to-matrix balance gate**; the appearance of genuine contest is the **mechanism gate**. These are distinct and both matter.

## 5. Implementation Order (LOCKED)

1. Freeze document (this file + Notion record)
2. Isolated overlay implementation
3. `--overlay-r1` CLI flag on `run_live_playtest.py`
4. 12-game diagnostic
5. Inspect traces
6. Decision (promote / fail / record side effect)

No production-code modification occurs before the freeze record exists.

---

## Implementation Reference

- Overlay: `overlay_r1.py` (additive; monkeypatches `interface.legal_level_ups`
  only when enabled; production files unmodified on disk)
- Diagnostic harness: `experiments/r1_diagnostic.py`
- Opening builders: `balance/openings.py` (ported from the offline Balance
  Investigation artifact; Phase-1 family builders A/B/C/D)
- CLI: matched baseline-vs-intervention comparison is the **default**
  invocation (`python3 experiments/r1_diagnostic.py --family B`);
  `--legacy` retains the original unmatched 12-game matrix for historical/
  raw-family inspection only -- see the harness methodology note (Notion:
  Balance Investigation v1 -> Diagnostic Harness -- Matched-by-Default
  Methodology) for why the unmatched aggregate must not be used to
  attribute causality to an overlay.

### Final disposition

**R1 -- NOT PROMOTED. Mechanism-neutral on Family B.**

Family A is invalid for seed-variation analysis: its pools are exactly
5 cards (== hand size), so a seed only permutes card order, which the
deterministic heuristic never reads (it selects by card properties, not
hand position). Confirmed via unmatched run: 10/10 treatment games
identical to each other (11 turns, FP wins all, no board-control change).

Family B's unmatched run produced a 30% FP / 70% SP split that read as a
real balance effect (board-control changes appeared; first-board stopped
predicting the winner in 7/10 games). The matched baseline-vs-R1
comparison (identical hands/seed/initiative/heuristic/protocol per pair,
overlay the only variable) shows this was not caused by R1:

| Matched Family B, n=10 | Result |
|---|---|
| Intervention engaged | 10/10 |
| Winner flipped | 0/10 |
| Downstream outcome changed | 1/10 |
| Downstream outcome unchanged | 9/10 |
| R1 promoted | No |

R1 genuinely engages every time (the first mover's turn-3 Level-Up is
suppressed in all 10 pairs; `T_first_level_up` shifts 3 -> 7/8 in every
pair -- confirmed via the overlay's own `level_up_actually_suppressed`
marker, not inferred from turn numbers). In 9/10 pairs this produces zero
change to winner, turn count, board-control timeline, or lethal turn. In
one pair (B105_A) it measurably alters downstream timing -- turns 18->14,
`T_board_control_change` 8->7, `T_lethal` 18->14 -- without flipping the
winner. That single case is why the disposition is **mechanism-neutral**,
not "no effect": R1 is capable of altering downstream state in this
opening family, just not consequentially enough, nor consistently enough,
to move the aggregate FP/SP balance in this family.

The original unmatched 30%/70% split is confirmed to be ~entirely
hand-composition (3 of 5 seeds show the same agent winning regardless of
initiative -- a hand-power effect, not a move-order effect); it must not
be carried forward as evidence for or against R2/R4.

Full records: Notion (Balance Investigation v1 -> R1 -- Disposition
(Final)); JSON: `experiments/r1_matched_familyB.json`,
`experiments/r1_default_run.json` (post harness-default-flip, same result).
