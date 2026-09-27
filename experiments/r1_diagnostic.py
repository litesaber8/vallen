"""
Experiment R1 -- First Level-Up Delay: matched baseline-vs-intervention
diagnostic harness.

Frozen spec: experiments/r1-first-level-up-delay.md

DEFAULT BEHAVIOR (locked harness rule, adopted after the R1 Family B
episode below): for every seed/initiative configuration, the SAME opening
-- identical hands, identical seed, identical initiative, identical
heuristic, identical protocol -- is played twice: once with the overlay
disabled (baseline) and once enabled (intervention). The two runs are
compared pairwise. An aggregate FP/SP win rate is reported as a
descriptive statistic only; it is never sufficient on its own to
attribute a change to the overlay. Causal attribution comes from the
per-pair diff: winner, turn count, T_first_level_up,
T_first_unit_destroyed, first_board_owner, first_board_owner==winner,
T_board_control_change, T_lethal, residual LP, an intervention-effect
marker (level_up_actually_suppressed for R1), a pairwise winner-flip
count, and a pairwise outcome-change count.

WHY THIS IS THE DEFAULT NOW -- the R1 Family B episode:
  1. An earlier unmatched run (5 seeds x 2 initiatives, overlay ON, vs. a
     separate CONTROL opening) showed a 30% FP / 70% SP split that looked
     like a real balance effect (board-control changes appeared,
     first-board stopped predicting the winner).
  2. Per-seed inspection showed 3 of 5 seeds were actually driven by
     hand-power imbalance regardless of initiative -- unrelated to R1 --
     because the unmatched CONTROL arm used a different opening entirely
     and couldn't isolate what changed *because of* the overlay.
  3. Re-run as a matched comparison (this harness): R1 genuinely engaged
     (the first mover's turn-3 Level-Up was suppressed in all 10 pairs;
     T_first_level_up shifted 3 -> 7/8 every time), but all 10 matched
     pairs produced identical winners, turn counts, and board-control
     timelines. The entire 30/70 split was hand-composition, 0% overlay
     effect. R1 is mechanism-neutral on Family B, not mechanism-positive
     as the unmatched run suggested.
  This is exactly the false-positive class this harness now exists to
  prevent. --legacy retains the old unmatched mode for inspecting raw
  family behavior, but it should not be used to attribute causality.

Opening Family A is invalid for seed-variation analysis: its pools are
exactly 5 cards (== hand size), so a seed only permutes card *order*,
which is invisible to the deterministic heuristic (it never reads hand
position). Families B/C/D have 6-card pools -> 5-card hands, so a seed
actually determines which card is dropped. --family defaults to B.

SEED VARIATION: opening hands come from balance/openings.py (Phase-1
family builders, ported verbatim from the offline Balance Investigation
artifact -- see balance/openings.py's own header). Each seed drives a
deterministic LCG permutation of a fixed per-family card pool.
build_deterministic_opening() (match_runner.py) is untouched and still
backs balance.openings.build_control() for --legacy's CONTROL arm.

Isolation:
  * Never edits interface.py, engine.py, turn_manager.py, heuristic.py,
    model.py, or match_runner.py.
  * balance/openings.py is a ported, unmodified artifact; it only
    constructs Player/GameState objects via model.py and never calls
    engine.py or otherwise mutates through anything but the canonical
    pipeline once the match starts.
  * Uses overlay_r1.py (additive, monkeypatch-based) for the R1 rule.
  * Subclasses match_runner.MatchRunner (does not edit match_runner.py)
    to call overlay_r1.observe(state) once per decision point and to
    collect the diagnostic markers the frozen spec asks for.

TEMPLATE FOR FUTURE OVERLAYS (R2, R4, ...): this file's structure --
seeded opening builder + additive monkeypatch overlay + matched pairwise
runner + per-pair diff summary -- is the intended pattern for any future
intervention diagnostic on this branch, not just R1.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

import model
import match_runner
import overlay_r1
import balance.openings as openings
import determinism_shim

# This harness's entire purpose depends on reproducibility, so the uid
# determinism shim is always on here (see determinism_shim.py for why it
# exists). It is scoped to this process only -- it does not touch
# engine.py on disk, and games run outside seeded_game() still get real
# random uuids.
determinism_shim.enable()


class R1MatchRunner(match_runner.MatchRunner):
    """MatchRunner + a single extra hook: overlay_r1.observe(state) before
    every agent decision. No other behavior is changed. overlay_r1.observe
    is a no-op whenever the overlay is disabled, so this subclass behaves
    identically to plain MatchRunner when overlay_r1 is off."""

    def step_once(self) -> Dict[str, Any]:
        overlay_r1.observe(self.state)
        return super().step_once()


def build_treatment_opening(
    family: str, seed: int, first_mover: str, lp: int = 800
) -> model.GameState:
    """Seeded opening via balance.openings.build_opening (Family A/B/C/D)."""
    state, _p0, _p1 = openings.build_opening(family=family, seed=seed, initiative=first_mover, lp=lp)
    return state


def build_control_opening(first_mover: str, lp: int = 800) -> model.GameState:
    """CONTROL_DETERMINISTIC via balance.openings.build_control -- the
    original fixed-hand build_deterministic_opening(), unchanged."""
    state, _p0, _p1 = openings.build_control(initiative=first_mover, lp=lp)
    return state


def _board_counts(state: model.GameState) -> Dict[str, int]:
    return {p.name: len(p.field_units()) for p in state.players}


class DiagnosticRunner(R1MatchRunner):
    """
    R1MatchRunner + acceptance-gate instrumentation. Tracks the fields
    requested in the R1 frozen spec's diagnostic protocol:
      T_first_level_up, T_first_unit_destroyed, first_board_owner,
      first_board_owner == winner, T_board_control_change, T_lethal,
      residual LP, forced-end reason, intervention metadata.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.T_first_level_up: Optional[int] = None
        self.T_first_unit_destroyed: Optional[int] = None
        self.first_board_owner: Optional[str] = None
        self.T_board_control_change: Optional[int] = None
        self._prior_total_resource_pile = 0
        self._prior_leader: Optional[str] = None

    def step_once(self) -> Dict[str, Any]:
        info = super().step_once()

        state = self.state
        turn = state.turn_number

        # First Level-Up (either seat).
        action = info.get("action") if isinstance(info, dict) else None
        if (
            self.T_first_level_up is None
            and isinstance(action, dict)
            and action.get("action") == "level_up"
        ):
            self.T_first_level_up = turn

        # First unit destroyed: resource_pile only ever grows on
        # destruction (engine.py), so a rising total is a clean signal
        # without needing to read engine internals.
        total_rp = sum(len(p.resource_pile) for p in state.players)
        if self.T_first_unit_destroyed is None and total_rp > self._prior_total_resource_pile:
            self.T_first_unit_destroyed = turn
        self._prior_total_resource_pile = total_rp

        # Board control: "leader" = player with strictly more field units.
        counts = _board_counts(state)
        names = list(counts.keys())
        if counts[names[0]] != counts[names[1]]:
            leader = names[0] if counts[names[0]] > counts[names[1]] else names[1]
            if self.first_board_owner is None:
                self.first_board_owner = leader
                self._prior_leader = leader
            elif (
                self._prior_leader is not None
                and leader != self._prior_leader
                and self.T_board_control_change is None
            ):
                self.T_board_control_change = turn
                self._prior_leader = leader

        return info

    def run_and_report(self) -> Dict[str, Any]:
        result = self.run()
        overlay_meta = overlay_r1.get_metadata()
        winner = result["winner"]
        return {
            "winner": winner,
            "turns": result["turns"],
            "residual_lp": result["lp"],
            "game_over": result["game_over"],
            "forced_end_reason": "draw_max_turns" if winner == "draw_max_turns" else "lp_zero",
            "T_first_level_up": self.T_first_level_up,
            "T_first_unit_destroyed": self.T_first_unit_destroyed,
            "first_board_owner": self.first_board_owner,
            "first_board_owner_is_winner": (
                (self.first_board_owner == winner) if self.first_board_owner is not None else None
            ),
            "T_board_control_change": self.T_board_control_change,
            "T_lethal": result["turns"] if winner not in (None, "draw_max_turns") else None,
            "intervention_metadata": overlay_meta,
            "provenance_violations": result["provenance_violations"],
        }


