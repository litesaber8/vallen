"""
Experiment R1 -- First Level-Up Delay: 12-game acceptance diagnostic.

Frozen spec: experiments/r1-first-level-up-delay.md

Runs exactly:
    5 treatment sessions (A101..A105) x 2 initiatives (AgentA-first /
    AgentB-first), overlay ON
    + 2 CONTROL sessions (baseline, overlay OFF) x 2 initiatives
    = 12 games total.

NOTE ON DETERMINISM: match_runner.build_deterministic_opening() is
documented as bit-identical on every call -- there is no RNG or seeded
deck-shuffle infrastructure on this branch (feature/llm-playtest). That
means, for a fixed initiative and a fixed overlay setting, the five A10x
sessions are exact replicates of each other and of any other run with the
same settings. This script does not fabricate variation the engine does
not have. Each is still recorded as its own session row per the
acceptance-gate protocol; the honest reading of "5 games" here is
"1 fixed configuration, replicated 5x for record-keeping," not "5
independently seeded games." Seed-based deck variation (the
first_player_test.py / batch_runner.py pattern from the frozen baseline)
would need to be ported onto this branch before a seed-varying version of
this diagnostic is possible -- out of scope here.

Isolation:
  * Never edits interface.py, engine.py, turn_manager.py, heuristic.py,
    or model.py.
  * Uses overlay_r1.py (additive, monkeypatch-based) for the R1 rule.
  * Subclasses match_runner.MatchRunner (does not edit match_runner.py)
    to call overlay_r1.observe(state) once per decision point and to
    collect the diagnostic markers the frozen spec asks for.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

import model
import match_runner
import overlay_r1


class R1MatchRunner(match_runner.MatchRunner):
    """MatchRunner + a single extra hook: overlay_r1.observe(state) before
    every agent decision. No other behavior is changed. overlay_r1.observe
    is a no-op whenever the overlay is disabled, so this subclass behaves
    identically to plain MatchRunner when overlay_r1 is off."""

    def step_once(self) -> Dict[str, Any]:
        overlay_r1.observe(self.state)
        return super().step_once()


def build_opening(first_mover: str, lp: int = 800) -> model.GameState:
    """
    first_mover: "A" or "B". AgentA / AgentB hands are exactly as defined
    in match_runner.build_deterministic_opening(); only seat order (who
    is players[0] / active first) changes. This mirrors the "flip who
    goes first, hold everything else constant" design used previously
    for first-move-advantage isolation.
    """
    state, p0, p1 = match_runner.build_deterministic_opening(lp=lp)
    if first_mover == "A":
        state.players = (p0, p1)
    elif first_mover == "B":
        state.players = (p1, p0)
    else:
        raise ValueError(f"first_mover must be 'A' or 'B', got {first_mover!r}")
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
    lp: int = 800,
    max_turns: int = 40,
) -> Dict[str, Any]:
    if overlay_enabled:
        overlay_r1.enable()
    else:
        overlay_r1.disable()
    overlay_r1.reset()

    state = build_opening(first_mover=first_mover, lp=lp)
    runner = DiagnosticRunner(state, max_turns=max_turns)
    report = runner.run_and_report()
    report["session_id"] = session_id
    report["first_mover"] = first_mover
    report["overlay_r1_enabled"] = overlay_enabled
    return report


def run_diagnostic(lp: int = 800, max_turns: int = 40) -> List[Dict[str, Any]]:
    games: List[Dict[str, Any]] = []

    treatment_ids = [f"A10{i}" for i in range(1, 6)]  # A101..A105
    for sid in treatment_ids:
        games.append(run_one_game(sid, "A", overlay_enabled=True, lp=lp, max_turns=max_turns))
        games.append(run_one_game(sid, "B", overlay_enabled=True, lp=lp, max_turns=max_turns))

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
            "Engine has no RNG on this branch: the 5 A10x sessions per "
            "initiative are exact replicates, run for record-keeping "
            "under the acceptance-gate protocol, not independent seeds."
        ),
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
    args = p.parse_args()

    if args.single:
        report = run_one_game(
            "MANUAL", args.first_mover, overlay_enabled=args.overlay_r1,
            lp=args.lp, max_turns=args.max_turns,
        )
        print(json.dumps(report, indent=2))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        return 0

    games = run_diagnostic(lp=args.lp, max_turns=args.max_turns)
    summary = summarize(games)
    report = {"summary": summary, "games": games}
    print(json.dumps(summary, indent=2))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nFull report written to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
