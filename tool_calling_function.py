# -*- coding: utf-8 -*-
"""
tool_calling_function.py — planner / verifier 에이전트가 tool calling 으로 호출하는 food DB 도구.

규약 (metric.py 와 동일)
* 영양값은 1인분(serving) 기준: nutrition × serving.amount / nutrition_basis.amount
  food_DB.json 의 nutrition 은 100 g / 100 ml 당 값이다. (food_DB_metadata.json 의 nutrition_basis_rule)
* price_krw 는 serving 하나의 가격이므로 환산하지 않는다.
* 슬롯 이름은 day{N}_{meal} (day1_lunch, day2_dinner ...), 슬롯 값은 food_code 리스트(합산).

에이전트별 도구
    planner  : search_foods, compute_plan        (PLANNER_TOOLS)
    verifier : check_plan                        (VERIFIER_TOOLS)
사용
    tools  = [t for t in TOOL_SPECS if t["name"] in PLANNER_TOOLS]   # LLM 에 넘김
    result = dispatch_tool(name, input)                               # tool_use 실행 -> tool_result
최종 답변은 PLANNER_SYSTEM_PROMPT 의 JSON 형식을 따르고, metric.py 가 그 JSON 을 읽는다.
"""
import json
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "food_DB.json"


def load_food_db(path=DB_PATH):
    """food_DB.json -> {food_code: {...}}. kcal / protein_g / sodium_mg 는 1인분 기준으로 환산."""
    db = {}
    for r in json.load(open(path, encoding="utf-8")):
        assert r["nutrition_basis"]["unit"] == r["serving"]["unit"], r["food_code"]
        f = r["serving"]["amount"] / r["nutrition_basis"]["amount"]
        db[r["food_code"]] = {
            "food_code": r["food_code"],
            "name": r["name"],
            "cuisine_type": r["cuisine_type"],
            "tags": r["tags"],
            "allergy": r["allergy"],
            "price_krw": r["price_krw"],
            "kcal": round(r["nutrition"]["energy_kcal"] * f, 1),
            "protein_g": round(r["nutrition"]["protein_g"] * f, 1),
            "sodium_mg": round(r["nutrition"]["sodium_mg"] * f, 1),
        }
    return db


FOOD_DB = load_food_db()


def _codes(v):
    """슬롯 값 정규화: "F020" -> ["F020"], 리스트는 그대로, 그 외는 []"""
    return [v] if isinstance(v, str) else list(v) if isinstance(v, list) else []


# ---------------------------------------------------------------- planner 도구
def search_foods(cuisine_types=None, excluded_cuisine_types=None, excluded_allergens=None,
                 excluded_food_codes=None, required_tags=None, excluded_tags=None,
                 kcal_min=None, kcal_max=None, protein_min=None, protein_max=None,
                 sodium_max=None, price_max=None):
    """조건에 맞는 음식 목록 (1인분 기준, 가격 오름차순). None / 빈 리스트인 조건은 적용하지 않는다."""
    out = []
    for r in FOOD_DB.values():
        if excluded_food_codes and r["food_code"] in excluded_food_codes:
            continue
        if cuisine_types and r["cuisine_type"] not in cuisine_types:
            continue
        if excluded_cuisine_types and r["cuisine_type"] in excluded_cuisine_types:
            continue
        if excluded_allergens and set(excluded_allergens) & set(r["allergy"]):
            continue
        if required_tags and not set(required_tags) <= set(r["tags"]):
            continue
        if excluded_tags and set(excluded_tags) & set(r["tags"]):
            continue
        if kcal_min is not None and r["kcal"] < kcal_min:
            continue
        if kcal_max is not None and r["kcal"] > kcal_max:
            continue
        if protein_min is not None and r["protein_g"] < protein_min:
            continue
        if protein_max is not None and r["protein_g"] > protein_max:
            continue
        if sodium_max is not None and r["sodium_mg"] > sodium_max:
            continue
        if price_max is not None and r["price_krw"] > price_max:
            continue
        out.append(r)
    return sorted(out, key=lambda r: r["price_krw"])


def compute_plan(plan):
    """{slot: [food_code]} -> 끼니별 / 일별 / 전체 합계 (price_krw, kcal, protein_g, sodium_mg)"""
    keys = ("price_krw", "kcal", "protein_g", "sodium_mg")
    slots, days, total, unknown = {}, {}, dict.fromkeys(keys, 0), []
    for slot, codes in plan.items():
        s = dict.fromkeys(keys, 0)
        for code in _codes(codes):
            if code not in FOOD_DB:
                unknown.append(code)
                continue
            for k in keys:
                s[k] += FOOD_DB[code][k]
        slots[slot] = s
        d = days.setdefault(slot.split("_")[0], dict.fromkeys(keys, 0))
        for k in keys:
            d[k] += s[k]
            total[k] += s[k]
    return {"slots": slots, "days": days, "total": total, "unknown_codes": unknown}