def run_one_game(
    session_id: str,
    first_mover: str,
    overlay_enabled: bool,
    family: Optional[str] = None,
    seed: Optional[int] = None,
    lp: int = 800,
    max_turns: int = 40,
) -> Dict[str, Any]:
    if overlay_enabled:
        overlay_r1.enable()
    else:
        overlay_r1.disable()
    overlay_r1.reset()

    if family is not None and seed is not None:
        state = build_treatment_opening(family=family, seed=seed, first_mover=first_mover, lp=lp)
    else:
        state = build_control_opening(first_mover=first_mover, lp=lp)

    with determinism_shim.seeded_game(family, seed, first_mover):
        runner = DiagnosticRunner(state, max_turns=max_turns)
        report = runner.run_and_report()
    report["session_id"] = session_id
    report["first_mover"] = first_mover
    report["overlay_r1_enabled"] = overlay_enabled
    report["family"] = family
    report["seed"] = seed
    return report


def run_diagnostic(family: str = "A", lp: int = 800, max_turns: int = 40) -> List[Dict[str, Any]]:
    games: List[Dict[str, Any]] = []

    seeds = [101, 102, 103, 104, 105]
    for seed in seeds:
        sid = f"{family}{seed}"
        games.append(run_one_game(sid, "A", overlay_enabled=True, family=family, seed=seed, lp=lp, max_turns=max_turns))
        games.append(run_one_game(sid, "B", overlay_enabled=True, family=family, seed=seed, lp=lp, max_turns=max_turns))

    games.append(run_one_game("CONTROL", "A", overlay_enabled=False, lp=lp, max_turns=max_turns))
    games.append(run_one_game("CONTROL", "B", overlay_enabled=False, lp=lp, max_turns=max_turns))

    return games


