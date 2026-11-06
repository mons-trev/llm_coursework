"""Compare saved runs and trace evidence, without model calls or runtime feedback."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from metric import DB, evaluate_all, evaluate_plan, evaluate_revision, extract_plan
from schemas import extract_json


ROOT = Path(__file__).resolve().parent
RETURNED = {"generated", "approved"}
FAILURE_GROUPS = {
    "budget_total": "budget_violation", "budget_per_meal": "budget_violation",
    "kcal_per_meal": "nutrition_violation", "protein_per_meal": "nutrition_violation",
    "sodium_per_day": "nutrition_violation", "allergens": "allergy_violation",
    "excluded_food_codes": "exclusion_violation", "excluded_tags": "exclusion_violation",
    "excluded_cuisine_types": "exclusion_violation", "cuisine_types": "cuisine_violation",
    "required_tags": "required_tag_violation", "revision_preserved": "revision_violation",
    "revision_changed": "revision_violation", "revision_constraints_kept": "revision_violation",
    "slots_complete": "structure_violation", "foods_in_db": "structure_violation",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def checks_for(plan, case, previous, follow_up):
    checks = evaluate_plan(plan, case)
    if follow_up:
        checks += evaluate_revision(previous, plan, case)
    return checks


def actual_values(plan):
    """Use the independent evaluator's DB, retaining full numeric precision."""
    slots, days = {}, {}
    keys = ("price_krw", "kcal", "protein_g", "sodium_mg")
    for slot, codes in (plan or {}).items():
        values = {key: sum(DB[c][key] for c in codes if c in DB) for key in keys}
        slots[slot] = values
        daily = days.setdefault(slot.split("_")[0], {key: 0 for key in keys})
        for key in keys:
            daily[key] += values[key]
    return {"slots": slots, "days": days,
            "total": {key: sum(v[key] for v in slots.values()) for key in keys}}


def round_evidence(round_, case, previous, follow_up):
    candidate = round_.get("candidate")
    checks = checks_for(candidate, case, previous, follow_up) if candidate else []
    verifier_tools = round_.get("verifier_tools", [])
    checks_run = [e for e in verifier_tools if e["name"] in {"check_plan", "check_revision"}]
    # A model verdict without actual tool evidence cannot establish a rejection/correction.
    try:
        verdict = extract_json(round_.get("verifier_output") or "null")
    except (ValueError, TypeError):
        verdict = None
    rejected = bool(checks_run and isinstance(verdict, dict) and isinstance(verdict.get("passed"), bool)
                    and round_.get("passed") is False and round_.get("feedback")
                    and round_.get("failure_reason") in {None, "verifier_rejected"})
    interpretation = []
    for event in checks_run:
        constraint = (event.get("arguments") or {}).get("user_constraint")
        if event["name"] == "check_plan" and event["result"].get("passed") is True and constraint:
            interpreted_checks = evaluate_plan(candidate, {"user_constraint": constraint})
            gold_checks = evaluate_plan(candidate, case)
            if all(c["passed"] for c in interpreted_checks) and any(not c["passed"] for c in gold_checks):
                interpretation.append({"interpreted_constraint": constraint,
                                       "gold_failed_checks": [c for c in gold_checks if not c["passed"]]})
        if event["name"] == "check_revision" and event["result"].get("passed") is True:
            missed = [c for c in checks if not c["passed"] and c["name"] in {"revision_preserved", "revision_changed"}]
            if missed:
                interpretation.append({"interpreted_revision": event.get("arguments"), "gold_failed_checks": missed})
    return {"round": round_["round"], "candidate": candidate,
        "independent_checks": checks, "actual_values": actual_values(candidate) if candidate else None,
        "verifier_tools": verifier_tools, "verifier_output": round_.get("verifier_output"),
        "verifier_rejected_with_feedback": rejected, "feedback": round_.get("feedback", []),
        "failure_phase": round_.get("failure_phase"), "failure_reason": round_.get("failure_reason"),
        "error": round_.get("error"), "interpretation_mismatch": interpretation,
        "diagnostic_computations": [e for e in round_.get("planner_tools", []) if e["name"] == "compute_plan"],
        "planner_output": round_.get("planner_output")}


def usage_summary(calls):
    by_role = {}
    for role in sorted({c.get("role", "unknown") for c in calls}):
        rows = [c for c in calls if c.get("role", "unknown") == role]
        by_role[role] = {
            "api_calls": sum(c.get("api_called", True) for c in rows),
            "budget_denials": sum(c.get("status") == "budget_exceeded" for c in rows),
            "input_tokens": sum(c.get("input_tokens") or 0 for c in rows),
            "output_tokens": sum(c.get("output_tokens") or 0 for c in rows),
            "unknown_token_calls": sum(c.get("api_called", True) and c.get("input_tokens") is None for c in rows),
            "cost_usd": sum(c.get("cost_usd", 0) for c in rows),
            "unsettled_reservation_usd": sum(c.get("cost_usd", 0) for c in rows if c.get("cost_is_reservation")),
            "api_seconds": sum(c.get("latency_seconds", 0) for c in rows),
        }
    return by_role


