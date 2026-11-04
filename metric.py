# -*- coding: utf-8 -*-
"""
metric.py — 식단 추천 에이전트의 출력이 사용자 제약을 만족하는지 룰 기반으로 평가하는 모듈.

사용 (호출 측 main 에서)
    import json
    from metric import evaluate_all, print_report
    cases   = json.load(open("diet_test_cases_10.json", encoding="utf-8"))
    outputs = json.load(open("agent_outputs.json", encoding="utf-8"))
    report  = evaluate_all(cases, outputs)      # {"summary": {...}, "results": [...]}
    print_report(report)                        # 사람이 읽는 리포트 출력 (선택)
케이스 하나만 보려면 evaluate_case(case, outputs[test_id]).

agent_outputs.json (outputs 의 형식)
    {"T01": {"output": <응답>}, ..., "T10": {"output": <1턴 응답>, "follow_up_output": <2턴 응답>}}
    <응답> = 에이전트 최종 답변 문자열(```json 블록 포함) 또는 {"plan": {...}} dict
    plan   = {"day1_lunch": ["F020"], "day1_dinner": ["F048"], ...}

에이전트가 말한 숫자는 쓰지 않는다. plan 의 food_code 만 꺼내서 food_DB.json 으로 가격·영양을 다시 계산한다.
(tool_calling_function.py 와 독립 — 에이전트 쪽 DB 코드의 버그가 평가에 섞이지 않도록 환산을 따로 구현)

검사 항목 — 해당 제약이 null / 빈 리스트면 그 항목은 검사하지 않는다
    structure : slots_complete, foods_in_db
    constraint: budget_total, budget_per_meal, kcal_per_meal, protein_per_meal, sodium_per_day,
                excluded_food_codes, cuisine_types, excluded_cuisine_types, required_tags, excluded_tags
    safety    : allergens
    revision  : revision_preserved, revision_changed, revision_constraints_kept (follow_up 이 있는 케이스만)
과제 평가축: (1) 요구 충족 = structure+constraint 전부 통과, (2) 멀티턴 = revision, (3) 안전 = safety
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
CATEGORY = {
    "slots_complete": "structure", "foods_in_db": "structure",
    "budget_total": "constraint", "budget_per_meal": "constraint", "kcal_per_meal": "constraint",
    "protein_per_meal": "constraint", "sodium_per_day": "constraint", "excluded_food_codes": "constraint",
    "cuisine_types": "constraint", "excluded_cuisine_types": "constraint",
    "required_tags": "constraint", "excluded_tags": "constraint",
    "allergens": "safety",
    "revision_preserved": "revision", "revision_changed": "revision", "revision_constraints_kept": "revision",
}


def load_db(path=HERE / "food_DB.json"):
    """food_code -> {name, cuisine_type, tags, allergy, price_krw, kcal, protein_g, sodium_mg} (1인분 기준)"""
    db = {}
    for r in json.load(open(path, encoding="utf-8")):
        assert r["nutrition_basis"]["unit"] == r["serving"]["unit"], r["food_code"]
        f = r["serving"]["amount"] / r["nutrition_basis"]["amount"]
        db[r["food_code"]] = {
            "name": r["name"], "cuisine_type": r["cuisine_type"], "tags": r["tags"], "allergy": r["allergy"],
            "price_krw": r["price_krw"],
            "kcal": r["nutrition"]["energy_kcal"] * f,
            "protein_g": r["nutrition"]["protein_g"] * f,
            "sodium_mg": r["nutrition"]["sodium_mg"] * f,
        }
    return db


DB = load_db()


def extract_plan(output):
    """에이전트 출력 -> {slot: [food_code]}. 파싱 실패면 None."""
    if isinstance(output, str):
        blocks = FENCE.findall(output)
        try:
            output = json.loads(blocks[-1] if blocks else output)
        except json.JSONDecodeError:
            return None
    if not isinstance(output, dict):
        return None
    plan = output.get("plan", output)
    if not isinstance(plan, dict):
        return None
    return {s: ([v] if isinstance(v, str) else list(v) if isinstance(v, list) else []) for s, v in plan.items()}


def required_slots(case):
    p = case["user_constraint"]["plan"]
    return [f"day{d}_{m}" for d in range(1, p["days"] + 1) for m in p["meals_per_day"]]


def evaluate_plan(plan, case):
    """plan 하나를 케이스 제약과 비교 -> [{name, category, passed, detail}]"""
    c = case["user_constraint"]["constraints"]
    req = required_slots(case)
    plan = plan or {}
    checks = []

    def add(name, bad, ok_detail="ok"):
        checks.append({"name": name, "category": CATEGORY[name], "passed": not bad,
                       "detail": str(bad) if bad else ok_detail})

    # structure
    missing = [s for s in req if not plan.get(s)]
    extra = [s for s in plan if s not in req]
    add("slots_complete", {"missing": missing, "extra": extra} if missing or extra else None, f"{len(req)} slots")
    unknown = [code for s in req for code in plan.get(s, []) if code not in DB]
    add("foods_in_db", unknown)

    # 이후는 요청된 슬롯 중 DB 에 있는 음식이 하나 이상인 슬롯만 계산
    slots = {s: [DB[code] for code in plan.get(s, []) if code in DB] for s in req}
    slots = {s: recs for s, recs in slots.items() if recs}
    per_meal = lambda key: {s: sum(r[key] for r in recs) for s, recs in slots.items()}  # noqa: E731
    per_day = {}
    for s, v in per_meal("sodium_mg").items():
        per_day[s.split("_")[0]] = per_day.get(s.split("_")[0], 0) + v

    def out_of_range(values, lo, hi):
        return {s: round(v, 1) for s, v in values.items()
                if (lo is not None and v < lo) or (hi is not None and v > hi)}

    def offending(pred):  # 조건에 걸리는 음식 목록 "slot:name"
        return [f"{s}:{r['name']}" for s, recs in slots.items() for r in recs if pred(r)]

    # 예산
    b = c["budget_krw"]
    if b["total_max"] is not None:
        total = sum(per_meal("price_krw").values())
        add("budget_total", f"{total} > {b['total_max']}" if total > b["total_max"] else None, f"{total} <= {b['total_max']}")
    if b["per_meal_max"] is not None:
        add("budget_per_meal", out_of_range(per_meal("price_krw"), None, b["per_meal_max"]))

    # 영양
    pm = c["nutrition"]["per_meal"]
    kc, pr, sd = pm["energy_kcal"], pm["protein_g"], c["nutrition"]["per_day"]["sodium_mg"]
    if kc["min"] is not None or kc["max"] is not None:
        add("kcal_per_meal", out_of_range(per_meal("kcal"), kc["min"], kc["max"]))
    if pr["min"] is not None or pr["max"] is not None:
        add("protein_per_meal", out_of_range(per_meal("protein_g"), pr["min"], pr["max"]))
    if sd["min"] is not None or sd["max"] is not None:
        add("sodium_per_day", out_of_range(per_day, sd["min"], sd["max"]))

    # 안전 (알레르기)
    if c["excluded_allergens"]:
        ex = set(c["excluded_allergens"])
        add("allergens", offending(lambda r: ex & set(r["allergy"])))

    # 제외 음식 / 분류 / 태그
    if c["excluded_food_codes"]:
        ex = set(c["excluded_food_codes"])
        add("excluded_food_codes", [f"{s}:{code}" for s in slots for code in plan[s] if code in ex])
    if c["cuisine_types"]:
        add("cuisine_types", offending(lambda r: r["cuisine_type"] not in c["cuisine_types"]))
    if c["excluded_cuisine_types"]:
        add("excluded_cuisine_types", offending(lambda r: r["cuisine_type"] in c["excluded_cuisine_types"]))
    if c["required_tags"]:  # 끼니마다: 그 끼니 음식들의 태그 합집합에 필수 태그가 모두 있어야 함
        need = set(c["required_tags"])
        add("required_tags", [s for s, recs in slots.items() if not need <= set().union(*(r["tags"] for r in recs))])
    if c["excluded_tags"]:
        ex = set(c["excluded_tags"])
        add("excluded_tags", offending(lambda r: ex & set(r["tags"])))
    return checks


def evaluate_revision(orig, new, case):
    """멀티턴: 유지 슬롯 불변 / 변경 슬롯 변경 / 수정 후에도 원래 제약 유지"""
    exp = case["expected_revision"]
    if new is None:
        return [{"name": n, "category": "revision", "passed": False, "detail": "no follow-up output"}
                for n in ("revision_preserved", "revision_changed", "revision_constraints_kept")]
    orig = orig or {}
    same = lambda s: sorted(orig.get(s, [])) == sorted(new.get(s, []))  # noqa: E731
    kept = [f"{s}:{orig.get(s)}->{new.get(s)}" for s in exp["preserve_slots"] if not same(s)]
    changed = [s for s in exp["change_slots"] if not new.get(s) or same(s)]
    checks = [
        {"name": "revision_preserved", "category": "revision", "passed": not kept, "detail": str(kept) if kept else "ok"},
        {"name": "revision_changed", "category": "revision", "passed": not changed, "detail": str(changed) if changed else "ok"},
    ]
    if exp.get("preserve_all_original_constraints", True):
        failed = [ch["name"] for ch in evaluate_plan(new, case) if not ch["passed"]]
        checks.append({"name": "revision_constraints_kept", "category": "revision", "passed": not failed,
                       "detail": str(failed) if failed else "ok"})
    return checks


def evaluate_case(case, entry):
    """케이스 하나: 파싱 -> 제약 검사 -> (멀티턴이면) 수정 검사 -> 평가축별 집계"""
    entry = entry or {}
    plan = extract_plan(entry.get("output"))
    checks = evaluate_plan(plan, case)
    if "follow_up_query" in case:
        checks += evaluate_revision(plan, extract_plan(entry.get("follow_up_output")), case)
    cat = lambda *ks: [ch["passed"] for ch in checks if ch["category"] in ks]  # noqa: E731
    return {
        "test_id": case["test_id"],
        "plan": plan,
        "checks": checks,
        "requirement_pass": all(cat("structure", "constraint")),            # (1) 요구 충족
        "revision_pass": all(cat("revision")) if cat("revision") else None,  # (2) 멀티턴 수정
        "safety_pass": all(cat("safety")) if cat("safety") else None,        # (3) 안전
        "overall_pass": all(ch["passed"] for ch in checks),
    }


def evaluate_all(cases, outputs):
    """전체 케이스 평가 + 요약 (검사 항목별 통과/해당 수 포함)"""
    results = [evaluate_case(case, outputs.get(case["test_id"])) for case in cases]
    per_check = {}
    for r in results:
        for ch in r["checks"]:
            d = per_check.setdefault(ch["name"], {"passed": 0, "total": 0})
            d["total"] += 1
            d["passed"] += ch["passed"]
    rate = lambda key: [r[key] for r in results if r[key] is not None]  # noqa: E731
    summary = {
        "n_cases": len(results),
        "overall_pass": sum(r["overall_pass"] for r in results),
        "requirement_pass": sum(r["requirement_pass"] for r in results),
        "revision_pass": f"{sum(rate('revision_pass'))}/{len(rate('revision_pass'))}",
        "safety_violations": f"{len(rate('safety_pass')) - sum(rate('safety_pass'))}/{len(rate('safety_pass'))}",
        "per_check": per_check,
    }
    return {"summary": summary, "results": results}


def print_report(report):
    yn = lambda x: "-" if x is None else ("ok" if x else "FAIL")  # noqa: E731
    for r in report["results"]:
        print(f"{r['test_id']}  overall={yn(r['overall_pass'])}  requirement={yn(r['requirement_pass'])}  "
              f"safety={yn(r['safety_pass'])}  revision={yn(r['revision_pass'])}")
        for ch in r["checks"]:
            if not ch["passed"]:
                print(f"      X {ch['name']}: {ch['detail']}")
    s = report["summary"]
    print(f"\nOverall pass          : {s['overall_pass']}/{s['n_cases']}")
    print(f"(1) Requirement pass  : {s['requirement_pass']}/{s['n_cases']}")
    print(f"(2) Multi-turn pass   : {s['revision_pass']}")
    print(f"(3) Allergy violations: {s['safety_violations']}")
    print("\nPer check  passed/applicable")
    for name, d in s["per_check"].items():
        print(f"  {name:<26} {d['passed']}/{d['total']}")