def summarize(games: List[Dict[str, Any]]) -> Dict[str, Any]:
    treatment = [g for g in games if g["overlay_r1_enabled"]]
    control = [g for g in games if not g["overlay_r1_enabled"]]

    def fp_win_rate(gs: List[Dict[str, Any]]) -> Optional[float]:
        decided = [g for g in gs if g["winner"] not in (None, "draw_max_turns")]
        if not decided:
            return None
        fp_wins = 0
        for g in decided:
            fp_name = "AgentA" if g["first_mover"] == "A" else "AgentB"
            if g["winner"] == fp_name:
                fp_wins += 1
        return fp_wins / len(decided)

    return {
        "n_games": len(games),
        "n_treatment": len(treatment),
        "n_control": len(control),
        "treatment_fp_win_rate": fp_win_rate(treatment),
        "control_fp_win_rate": fp_win_rate(control),
        "treatment_draws": sum(1 for g in treatment if g["winner"] == "draw_max_turns"),
        "control_draws": sum(1 for g in control if g["winner"] == "draw_max_turns"),
        "note": (
            "Treatment sessions use balance/openings.py seeded hands; the "
            "actual family/seed used is recorded per-game (see games[].family, "
            "games[].seed) rather than restated here, since this summary is "
            "shared across families. CONTROL uses the original fixed-hand "
            "build_deterministic_opening() via balance.openings.build_control(), "
            "unchanged."
        ),
    }


