"""Shared CLI configuration; model changes require no code edits."""
from dataclasses import replace

from config import Settings


def add_options(parser):
    parser.add_argument("--mode", choices=["planner_only", "planner_verifier"])
    parser.add_argument("--model", help="Set both agents: gpt-4o-mini or gpt-5-mini")
    parser.add_argument("--planner-model")
    parser.add_argument("--verifier-model")
    parser.add_argument("--budget-usd", type=float, help="Cumulative application ledger limit (default $15)")
    parser.add_argument("--ledger", help="Shared persistent ledger path")
    parser.add_argument("--max-rounds", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--max-agent-calls", type=int)
    parser.add_argument("--max-turn-calls", type=int)
    parser.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"])


def settings_from_args(args):
    settings = Settings.from_env()
    overrides = {}
    if args.model:
        overrides.update(planner_model=args.model, verifier_model=args.model)
    for field in ("mode", "planner_model", "verifier_model", "budget_usd", "max_rounds",
                  "max_output_tokens", "max_agent_calls", "max_turn_calls", "reasoning_effort"):
        value = getattr(args, field, None)
        if value is not None:
            overrides[field] = value
    if args.ledger:
        overrides["ledger_path"] = args.ledger
    return replace(settings, **overrides)