# ---------------------------------------------------------------- verifier 도구
def check_plan(plan, user_constraint):
    """plan 이 user_constraint 를 만족하는지 룰로 검사 -> {"passed": bool, "violations": [str, ...]}

    user_constraint 는 diet_test_cases_10.json 의 user_constraint 와 같은 형식이다. verifier LLM 이
    사용자 질문(멀티턴이면 전체 대화)에서 직접 채운다. 검사 내용은 metric.py 의 evaluate_plan 과 같지만
    평가 코드와 섞이지 않도록 따로 구현한다.
    """
    p, c = user_constraint["plan"], user_constraint["constraints"]
    req = [f"day{d}_{m}" for d in range(1, p["days"] + 1) for m in p["meals_per_day"]]
    plan = {s: _codes(v) for s, v in plan.items()}
    v = []

    missing = [s for s in req if not plan.get(s)]
    extra = [s for s in plan if s not in req]
    if missing:
        v.append(f"missing slots: {missing}")
    if extra:
        v.append(f"unrequested slots: {extra}")
    unknown = [x for s in req for x in plan.get(s, []) if x not in FOOD_DB]
    if unknown:
        v.append(f"food codes not in DB: {unknown}")

    slots = {s: [FOOD_DB[x] for x in plan.get(s, []) if x in FOOD_DB] for s in req}
    slots = {s: recs for s, recs in slots.items() if recs}
    per_meal = lambda k: {s: sum(r[k] for r in recs) for s, recs in slots.items()}  # noqa: E731
    per_day = {}
    for s, x in per_meal("sodium_mg").items():
        per_day[s.split("_")[0]] = per_day.get(s.split("_")[0], 0) + x

    def rng(label, values, lo, hi):
        bad = {s: round(x, 1) for s, x in values.items() if (lo is not None and x < lo) or (hi is not None and x > hi)}
        if bad:
            v.append(f"{label} out of range [{lo}, {hi}]: {bad}")

    def foods(label, pred):
        bad = [f"{s}:{r['name']}({r['food_code']})" for s, recs in slots.items() for r in recs if pred(r)]
        if bad:
            v.append(f"{label}: {bad}")

    b, pm, sd = c["budget_krw"], c["nutrition"]["per_meal"], c["nutrition"]["per_day"]["sodium_mg"]
    total = sum(per_meal("price_krw").values())
    if b["total_max"] is not None and total > b["total_max"]:
        v.append(f"total price {total} > {b['total_max']}")
    if b["per_meal_max"] is not None:
        rng("price per meal", per_meal("price_krw"), None, b["per_meal_max"])
    rng("kcal per meal", per_meal("kcal"), pm["energy_kcal"]["min"], pm["energy_kcal"]["max"])
    rng("protein per meal", per_meal("protein_g"), pm["protein_g"]["min"], pm["protein_g"]["max"])
    rng("sodium per day", per_day, sd["min"], sd["max"])
    if c["excluded_allergens"]:
        foods("contains excluded allergen", lambda r: set(c["excluded_allergens"]) & set(r["allergy"]))
    if c["excluded_food_codes"]:
        foods("excluded food code", lambda r: r["food_code"] in c["excluded_food_codes"])
    if c["cuisine_types"]:
        foods("cuisine not allowed", lambda r: r["cuisine_type"] not in c["cuisine_types"])
    if c["excluded_cuisine_types"]:
        foods("excluded cuisine", lambda r: r["cuisine_type"] in c["excluded_cuisine_types"])
    if c["required_tags"]:  # 끼니마다: 그 끼니 음식 태그의 합집합에 필수 태그가 모두 있어야 함
        need = set(c["required_tags"])
        bad = [s for s, recs in slots.items() if not need <= set().union(*(r["tags"] for r in recs))]
        if bad:
            v.append(f"required tags {sorted(need)} missing in: {bad}")
    if c["excluded_tags"]:
        foods("has excluded tag", lambda r: set(c["excluded_tags"]) & set(r["tags"]))
    return {"passed": not v, "violations": v}


# ---------------------------------------------------------------- LLM 연결
# TOOL_SPECS 설명과 SYSTEM_PROMPT 는 LLM 이 읽는 텍스트다. 한국어로 쓰되 식별자 / JSON 키는 그대로 두고,
# 사용자 질문이 영어이므로 DB 어휘의 영어 병기(새우 (shrimp) 등)도 남겨 둔다.
_LIST = {"type": "array", "items": {"type": "string"}}
_NUM = {"type": "number"}