def run_matched_diagnostic(
    family: str = "B",
    seeds: Optional[List[int]] = None,
    lp: int = 800,
    max_turns: int = 40,
) -> List[Dict[str, Any]]:
    """
    Matched baseline-vs-intervention comparison -- the harness default.

        For each of 5 seed/initiative pairs (10 configurations), run the
        SAME opening (identical hands, identical seed, identical initiative)
        twice -- once with overlay_r1 disabled (baseline), once enabled
        (intervention) -- so the only thing that differs within a pair is
        the overlay. This isolates what changed *because of* the overlay
        from what changed because a given seed's hand pairing is simply
        stronger for one side (see the module docstring's Family B episode).

    Returns 20 games: 10 baseline + 10 R1, tagged with a shared
    `matched_pair_id` so they can be paired back up during analysis.
    """
    if seeds is None:
        seeds = [101, 102, 103, 104, 105]

    games: List[Dict[str, Any]] = []
    for seed in seeds:
        for first_mover in ("A", "B"):
            pair_id = f"{family}{seed}_{first_mover}"

            baseline = run_one_game(
                f"{pair_id}_baseline", first_mover, overlay_enabled=False,
                family=family, seed=seed, lp=lp, max_turns=max_turns,
            )
            baseline["matched_pair_id"] = pair_id
            baseline["arm"] = "baseline"
            games.append(baseline)

            treatment = run_one_game(
                f"{pair_id}_R1", first_mover, overlay_enabled=True,
                family=family, seed=seed, lp=lp, max_turns=max_turns,
            )
            treatment["matched_pair_id"] = pair_id
            treatment["arm"] = "R1"
            games.append(treatment)

    return games


