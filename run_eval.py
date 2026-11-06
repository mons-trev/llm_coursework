"""Run natural-language requests, THEN evaluate against held-out constraints."""
import argparse
import hashlib
import json
import subprocess
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


ROOT = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(value).hexdigest()


def provenance(settings, cases_file, cases, repetition):
    """Capture comparison conditions locally, without reading credentials."""
    from agents import openai_tools
    from budget import RATES
    from tool_calling_function import PLANNER_SYSTEM_PROMPT, PLANNER_TOOLS, VERIFIER_SYSTEM_PROMPT

    def git(*args):
        result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True)
        return result.stdout.strip()

    files = sorted([*ROOT.glob("*.py"), *ROOT.glob("tests/*.py")])
    file_hashes = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in files}
    encoded = lambda obj: json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    try:
        status = git("status", "--porcelain")
        source = {"commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
                  "dirty": bool(status), "status": status}
    except (OSError, subprocess.CalledProcessError):
        source = {"commit": None, "branch": None, "dirty": None}
    return {"schema_version": 1, "kind": "live_model_evaluation", "mode": settings.mode,
        "repetition": repetition, "settings": asdict(settings),
        "started_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(), "source": source,
        "hashes": {"db": digest((ROOT / "food_DB.json").read_bytes()),
                   "test_file": digest(cases_file.read_bytes()), "selected_cases": digest(encoded(cases)),
                   "planner_prompt": digest(PLANNER_SYSTEM_PROMPT.encode("utf-8")),
                   "verifier_prompt": digest(VERIFIER_SYSTEM_PROMPT.encode("utf-8")),
                   "planner_tools": digest(encoded(openai_tools(PLANNER_TOOLS))),
                   "source_files": file_hashes},
        "case_ids": [c["test_id"] for c in cases], "rates_usd_per_million": RATES,
        "cases_file": str(cases_file.resolve())}


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
            bot.trace_context = {"case_id": test_id, "output_field": field}
            result = bot.respond(session, query)
            returned = result.status in {"approved", "generated"} and result.plan is not None
            entry[field] = {"plan": result.plan} if returned else None
            first[field] = next(({"plan": r["candidate"]} for r in result.rounds
                                 if "candidate" in r), None)
            print(f"{test_id} {field}: {result.status} ({len(result.rounds)} rounds)", flush=True)
            if not returned:
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
    parser.add_argument("--repetition", type=int, default=1, help="Recorded repetition number; use a fresh directory")
    parser.add_argument("--check-only", action="store_true", help="Validate fixtures/schemas without any API calls")
    parser.add_argument("--evaluate-only", type=Path, help="Score an existing outputs.json without API calls")
    args = parser.parse_args(argv)
    try:
        settings = settings_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.repetition < 1:
        parser.error("repetition must be positive")
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
    if output_dir.exists():
        parser.error("output directory already exists; choose a new directory")
    if args.evaluate_only:
        report = evaluate_all(cases, json.loads(args.evaluate_only.read_text(encoding="utf-8")))
        write_json(output_dir / "report.json", report)
        print_report(report)
        return 0
    try:
        ledger = BudgetLedger(settings.ledger_path, settings.budget_usd)
        client = OpenAIClient(ledger, settings)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    bot = MealChatbot(client, settings)
    # Exclusive creation also protects incomplete runs and concurrent invocations.
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = provenance(settings, args.cases_file, cases, args.repetition)
    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "cases.json", cases)  # Held-out evaluation snapshot; never sent to bot.

    def checkpoint(outputs, initial, traces):
        write_json(output_dir / "outputs.json", outputs)
        write_json(output_dir / "initial_outputs.json", initial)
        write_json(output_dir / "traces.json", traces)
        write_json(output_dir / "report.json", evaluate_all(cases, outputs))
        write_json(output_dir / "initial_report.json", evaluate_all(cases, initial))
        write_json(output_dir / "usage.json", {"settings": asdict(settings),
                   "mode": settings.mode, "repetition": args.repetition,
                   "run_calls": client.usage, "run_cost_usd": sum(u["cost_usd"] for u in client.usage),
                   "ledger": ledger.summary()})

    outputs, initial, traces = run_cases(bot, cases, checkpoint)
    checkpoint(outputs, initial, traces)
    report = evaluate_all(cases, outputs)
    write_json(output_dir / "report.json", report)
    write_json(output_dir / "initial_report.json", evaluate_all(cases, initial))
    manifest["finished_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    write_json(output_dir / "manifest.json", manifest)
    print_report(report)
    print(f"Run cost: ${sum(u['cost_usd'] for u in client.usage):.6f}; artifacts: {output_dir}")
    if any(turn["status"] in {"api_error", "budget_exceeded"}
           for turns in traces.values() for turn in turns):
        return 2
    return 0 if report["summary"]["overall_pass"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