TOOL_SPECS = [
    {
        "name": "search_foods",
        "description": (
            "조건에 맞는 음식을 food DB 에서 검색합니다. 영양 필터는 1인분(serving) 기준이고, 결과는 가격 오름차순으로 "
            "정렬됩니다. 각 항목은 food_code, name, cuisine_type, tags, allergy, price_krw, kcal, protein_g, sodium_mg 를 "
            "가집니다. 사용자의 알레르기 / 제외 조건은 반드시 excluded_allergens / excluded_food_codes 로 넘겨서 "
            "해당 음식이 후보에 나오지 않게 하세요. "
            "cuisine_type 값: 한식 (Korean), 중식 (Chinese), 일식 (Japanese), 양식 (Western), 동남아식 (Southeast Asian). "
            "allergy 값: 밀 (wheat), 우유 (milk), 대두 (soy), 알류 (egg), 돼지고기 (pork), 쇠고기 (beef), "
            "닭고기 (chicken), 새우 (shrimp), 생선 (fish), 오징어 (squid), 조개류 (shellfish), 주꾸미 (octopus), "
            "참깨 (sesame), 토마토 (tomato). tags 는 매운맛, 국물요리, 패스트푸드 같은 DB 의 한국어 문자열입니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cuisine_types": _LIST, "excluded_cuisine_types": _LIST,
                "excluded_allergens": _LIST, "excluded_food_codes": _LIST,
                "required_tags": _LIST, "excluded_tags": _LIST,
                "kcal_min": _NUM, "kcal_max": _NUM, "protein_min": _NUM, "protein_max": _NUM,
                "sodium_max": _NUM, "price_max": _NUM,
            },
        },
    },
    {
        "name": "compute_plan",
        "description": (
            "plan 전체의 끼니별 / 일별 / 전체 합계(가격, kcal, 단백질, 나트륨)를 계산합니다. "
            "총예산이나 하루 나트륨 같은 합산 제약을 확인할 수 있도록 최종 답변 전에 호출하세요. "
            "plan 형식: {'day1_lunch': ['F020'], 'day1_dinner': ['F048']}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"plan": {"type": "object", "additionalProperties": _LIST}},
            "required": ["plan"],
        },
    },
    {
        "name": "check_plan",
        "description": (
            "식단(plan)이 사용자의 제약을 만족하는지 룰 기반으로 검사합니다. {passed, violations} 를 반환합니다. "
            "user_constraint 는 사용자가 직접 한 말(대화의 모든 턴)에서 채우고, 사용자가 말하지 않은 항목은 null 로 "
            "두세요. 형식: {'plan': {'days': int, 'meals_per_day': ['lunch', 'dinner']}, "
            "'constraints': {'budget_krw': {'total_max': int|null, 'per_meal_max': int|null}, "
            "'nutrition': {'per_meal': {'energy_kcal': {'min', 'max'}, 'protein_g': {'min', 'max'}}, "
            "'per_day': {'sodium_mg': {'min', 'max'}}}, 'excluded_allergens': [], 'excluded_food_codes': [], "
            "'cuisine_types': [] | null, 'excluded_cuisine_types': [], 'required_tags': [], 'excluded_tags': []}}. "
            "알레르기, cuisine type, tag 는 DB 의 한국어 어휘를 쓰세요 (search_foods 참고)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan": {"type": "object", "additionalProperties": _LIST},
                "user_constraint": {"type": "object"},
            },
            "required": ["plan", "user_constraint"],
        },
    },
]

PLANNER_TOOLS = ["search_foods", "compute_plan"]
VERIFIER_TOOLS = ["check_plan"]

_TOOLS = {"search_foods": search_foods, "compute_plan": compute_plan, "check_plan": check_plan}


def dispatch_tool(name, arguments):
    """LLM 의 tool_use 요청을 실행한다. 에러는 예외 대신 {"error": ...} 로 돌려줘 LLM 이 재시도하게 한다."""
    if name not in _TOOLS:
        return {"error": f"unknown tool {name!r}; available: {sorted(_TOOLS)}"}
    try:
        return _TOOLS[name](**(arguments or {}))
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


PLANNER_SYSTEM_PROMPT = """\
당신은 food DB 를 기반으로 식단을 짜 주는 챗봇입니다. 음식은 반드시 search_foods 로 조회하고, DB 에 없는 음식은
추천하지 마세요. 가격과 영양값은 도구가 돌려준 1인분(serving) 기준 값만 사용하고, 직접 추정하거나 계산하지 마세요.
알레르기 제외 조건은 절대 어기면 안 됩니다.
최종 답변 전에 compute_plan 을 호출해 총예산과 일별 합계를 확인하세요.
verifier 의 feedback 을 받으면 위반된 부분만 고치고 나머지는 그대로 두세요.
최종 답변은 자연어 설명을 쓴 뒤 아래 형식의 JSON 블록을 붙입니다.
slot 이름은 day{N}_{meal} (예: day1_lunch, day2_dinner) 이고, 값은 food_code 리스트입니다.
```json
{"plan": {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}}
```
"""

VERIFIER_SYSTEM_PROMPT = """\
당신은 식단(plan)이 사용자의 요청을 만족하는지 검증합니다. 사용자가 직접 쓴 메시지(모든 턴)를 읽고, 사용자가 말한
그대로 user_constraint 를 채운 뒤 (말하지 않은 항목은 null) plan 과 함께 check_plan 을 호출하세요.
plan 을 직접 판단하지 말고 도구 결과에 따르세요. 답변은 아래 JSON 블록으로 하세요:
```json
{"passed": true|false, "feedback": "무엇을 바꿔야 하는지 slot 별로 작성, 통과했으면 빈 문자열"}
```
"""