def summarize_matched(games: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Per-pair diff (baseline vs intervention, identical hands/seed/initiative)
    plus aggregate FP-win-rate for each arm. This is the harness default per
    the locked rule: same opening/seed/hand/initiative/heuristic/protocol,
    baseline vs intervention, compared pairwise -- an aggregate FP rate
    alone is descriptive only and is never sufficient on its own to
    attribute a change to the overlay.

    Reports, per pair, at minimum: winner, turn count, T_first_level_up,
    T_first_unit_destroyed, first_board_owner, first_board_owner==winner,
    T_board_control_change, T_lethal, residual LP, an intervention-effect
    marker (level_up_actually_suppressed for R1; analogous markers for
    future overlays should follow the same shape), a pairwise winner-flip
    count, and a pairwise outcome-change count (any tracked field differs,
    not just the winner).
    """
    pairs: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for g in games:
        pairs.setdefault(g["matched_pair_id"], {})[g["arm"]] = g

    diffs = []
    winner_flipped = 0
    outcome_changed = 0
    intervention_engaged = 0
    for pair_id, arms in sorted(pairs.items()):
        b = arms.get("baseline")
        r = arms.get("R1")
        if b is None or r is None:
            continue

        flipped = b["winner"] != r["winner"]
        winner_flipped += int(flipped)

        # T_first_level_up is expected to differ whenever the overlay
        # engages -- that IS the intervention, not evidence of a
        # downstream effect. Track it separately from fields that
        # actually bear on balance/outcome.
        downstream_fields = [
            "winner", "turns", "T_first_unit_destroyed",
            "first_board_owner", "first_board_owner_is_winner",
            "T_board_control_change", "T_lethal", "residual_lp",
        ]
        changed_fields = [f for f in downstream_fields if b.get(f) != r.get(f)]
        mechanism_marker_changed = b.get("T_first_level_up") != r.get("T_first_level_up")
        if changed_fields:
            outcome_changed += 1

        suppressed = r["intervention_metadata"].get("level_up_actually_suppressed", [])
        if suppressed:
            intervention_engaged += 1

        diffs.append({
            "matched_pair_id": pair_id,
            "first_mover": b["first_mover"],
            "baseline_winner": b["winner"],
            "R1_winner": r["winner"],
            "winner_flipped": flipped,
            "baseline_turns": b["turns"],
            "R1_turns": r["turns"],
            "baseline_T_first_level_up": b["T_first_level_up"],
            "R1_T_first_level_up": r["T_first_level_up"],
            "baseline_T_first_unit_destroyed": b["T_first_unit_destroyed"],
            "R1_T_first_unit_destroyed": r["T_first_unit_destroyed"],
            "baseline_first_board_owner": b["first_board_owner"],
            "R1_first_board_owner": r["first_board_owner"],
            "baseline_first_board_is_winner": b["first_board_owner_is_winner"],
            "R1_first_board_is_winner": r["first_board_owner_is_winner"],
            "baseline_T_board_control_change": b["T_board_control_change"],
            "R1_T_board_control_change": r["T_board_control_change"],
            "baseline_T_lethal": b["T_lethal"],
            "R1_T_lethal": r["T_lethal"],
            "baseline_residual_lp": b["residual_lp"],
            "R1_residual_lp": r["residual_lp"],
            "level_up_actually_suppressed": suppressed,
            "mechanism_marker_changed": mechanism_marker_changed,
            "outcome_changed": bool(changed_fields),
            "outcome_changed_fields": changed_fields,
        })

    def fp_win_rate(arm: str) -> Optional[float]:
        gs = [g for g in games if g["arm"] == arm and g["winner"] not in (None, "draw_max_turns")]
        if not gs:
            return None
        wins = sum(
            1 for g in gs
            if g["winner"] == ("AgentA" if g["first_mover"] == "A" else "AgentB")
        )
        return wins / len(gs)

    return {
        "n_pairs": len(diffs),
        "winner_flipped_count": winner_flipped,
        "outcome_changed_count": outcome_changed,
        "intervention_engaged_count": intervention_engaged,
        "baseline_fp_win_rate": fp_win_rate("baseline"),
        "R1_fp_win_rate": fp_win_rate("R1"),
        "note": (
            "baseline_fp_win_rate / R1_fp_win_rate are descriptive aggregates "
            "only. Causal attribution to the overlay comes from "
            "outcome_changed_count (downstream fields only -- winner, turns, "
            "T_first_unit_destroyed, first_board_owner, "
            "first_board_owner_is_winner, T_board_control_change, T_lethal, "
            "residual_lp) and intervention_engaged_count in pair_diffs, not "
            "from the aggregate rates. mechanism_marker_changed "
            "(T_first_level_up shifting) is excluded from outcome_changed "
            "because it is definitional to the overlay engaging, not "
            "evidence of a downstream effect: an overlay can engage on every "
            "pair while outcome_changed_count == 0, meaning it fired but "
            "changed nothing that matters for balance."
        ),
        "pair_diffs": diffs,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--lp", type=int, default=800)
    p.add_argument("--max-turns", type=int, default=40)
    p.add_argument("--out", type=str, default=None)
    p.add_argument(
        "--single",
        action="store_true",
        help="Run one ad-hoc game instead of the full 12-game acceptance matrix.",
    )
    p.add_argument(
        "--overlay-r1",
        action="store_true",
        help="Enable the R1 overlay for --single. Ignored by the full matrix, "
        "which always toggles the overlay per-game per the frozen protocol.",
    )
    p.add_argument("--first-mover", choices=["A", "B"], default="A", help="For --single only.")
    p.add_argument("--family", choices=["A", "B", "C", "D"], default="B", help="For --single or the full matrix. Default B: Family A's seed variation is inert (pool size == hand size).")
    p.add_argument("--seed", type=int, default=101, help="For --single only.")
    p.add_argument(
        "--legacy",
        action="store_true",
        help="Run the old unmatched 12-game acceptance matrix (5 seeds x 2 "
        "initiatives, overlay ON, vs. a separate CONTROL opening) instead of "
        "the matched baseline-vs-intervention comparison. Retained only for "
        "inspecting raw family behavior -- its aggregate FP rate cannot "
        "attribute causality to the overlay (see the R1 Family B episode: "
        "a 30%/70% unmatched split turned out to be 100% hand-composition, "
        "0% overlay effect, once matched). Prefer the default matched mode.",
    )
    args = p.parse_args()

    if args.single:
        report = run_one_game(
            "MANUAL", args.first_mover, overlay_enabled=args.overlay_r1,
            family=args.family, seed=args.seed,
            lp=args.lp, max_turns=args.max_turns,
        )
        print(json.dumps(report, indent=2))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        return 0

    if args.legacy:
        games = run_diagnostic(family=args.family, lp=args.lp, max_turns=args.max_turns)
        summary = summarize(games)
        report = {"summary": summary, "games": games}
        print(json.dumps(summary, indent=2))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(f"\nFull report written to {args.out}", file=sys.stderr)
        return 0

    # Default: matched baseline-vs-intervention comparison.
    games = run_matched_diagnostic(family=args.family, lp=args.lp, max_turns=args.max_turns)
    summary = summarize_matched(games)
    report = {"summary": summary, "games": games}
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nFull report written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