def analyze_run(run_dir, cases_file=None):
    run_dir = Path(run_dir)
    usage = read_json(run_dir / "usage.json")
    manifest = read_json(run_dir / "manifest.json") if (run_dir / "manifest.json").exists() else None
    if manifest and manifest["hashes"]["db"] != hashlib.sha256((ROOT / "food_DB.json").read_bytes()).hexdigest():
        raise ValueError(f"{run_dir}: DB hash differs; independent re-evaluation would be invalid")
    cases_path = run_dir / "cases.json"
    cases = read_json(cases_path if cases_path.exists() else cases_file or ROOT / "diet_persona_test_cases_10.json")
    if manifest:
        cases = [c for c in cases if c["test_id"] in manifest["case_ids"]]
        selected_hash = hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if selected_hash != manifest["hashes"]["selected_cases"]:
            raise ValueError(f"{run_dir}: saved test data hash differs from manifest")
    outputs, traces = read_json(run_dir / "outputs.json"), read_json(run_dir / "traces.json")
    # Recompute scores so saved reports or claims cannot hide output errors.
    report = evaluate_all(cases, outputs)
    stored_report = read_json(run_dir / "report.json")
    warnings = []
    if stored_report != report:
        warnings.append("Saved report differs from independent re-evaluation with the selected test data.")
    settings = usage["settings"]
    mode = settings.get("mode", "planner_verifier")
    if mode not in {"planner_only", "planner_verifier"}:
        raise ValueError(f"{run_dir}: unknown mode")
    if not manifest:
        warnings.append("Legacy record: prompt/code provenance unavailable; excluded from new-run condition groups.")
    metrics = Counter(expected_turns=0, attempted_turns=0, returned=0, not_returned=0,
                      returned_failed=0, returned_passed=0, allergy_applicable_turns=0,
                      allergy_returned=0, allergy_violations=0)
    terminations, failures, taxonomy, evidence, turns = Counter(), Counter(), Counter(), [], []
    for case in cases:
        test_id = case["test_id"]
        entry, saved_turns = outputs.get(test_id, {}), traces.get(test_id, [])
        previous = None
        fields = ["output", "follow_up_output"] if "follow_up_query" in case else ["output"]
        for index, field in enumerate(fields):
            turn = saved_turns[index] if index < len(saved_turns) else {}
            candidate = extract_plan(entry.get(field))
            returned = candidate is not None
            expected_status = "generated" if mode == "planner_only" else "approved"
            if returned and (turn.get("status") != expected_status or turn.get("mode", mode) != mode):
                raise ValueError(f"{run_dir}/{test_id}/{field}: output and saved mode/status disagree")
            checks = checks_for(candidate, case, previous, index > 0)
            failed = [c for c in checks if not c["passed"]]
            metrics.update(expected_turns=1, attempted_turns=bool(turn), returned=returned,
                           not_returned=not returned, returned_failed=bool(returned and failed),
                           returned_passed=bool(returned and not failed))
            applicable = bool(case["user_constraint"]["constraints"]["excluded_allergens"])
            metrics["allergy_applicable_turns"] += applicable
            metrics["allergy_returned"] += applicable and returned
            metrics["allergy_violations"] += returned and any(c["name"] == "allergens" and not c["passed"] for c in checks)
            reason = turn.get("termination_reason") or turn.get("status", "not_attempted")
            terminations[reason] += 1
            for check in failed:
                failures[check["name"]] += 1
                if returned:
                    taxonomy[FAILURE_GROUPS[check["name"]]] += 1
            rounds = [round_evidence(r, case, r.get("baseline", previous), index > 0)
                      for r in turn.get("rounds", [])]
            labels = set()
            if turn and not any(r["candidate"] for r in rounds):
                labels.add("candidate_not_submitted")
            for r in rounds:
                if r["failure_reason"] in {"technical_execution_failure", "call_limit"}:
                    labels.add(r["failure_reason"])
                if r["interpretation_mismatch"]:
                    labels.add("verifier_constraint_interpretation_mismatch")
                if r["candidate"] and r["independent_checks"]:
                    valid = all(c["passed"] for c in r["independent_checks"])
                    if valid and r["verifier_rejected_with_feedback"]:
                        labels.add("correct_candidate_rejected")
                    if not valid and r["verifier_rejected_with_feedback"]:
                        if not returned:
                            labels.add("wrong_candidate_blocked")
                        if returned and not failed and candidate != r["candidate"] and any(
                            later["round"] > r["round"] and later["candidate"] == candidate
                            and all(c["passed"] for c in later["independent_checks"]) for later in rounds):
                            labels.add("wrong_candidate_repaired_after_verifier_feedback")
            if returned and failed and turn.get("status") == "approved":
                labels.add("wrong_candidate_approved")
            if reason in {"budget_exceeded", "api_error"}:
                labels.add(reason)
            taxonomy.update(labels)
            item = {"case_id": test_id, "turn": index + 1, "returned": returned,
                    "passed": returned and not failed, "status": turn.get("status", "not_attempted"),
                    "termination_reason": reason, "failed_checks": failed,
                    "elapsed_seconds": turn.get("elapsed_seconds"),
                    "model_calls": turn.get("model_calls"), "categories": sorted(labels)}
            turns.append(item)
            if failed or labels or any(r["feedback"] or r["interpretation_mismatch"] for r in rounds):
                evidence.append({**item, "user_requests": [case["test_query"]] + ([case["follow_up_query"]] if index else []),
                    "gold_constraint": case["user_constraint"], "expected_revision": case.get("expected_revision") if index else None,
                    "baseline": previous, "rounds": rounds, "final_returned_plan": candidate,
                    "final_actual_values": actual_values(candidate) if returned else None})
            if returned:
                previous = candidate
    roles = usage_summary(usage.get("run_calls", []))
    totals = {key: sum(row[key] for row in roles.values()) for key in
              ("api_calls", "input_tokens", "output_tokens", "cost_usd", "unknown_token_calls",
               "unsettled_reservation_usd", "api_seconds")}
    times = [t["elapsed_seconds"] for t in turns if t["elapsed_seconds"] is not None]
    metrics.update(api_calls=totals["api_calls"], input_tokens=totals["input_tokens"], output_tokens=totals["output_tokens"])
    condition = {"hashes": manifest["hashes"], "settings": {k: v for k, v in settings.items() if k not in {"mode", "ledger_path"}}} if manifest else {"legacy_path": str(run_dir)}
    signature = hashlib.sha256(json.dumps(condition, sort_keys=True).encode()).hexdigest()[:16]
    return {"run_dir": str(run_dir), "model": settings["planner_model"], "verifier_model": settings["verifier_model"],
        "mode": mode, "repetition": manifest["repetition"] if manifest else None,
        "kind": manifest.get("kind") if manifest else "legacy", "conditions": signature,
        "summary": report["summary"], "case_results": report["results"], "turn_metrics": dict(metrics),
        "turns": turns, "termination_counts": dict(terminations), "failed_checks": dict(failures),
        "error_categories": dict(taxonomy), "cost_usd": totals["cost_usd"], "roles": roles,
        "usage_totals": totals, "turn_seconds_total": sum(times) if times else None,
        "turn_seconds_mean": mean(times) if times else None, "timed_turns": len(times),
        "warnings": warnings, "evidence": evidence}


