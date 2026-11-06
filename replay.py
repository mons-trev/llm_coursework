"""Display saved experimental conversations, explicitly labeled as a replay."""
import argparse
import json
import sys
from pathlib import Path

from presentation import render_plan
from schemas import extract_plan


ROOT = Path(__file__).resolve().parent


def saved_conversation(run_dir, case):
    run_dir = Path(run_dir)
    entries = json.loads((run_dir / "outputs.json").read_text(encoding="utf-8"))
    traces = json.loads((run_dir / "traces.json").read_text(encoding="utf-8"))
    usage = json.loads((run_dir / "usage.json").read_text(encoding="utf-8"))
    entry = entries[case["test_id"]]
    messages, previous = [], None
    fields = [("output", "test_query")]
    if "follow_up_query" in case:
        fields.append(("follow_up_output", "follow_up_query"))
    for index, (output_field, query_field) in enumerate(fields):
        if query_field not in case:
            continue
        messages.append(("사용자", case[query_field]))
        output = entry.get(output_field)
        if not output:
            messages.append(("식단 도우미", "이 실험에서는 조건을 만족하는 식단을 반환하지 못했어요."))
            break
        plan = extract_plan(output)
        turns = traces.get(case["test_id"], [])
        turn = turns[index] if index < len(turns) else {}
        if turn.get("status") != "approved":
            raise ValueError("승인된 응답 기록이 아니어서 성공한 대화로 재생할 수 없습니다.")
        checks = [event for round_ in turn.get("rounds", [])
                  for event in round_.get("verifier_tools", []) if event["name"] == "check_plan"]
        constraint = checks[-1]["arguments"]["user_constraint"] if checks else None
        messages.append(("식단 도우미", render_plan(plan, previous_plan=previous,
                                                user_constraint=constraint)))
        previous = plan
    return usage["settings"], messages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=ROOT / "artifacts/5-mini-ko-strict")
    parser.add_argument("--case", default="T10")
    parser.add_argument("--cases-file", type=Path, default=ROOT / "diet_persona_test_cases_10.json")
    parser.add_argument("--step", action="store_true", help="Pause before each saved chatbot response")
    parser.add_argument("--export", type=Path, help="Save the displayed conversation as UTF-8 text")
    args = parser.parse_args(argv)
    if args.step and not sys.stdin.isatty():
        parser.error("--step 은 직접 Enter 를 누를 수 있는 터미널에서 실행하세요.")
    try:
        cases = json.loads(args.cases_file.read_text(encoding="utf-8"))
        case = next((c for c in cases if c["test_id"] == args.case), None)
        if case is None:
            raise ValueError(f"해당 테스트가 없습니다: {args.case}")
        settings, messages = saved_conversation(args.run_dir, case)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    header = ("과거 실험 기록 재생 — 실시간 생성이 아닙니다.\n"
              "메뉴와 수치는 원본 실험 결과이며, 응답 표현은 현재 표시 함수로 변환했습니다.\n"
              f"모델: {settings['planner_model']} / {settings['verifier_model']} · 테스트: {args.case}\n"
              f"원본 기록: {args.run_dir}")
    transcript = header + "\n\n" + "\n\n".join(f"{role}> {text}" for role, text in messages) + "\n"
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(transcript, encoding="utf-8")
    print(header)
    try:
        for role, text in messages:
            if args.step and role == "식단 도우미":
                input("\nEnter 를 누르면 저장된 응답을 표시합니다.")
            print(f"\n{role}> {text}")
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
