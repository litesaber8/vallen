"""
Vallen — one-shot live playtest batch: Heuristic vs LLM provider.

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

Providers:
  anthropic  — native Messages API (default URL api.anthropic.com)
  openai     — OpenAI-compatible Chat Completions
  ollama     — OpenAI-compatible against local Ollama
               (default URL http://localhost:11434/v1/chat/completions)

Usage (Ollama):
    # Ollama often needs no key; set a dummy if the provider requires the env var
    export VALLEN_LLM_API_KEY=ollama
    python3 run_live_playtest.py --provider ollama --model gemma4:31b-cloud \
        --n 6 --lp 800 --max-turns 40 --paired --out smoke_report.json

Usage (Anthropic):
    export VALLEN_LLM_API_KEY=sk-ant-...
    python3 run_live_playtest.py --provider anthropic --model <model-id> \
        --n 20 --lp 800 --max-turns 40 --paired --out report.json

Only reads game state and provider config; never touches engine.py and
never bypasses TurnManager.validate_and_execute().
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional, Tuple

from llm_adapter import ProviderConfig, build_provider, ProviderError
from playtest import run_playtest_batch


# (provider_name_for_build, default_api_url)
_PROVIDER_DEFAULTS: Dict[str, Tuple[str, str]] = {
    "anthropic": ("anthropic", "https://api.anthropic.com/v1/messages"),
    "openai": ("openai", "https://api.openai.com/v1/chat/completions"),
    "ollama": ("openai", "http://localhost:11434/v1/chat/completions"),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--n", type=int, default=10, help="total games in the batch")
    p.add_argument("--model", type=str, required=True, help="model id as the provider expects it")
    p.add_argument(
        "--provider",
        choices=sorted(_PROVIDER_DEFAULTS.keys()),
        default="anthropic",
        help="inference backend (ollama uses OpenAI-compatible wire format)",
    )
    p.add_argument(
        "--api-url",
        type=str,
        default=None,
        help="override default API URL for the chosen provider",
    )
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
    p.add_argument("--timeout-sec", type=float, default=60.0)
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

    build_name, default_url = _PROVIDER_DEFAULTS[args.provider]
    api_url = args.api_url or default_url

    cfg = ProviderConfig(
        provider=build_name,
        api_url=api_url,
        api_key_env=args.api_key_env,
        model=args.model,
        timeout_sec=args.timeout_sec,
    )

    # Fail fast on missing key *before* spending a batch of games on it.
    # Ollama accepts any non-empty key string; set VALLEN_LLM_API_KEY=ollama if needed.
    try:
        build_provider(cfg)
    except ProviderError as e:
        print(
            f"Provider construction failed before any games ran: {e.reason}",
            file=sys.stderr,
        )
        if args.provider == "ollama":
            print(
                "Hint: export VALLEN_LLM_API_KEY=ollama  "
                "(Ollama ignores the value but the provider requires the env var.)",
                file=sys.stderr,
            )
        return 1

    provider_name = f"{args.provider}:{args.model}"

    if args.paired:
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
            "api_url": api_url,
            "lp": args.lp,
            "max_turns": args.max_turns,
            "by_seat": {
                "A": _summary_from_batch(batch_a),
                "B": _summary_from_batch(batch_b),
            },
            "matches_A": batch_a.get("matches", []),
            "matches_B": batch_b.get("matches", []),
        }
        console = {
            "mode": "paired",
            "batch_size": args.n,
            "provider": provider_name,
            "api_url": api_url,
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
        print(f"\nFull report written to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