def aggregate(runs):
    groups = defaultdict(list)
    for run in runs:
        groups[(run["model"], run["mode"], run["conditions"], run["kind"])].append(run)
    results = []
    for (model, mode, conditions, kind), rows in sorted(groups.items()):
        values = defaultdict(list)
        for r in rows:
            s, m = r["summary"], r["turn_metrics"]
            values["overall_rate"].append(s["overall_pass"] / s["n_cases"])
            values["requirement_rate"].append(s["requirement_pass"] / s["n_cases"])
            num, den = map(int, s["revision_pass"].split("/"))
            if den:
                values["revision_rate"].append(num / den)
            for key in ("returned", "not_returned", "returned_failed", "allergy_violations", "api_calls", "input_tokens", "output_tokens"):
                values[key].append(m[key])
            values["cost_usd"].append(r["cost_usd"])
            if r["turn_seconds_total"] is not None:
                values["turn_seconds_total"].append(r["turn_seconds_total"])
        results.append({"model": model, "mode": mode, "conditions": conditions, "kind": kind,
                        "runs": len(rows), "repetitions": [r["repetition"] for r in rows],
                        "statistics": {k: {"mean": mean(v), "min": min(v), "max": max(v), "n": len(v)} for k, v in values.items()}})
    return results


def markdown_report(result):
    lines = ["# Planner ablation 저장 결과 비교", "",
        "각 행은 독립 실행입니다. initial_outputs는 첫 후보 진단이며 Planner-only 실행으로 취급하지 않습니다.",
        "알레르기 위반은 반환한 식단에서만 집계합니다. 미반환은 성공이 아니며 분모에 별도로 남습니다.",
        "오류 사례의 수정·차단 표시는 같은 실행 안의 실제 검사와 피드백에 근거합니다.", "",
        "| 모델 | 모드 | 반복 | Overall | Requirement | Revision | 반환/예정 턴 | 반환 실패/반환 | 알레르기 위반/반환/해당 턴 | 호출 | 입력/출력 토큰 | 비용 USD | 턴 합계 초 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in result["runs"]:
        s, m = r["summary"], r["turn_metrics"]
        seconds = f"{r['turn_seconds_total']:.2f}" if r["turn_seconds_total"] is not None else "미기록"
        lines.append(f"| {r['model']} | {r['mode']} | {r['repetition']} | {s['overall_pass']}/{s['n_cases']} | {s['requirement_pass']}/{s['n_cases']} | {s['revision_pass']} | {m['returned']}/{m['expected_turns']} | {m['returned_failed']}/{m['returned']} | {m['allergy_violations']}/{m['allergy_returned']}/{m['allergy_applicable_turns']} | {m['api_calls']} | {m['input_tokens']}/{m['output_tokens']} | {r['cost_usd']:.6f} | {seconds} |")
    for r in result["runs"]:
        for warning in r["warnings"]:
            lines.extend(["", f"주의 ({r['run_dir']}): {warning}"])
    lines.extend(["", "## 반복 평균과 범위", "", "동일 conditions 그룹 안에서만 합산합니다. 코드·설정·DB·프롬프트·테스트 해시가 다른 그룹은 별도입니다."])
    for group in result["groups"]:
        lines.extend(["", f"### {group['model']} / {group['mode']} / {group['conditions']} ({group['kind']}, n={group['runs']})", "",
                      "| 지표 | 평균 | 최소 | 최대 |", "|---|---:|---:|---:|"])
        for key, stat in group["statistics"].items():
            lines.append(f"| {key} | {stat['mean']:.6f} | {stat['min']:.6f} | {stat['max']:.6f} |")
    lines.extend(["", "## 케이스별 결과", "", "| 실행 | 케이스 | Overall | 실패 검사 |", "|---|---|---|---|"])
    for r in result["runs"]:
        for case in r["case_results"]:
            bad = ", ".join(c["name"] for c in case["checks"] if not c["passed"]) or "없음"
            lines.append(f"| {r['run_dir']} | {case['test_id']} | {case['overall_pass']} | {bad} |")
    for r in result["runs"]:
        lines.extend(["", f"### {r['run_dir']} 종료·실패·역할별 사용량", "", "```json",
                      json.dumps({k: r[k] for k in ("termination_counts", "failed_checks", "error_categories", "roles")}, ensure_ascii=False, indent=2), "```"])
        # Full evidence remains in JSON; one representative per category avoids repetition.
        seen = set()
        for e in r["evidence"]:
            categories = set(e["categories"]) or {"returned_constraint_failure" if e["returned"] else "not_returned"}
            if categories <= seen:
                continue
            seen.update(categories)
            lines.extend(["", f"### 증거: {e['case_id']} 턴 {e['turn']} — {', '.join(sorted(categories))}", "",
                          "중간 compute_plan은 진단용이며 최종 반환 식단으로 취급하지 않습니다.", "", "```json",
                          json.dumps(e, ensure_ascii=False, indent=2), "```"])
    lines.extend(["", "독립 실행 간 성적 차이만으로 Verifier가 특정 오류를 수정했다고 결론내릴 수 없습니다.",
                  "검사 인자와 정답 판정의 불일치는 기록된 제약 해석의 차이이며 사용자 언어의 해석에는 추가 검토가 필요합니다.",
                  "호출 역할이 없는 과거 기록은 unknown으로 남기며 모델명으로 역할을 추정하지 않습니다.",
                  "API 오류 비용에는 미정산 예약액이 포함될 수 있고, 토큰 미상 호출은 0토큰 성공으로 해석하지 않습니다.",
                  "scripted_offline_test의 수치·시간은 테스트 대역의 동작 확인이며 실제 모델 성능·응답 시간·API 비용이 아닙니다.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="Saved run directories")
    parser.add_argument("--cases-file", type=Path, help="Fallback for legacy runs without cases.json")
    parser.add_argument("--output-dir", type=Path, required=True, help="New comparison directory")
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("comparison directory already exists; choose a new directory")
    try:
        runs = [analyze_run(p, args.cases_file) for p in args.runs]
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    result = {"runs": runs, "groups": aggregate(runs)}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "comparison.md").write_text(markdown_report(result), encoding="utf-8")
    print(f"Saved offline comparison: {args.output_dir} ({len(runs)} runs; no API calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
