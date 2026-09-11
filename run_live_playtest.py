"""
Vallen — one-shot live playtest batch: Heuristic vs real Anthropic LLM.

Fixed-condition experiment per the Phase 7 read order:
  1. Usable Canonical Actions?
  2. Action-surface understanding?
  3. Level-Up / Supports / Defense use?
  4. Legal but poor decisions?
  5. Terminates vs long-game / draw_max_turns?

No prompt tuning between games in a batch -- if you want to iterate on
the prompt, do it between batches, not within one, or the batch stops
being a fixed-condition read.

There is no RNG in the engine; build_deterministic_opening() is
bit-identical every call. "--paired" therefore means: hold lp / max_turns /
model constant and split the batch across seat A and seat B in one
invocation so flags cannot drift between two separate CLI runs.

Usage:
    export VALLEN_LLM_API_KEY=sk-ant-...
    python3 run_live_playtest.py --n 20 --model <model-id> \
        --lp 800 --max-turns 40 --paired --out report.json

Only reads game state and provider config; never touches engine.py and
never bypasses TurnManager.validate_and_execute() (see llm_adapter.py /
playtest.py for the boundary this respects).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from llm_adapter import ProviderConfig, build_provider, ProviderError
from playtest import run_playtest_batch


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--n", type=int, default=10, help="total games in the batch")
    p.add_argument("--model", type=str, required=True, help="e.g. claude-sonnet-4-20250514")
    p.add_argument("--api-url", type=str, default="https://api.anthropic.com/v1/messages")
    p.add_argument(
        "--api-key-env",
        type=str,
        default="VALLEN_LLM_API_KEY",
        help="env var holding the API key (never pass the key itself as an arg)",
    )
    p.add_argument("--lp", type=int, default=800)
    p.add_argument("--max-turns", type=int, default=40)
    p.add_argument(
        "--llm-side",
        choices=["A", "B"],
        default="B",
        help="LLM seat when not using --paired (ignored when --paired is set)",
    )
    p.add_argument(
        "--paired",
        action="store_true",
        help=(
            "split --n across seat A and seat B under identical lp/max_turns/model "
            "in one invocation; report by_seat instead of a blended total"
        ),
    )
    p.add_argument("--timeout-sec", type=float, default=30.0)
    p.add_argument("--out", type=str, default=None, help="write full JSON report here")
    return p.parse_args()


def _run_one_side(
    *,
    n: int,
    cfg: ProviderConfig,
    provider_name: str,
    lp: int,
    max_turns: int,
    llm_side: str,
) -> Dict[str, Any]:
    provider_factory = lambda: build_provider(cfg)
    return run_playtest_batch(
        n=n,
        llm_provider_factory=provider_factory,
        provider_name=provider_name,
        lp=lp,
        max_turns=max_turns,
        llm_side=llm_side,
    )


def _summary_from_batch(batch: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "batch_size": batch["batch_size"],
        "provider": batch["provider"],
        "llm_side": batch["llm_side"],
        "winners": batch["winners"],
        "terminal_reasons": batch["terminal_reasons"],
        "totals": batch["totals"],
    }


def main() -> int:
    args = parse_args()

    if args.n < 20:
        print(
            "CAVEAT: n < 20 — read this batch for protocol reliability only, "
            "not as a balance or strategy verdict.",
            file=sys.stderr,
        )

    cfg = ProviderConfig(
        provider="anthropic",
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        model=args.model,
        timeout_sec=args.timeout_sec,
    )

    # Fail fast on missing key *before* spending a batch of games on it.
    try:
        build_provider(cfg)
    except ProviderError as e:
        print(
            f"Provider construction failed before any games ran: {e.reason}",
            file=sys.stderr,
        )
        return 1

    provider_name = f"anthropic:{args.model}"

    if args.paired:
        # Split as evenly as possible; odd n gives the extra game to seat A.
        n_a = (args.n + 1) // 2
        n_b = args.n // 2
        if n_a < 1 or n_b < 1:
            print(
                "--paired requires --n >= 2 so each seat gets at least one game.",
                file=sys.stderr,
            )
            return 1

        batch_a = _run_one_side(
            n=n_a, cfg=cfg, provider_name=provider_name,
            lp=args.lp, max_turns=args.max_turns, llm_side="A",
        )
        batch_b = _run_one_side(
            n=n_b, cfg=cfg, provider_name=provider_name,
            lp=args.lp, max_turns=args.max_turns, llm_side="B",
        )

        report: Dict[str, Any] = {
            "mode": "paired",
            "batch_size": args.n,
            "provider": provider_name,
            "lp": args.lp,
            "max_turns": args.max_turns,
            "by_seat": {
                "A": _summary_from_batch(batch_a),
                "B": _summary_from_batch(batch_b),
            },
            "matches_A": batch_a.get("matches", []),
            "matches_B": batch_b.get("matches", []),
        }
        # Console summary keeps seats separate — do not blend winners.
        console = {
            "mode": "paired",
            "batch_size": args.n,
            "provider": provider_name,
            "by_seat": {
                "A": _summary_from_batch(batch_a),
                "B": _summary_from_batch(batch_b),
            },
        }
        print(json.dumps(console, indent=2))
    else:
        batch = _run_one_side(
            n=args.n, cfg=cfg, provider_name=provider_name,
            lp=args.lp, max_turns=args.max_turns, llm_side=args.llm_side,
        )
        report = batch
        print(json.dumps(_summary_from_batch(batch), indent=2))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(
            f"\nFull report written to {args.out}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
