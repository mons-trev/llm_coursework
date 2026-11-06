"""Interactive meal planner, with optional local save/resume."""
import argparse
import json
from pathlib import Path

from budget import BudgetLedger
from cli_options import add_options, settings_from_args
from llm_client import OpenAIClient
from orchestrator import MealChatbot
from run_eval import write_json
from session import Session


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_options(parser)
    parser.add_argument("--session-file", type=Path, help="Optional saved transcript/plan to resume")
    parser.add_argument("--query", help="Run one request instead of an interactive session")
    parser.add_argument("--debug", action="store_true", help="Show model and internal review status")
    args = parser.parse_args(argv)
    try:
        settings = settings_from_args(args)
        ledger = BudgetLedger(settings.ledger_path, settings.budget_usd)
        client = OpenAIClient(ledger, settings)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    bot, session = MealChatbot(client, settings), Session()
    if args.session_file and args.session_file.exists():
        session = Session(**json.loads(args.session_file.read_text(encoding="utf-8")))
    print("식단 도우미")
    print("예산, 알레르기, 음식 선호 등을 포함해 원하는 식단을 말씀해 주세요.")
    print("이어서 '점심은 그대로 두고 저녁만 바꿔줘'처럼 수정할 수 있어요.")
    print("/new 새 대화 · /quit 종료")
    if args.debug:
        print(f"Planner={settings.planner_model}, Verifier={settings.verifier_model}")
    while True:
        try:
            query = args.query if args.query is not None else input("\n사용자> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query.strip() == "/quit":
            break
        if query.strip() == "/usage":
            print(json.dumps(ledger.summary(), ensure_ascii=False))
            if args.query is not None:
                break
            continue
        if query.strip() == "/new":
            session = Session()
            if args.query is not None:
                break
            continue
        if not query.strip():
            if args.query is not None:
                parser.error("query cannot be empty")
            continue
        print("\n식단을 찾고 요청하신 조건을 확인하고 있어요...", flush=True)
        result = bot.respond(session, query)
        print(f"\n식단 도우미> {result.answer}")
        if args.debug:
            print(f"[상태: {result.status}, 검수 라운드: {len(result.rounds)}]")
        if args.session_file:
            # Replay original messages on resume, not opaque tool/reasoning IDs.
            write_json(args.session_file, {"user_turns": session.user_turns,
                       "accepted_plan": session.accepted_plan,
                       "accepted_at_turn": session.accepted_at_turn,
                       "results": session.results})
        if args.query is not None or result.status in {"budget_exceeded", "api_error"}:
            return 0 if result.status == "approved" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
