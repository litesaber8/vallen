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

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 run_live_playtest.py --n 20 --model claude-sonnet-5 \
        --lp 800 --max-turns 40 --llm-side B --out report.json

Only reads game state and provider config; never touches engine.py and
never bypasses TurnManager.validate_and_execute() (see llm_adapter.py /
playtest.py for the boundary this respects).
"""

from __future__ import annotations

import argparse
import json
import sys

from llm_adapter import ProviderConfig, build_provider, ProviderError
from playtest import run_playtest_batch


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=10, help="number of games in the batch")
    p.add_argument("--model", type=str, required=True, help="e.g. claude-sonnet-5")
    p.add_argument("--api-url", type=str, default="https://api.anthropic.com/v1/messages")
    p.add_argument("--api-key-env", type=str, default="ANTHROPIC_API_KEY",
                   help="env var holding the API key (never pass the key itself as an arg)")
    p.add_argument("--lp", type=int, default=800)
    p.add_argument("--max-turns", type=int, default=40)
    p.add_argument("--llm-side", choices=["A", "B"], default="B",
                   help="which seat the LLM plays; alternate across batches to control for seat effects")
    p.add_argument("--timeout-sec", type=float, default=30.0)
    p.add_argument("--out", type=str, default=None, help="write full JSON report here")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    cfg = ProviderConfig(
        provider="anthropic",
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        model=args.model,
        timeout_sec=args.timeout_sec,
    )

    # Fail fast on missing/bad key *before* spending a batch of games on it --
    # build_provider raises ProviderError at construction if the env var is unset.
    try:
        build_provider(cfg)
    except ProviderError as e:
        print(f"Provider construction failed before any games ran: {e.reason}", file=sys.stderr)
        return 1

    # A fresh provider instance per game (matches run_playtest_batch's factory
    # contract) so per-request state (if any future provider needs it) never
    # leaks across matches in the batch.
    provider_factory = lambda: build_provider(cfg)

    batch = run_playtest_batch(
        n=args.n,
        llm_provider_factory=provider_factory,
        provider_name=f"anthropic:{args.model}",
        lp=args.lp,
        max_turns=args.max_turns,
        llm_side=args.llm_side,
    )

    summary = {
        "batch_size": batch["batch_size"],
        "provider": batch["provider"],
        "llm_side": batch["llm_side"],
        "winners": batch["winners"],
        "terminal_reasons": batch["terminal_reasons"],
        "totals": batch["totals"],
    }
    print(json.dumps(summary, indent=2))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(batch, f, indent=2)
        print(f"\nFull report ({args.n} matches, action logs included) written to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
