"""Run natural-language requests, THEN evaluate against held-out constraints."""
import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator

from budget import BudgetLedger
from cli_options import add_options, settings_from_args
from llm_client import OpenAIClient
from metric import evaluate_all, print_report
from orchestrator import MealChatbot
from schemas import validate_constraints
from session import Session
from tool_calling_function import FOOD_DB, TOOL_SPECS


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_cases(bot, cases, checkpoint=None):
    outputs, initial, traces = {}, {}, {}
    for case in cases:
        test_id = case["test_id"]
        session = Session()
        entry, first = {}, {}
        # Only natural-language strings enter the chatbot. No answer labels,
        # personas, case IDs, expected revisions, or objective descriptions.
        requests = [("output", case["test_query"])]
        if "follow_up_query" in case:
            requests.append(("follow_up_output", case["follow_up_query"]))
        for field, query in requests:
            result = bot.respond(session, query)
            entry[field] = {"plan": result.plan} if result.status == "approved" else None
            first[field] = next(({"plan": r["candidate"]} for r in result.rounds
                                 if "candidate" in r), None)
            print(f"{test_id} {field}: {result.status} ({len(result.rounds)} rounds)", flush=True)
            if result.status != "approved":
                break
        outputs[test_id], initial[test_id] = entry, first
        traces[test_id] = session.results
        if checkpoint:
            checkpoint(outputs, initial, traces)
        if result.status in {"budget_exceeded", "api_error"}:
            break
    return outputs, initial, traces


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_options(parser)
    parser.add_argument("--cases", nargs="+", help="Subset, e.g. T05 T10; default all")
    parser.add_argument("--cases-file", type=Path,
                        default=Path(__file__).with_name("diet_persona_test_cases_10.json"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check-only", action="store_true", help="Validate fixtures/schemas without any API calls")
    parser.add_argument("--evaluate-only", type=Path, help="Score an existing outputs.json without API calls")
    args = parser.parse_args(argv)
    cases = json.loads(args.cases_file.read_text(encoding="utf-8"))
    if args.cases:
        unknown = set(args.cases) - {c["test_id"] for c in cases}
        if unknown:
            parser.error(f"unknown cases: {sorted(unknown)}")
        cases = [c for c in cases if c["test_id"] in args.cases]
    if not cases:
        parser.error("no cases selected")
    for case in cases:
        validate_constraints(case["user_constraint"])
    for spec in TOOL_SPECS:
        Draft202012Validator.check_schema(spec["input_schema"])
    if args.check_only:
        print(f"Offline preflight passed: {len(FOOD_DB)} foods, {len(cases)} cases, "
              f"{len(TOOL_SPECS)} tool schemas. No model invoked; not a model evaluation.")
        return 0
    output_dir = args.output_dir or Path("artifacts") / datetime.now(
        ZoneInfo("Asia/Seoul")).strftime("%Y%m%d-%H%M%S-%f")
    if (output_dir / "report.json").exists() or (output_dir / "outputs.json").exists():
        parser.error("output directory already contains a run; choose a new directory")
    if args.evaluate_only:
        report = evaluate_all(cases, json.loads(args.evaluate_only.read_text(encoding="utf-8")))
        write_json(output_dir / "report.json", report)
        print_report(report)
        return 0
    try:
        settings = settings_from_args(args)
        ledger = BudgetLedger(settings.ledger_path, settings.budget_usd)
        client = OpenAIClient(ledger, settings)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    bot = MealChatbot(client, settings)

    def checkpoint(outputs, initial, traces):
        write_json(output_dir / "outputs.json", outputs)
        write_json(output_dir / "initial_outputs.json", initial)
        write_json(output_dir / "traces.json", traces)
        write_json(output_dir / "usage.json", {"settings": asdict(settings),
                   "run_calls": client.usage, "run_cost_usd": sum(u["cost_usd"] for u in client.usage),
                   "ledger": ledger.summary()})

    outputs, initial, traces = run_cases(bot, cases, checkpoint)
    checkpoint(outputs, initial, traces)
    report = evaluate_all(cases, outputs)
    write_json(output_dir / "report.json", report)
    write_json(output_dir / "initial_report.json", evaluate_all(cases, initial))
    print_report(report)
    print(f"Run cost: ${sum(u['cost_usd'] for u in client.usage):.6f}; artifacts: {output_dir}")
    if any(turn["status"] in {"api_error", "budget_exceeded"}
           for turns in traces.values() for turn in turns):
        return 2
    return 0 if report["summary"]["overall_pass"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
