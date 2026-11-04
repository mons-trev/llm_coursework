# AGENT_GUIDE — planner / verifier 에이전트를 위한 `tool_calling_function.py` · `metric.py` 안내

이 문서는 **planner 에이전트와 verifier 에이전트를 구현하거나 호출하는 쪽(LLM 에이전트 포함)** 이 두 모듈을 올바르게 쓰도록 정리한 참고 문서다.
모든 수치 예시는 실제 `food_DB.json` 과 코드로 다시 계산해 확인한 값이다.

---

## 0. 한눈에 보기

| 파일 | 역할 | 누가 쓰나 |
|---|---|---|
| `food_DB.json` | 음식 50개 (F001–F050). 영양은 100 g / 100 ml 당, 가격은 1 serving 당 | 두 모듈이 각각 따로 읽음 |
| `food_DB_metadata.json` | DB 출처·환산 규칙·변경 이력 | 사람 참고용 |
| `diet_test_cases_10.json` | 테스트 케이스 10개 (T01–T10). T10 만 멀티턴 | 루프 코드, `metric.py` |
| `tool_calling_function.py` | LLM 이 tool calling 으로 호출하는 도구 3개 + 시스템 프롬프트 2개 | planner / verifier 루프 |
| `metric.py` | 에이전트 최종 출력을 룰 기반으로 채점 | 평가 단계 (루프 종료 후) |

```
사용자 질문 ──► [planner LLM] ──search_foods / compute_plan──► plan JSON
                     ▲                                             │
                     │ feedback (user 메시지로 덧붙임)              ▼
                     └──────────────── [verifier LLM] ──check_plan──┘
                                              │ passed=true
                                              ▼
                                   outputs.json 저장 ──► metric.py 채점
```

핵심 원칙

* **planner 는 숫자를 스스로 계산하지 않는다.** 가격·영양은 도구 결과만 쓴다.
* **verifier 는 plan 을 직접 판단하지 않는다.** 사용자 원문에서 `user_constraint` 를 채워 `check_plan` 에 넘기고, 그 결과만 전달한다.
* **metric 은 에이전트가 말한 숫자를 무시한다.** plan 의 food_code 만 꺼내 DB 로 다시 계산한다.

---

## 1. 공통 규약 (두 모듈이 동일하게 따름)

### 1.1 slot 과 plan 형식

* slot 이름: `day{N}_{meal}` — `day1_lunch`, `day2_dinner`, `day1_breakfast` …
* slot 값: **food_code 문자열 리스트**. 한 끼에 여러 음식을 넣으면 합산된다.
  `"F020"` 처럼 문자열 하나만 넣어도 `["F020"]` 로 정규화된다.
* 테스트 케이스가 요구하는 slot 집합은 `user_constraint.plan` 에서 나온다:
  `days=2, meals_per_day=["lunch","dinner"]` → `day1_lunch, day1_dinner, day2_lunch, day2_dinner`

```json
{"plan": {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}}
```

### 1.2 1인분(serving) 환산

DB 의 `nutrition` 은 `nutrition_basis`(100 g 또는 100 ml) 기준이다. 두 모듈 모두 로드 시점에
`nutrition × serving.amount / nutrition_basis.amount` 로 **serving 기준** `kcal / protein_g / sodium_mg` 를 만든다.
`price_krw` 는 이미 serving 하나의 가격이므로 환산하지 않는다.

주의: serving 은 "한 번 구매할 때 받는 양" 이라 1인 1끼 권장량이 아닐 수 있다 (피자 600 g 등). 그래서 kcal 상한에 걸리는 음식이 많다.

### 1.3 DB 어휘 (한국어 문자열 그대로 써야 한다)

| 필드 | 값 |
|---|---|
| `cuisine_type` | `한식` `중식` `일식` `양식` `동남아식` |
| `allergy` | `밀` `우유` `대두` `알류` `돼지고기` `쇠고기` `닭고기` `새우` `생선` `오징어` `조개류` `주꾸미` `참깨` `토마토` |
| `tags` (일부) | `매운맛` `국물요리` `패스트푸드` `밥류` `면류` `찌개류` `국밥류` `볶음류` `육류요리` `해산물요리` `찬음식` `간편식` … (총 36개) |

사용자 질문은 영어지만 (`shrimp allergy`, `fast food`, `spicy`) 도구 인자는 **반드시 DB 어휘(한국어)** 로 바꿔 넘겨야 한다. `TOOL_SPECS` 설명에 영→한 대응표가 들어 있다.

### 1.4 `user_constraint` 형식 (테스트 케이스와 `check_plan` 이 공유)

```json
{
  "plan": {"days": 1, "meals_per_day": ["lunch", "dinner"]},
  "constraints": {
    "budget_krw": {"total_max": 25000, "per_meal_max": null},
    "nutrition": {
      "per_meal": {"energy_kcal": {"min": 350, "max": 750}, "protein_g": {"min": null, "max": null}},
      "per_day":  {"sodium_mg": {"min": null, "max": null}}
    },
    "excluded_allergens": ["새우"],
    "excluded_food_codes": [],
    "cuisine_types": ["한식"],
    "excluded_cuisine_types": [],
    "required_tags": [],
    "excluded_tags": []
  }
}
```

* 사용자가 말하지 않은 항목은 `null` 또는 `[]`. **그 항목은 검사하지 않는다.**
* `cuisine_types` 는 허용 목록(화이트리스트), `excluded_cuisine_types` 는 금지 목록.
* `required_tags` 는 **끼니마다** 그 끼니 음식들의 태그 합집합에 전부 들어 있어야 한다.
* `sodium_mg` 는 **하루 합계** 기준, 나머지 영양/가격은 **끼니** 기준, `total_max` 는 **전체 합계** 기준.
* 모든 키가 있어야 한다. 키가 빠지면 `check_plan` 이 `KeyError` 를 내고 `dispatch_tool` 이 `{"error": ...}` 로 돌려준다.

---

## 2. `tool_calling_function.py`

### 2.1 모듈 로드 시 만들어지는 것

| 이름 | 내용 |
|---|---|
| `FOOD_DB` | `{food_code: {food_code, name, cuisine_type, tags, allergy, price_krw, kcal, protein_g, sodium_mg}}` (serving 기준, 소수 1자리) |
| `TOOL_SPECS` | LLM 에 넘기는 tool 정의 3개 (`name`, `description`, `input_schema`). 설명은 영어 |
| `PLANNER_TOOLS` | `["search_foods", "compute_plan"]` |
| `VERIFIER_TOOLS` | `["check_plan"]` |
| `PLANNER_SYSTEM_PROMPT`, `VERIFIER_SYSTEM_PROMPT` | 각 에이전트 system prompt (영어) |

에이전트별 도구 목록 만들기:

```python
from tool_calling_function import TOOL_SPECS, PLANNER_TOOLS, VERIFIER_TOOLS, dispatch_tool

planner_tools  = [t for t in TOOL_SPECS if t["name"] in PLANNER_TOOLS]
verifier_tools = [t for t in TOOL_SPECS if t["name"] in VERIFIER_TOOLS]
```

### 2.2 `dispatch_tool(name, arguments) -> dict | list`

LLM 의 `tool_use` 블록을 실행한다. **예외를 던지지 않고** `{"error": "..."}` 를 돌려주므로, 그대로 `tool_result` 로 넘기면 LLM 이 인자를 고쳐 재시도한다.

| 입력 | 결과 |
|---|---|
| 모르는 도구 이름 | `{"error": "unknown tool 'nope'; available: ['check_plan', 'compute_plan', 'search_foods']"}` |
| 필수 인자 누락 | `{"error": "TypeError: compute_plan() missing 1 required positional argument: 'plan'"}` |
| 없는 인자 | `{"error": "TypeError: search_foods() got an unexpected keyword argument 'bogus'"}` |
| `user_constraint` 키 누락 | `{"error": "KeyError: 'plan'"}` |

### 2.3 planner 도구 ① `search_foods(**filters) -> list[record]`

조건에 맞는 음식을 **가격 오름차순** 으로 돌려준다. `None` / 빈 리스트인 조건은 적용하지 않는다.

| 인자 | 의미 |
|---|---|
| `cuisine_types` | 이 중 하나여야 함 (허용 목록) |
| `excluded_cuisine_types` | 이 분류는 제외 |
| `excluded_allergens` | allergy 에 하나라도 겹치면 제외 ← **알레르기 케이스에서 반드시 넘길 것** |
| `excluded_food_codes` | 코드 제외 (T06 쇠고기 케이스처럼 코드 목록으로 주어질 때) |
| `required_tags` | 음식 하나가 이 태그를 **모두** 가져야 함 |
| `excluded_tags` | 하나라도 있으면 제외 |
| `kcal_min` `kcal_max` `protein_min` `protein_max` `sodium_max` `price_max` | serving 기준 수치 필터 (끼니 하나에 음식 하나를 넣는다는 전제) |

반환 레코드 예 (`FOOD_DB` 값과 같은 형식):

```json
{"food_code": "F020", "name": "제육볶음", "cuisine_type": "한식", "tags": ["볶음류", "육류요리", "매운맛"],
 "allergy": ["돼지고기", "대두", "밀", "참깨"], "price_krw": 10000, "kcal": 370.0, "protein_g": 38.5, "sodium_mg": 1190.0}
```

### 2.4 planner 도구 ② `compute_plan(plan) -> dict`

plan 전체의 **끼니별 / 일별 / 전체 합계** 를 돌려준다. 제약을 판단하지는 않는다. 총예산·하루 나트륨처럼 합산이 필요한 제약은 planner 가 이 결과를 보고 스스로 맞춰야 한다. DB 에 없는 코드는 합산에서 빠지고 `unknown_codes` 에 들어간다.

```python
compute_plan({"day1_lunch": ["F020"], "day1_dinner": ["F048"]})
```
```json
{"slots": {"day1_lunch":  {"price_krw": 10000, "kcal": 370.0, "protein_g": 38.5, "sodium_mg": 1190.0},
           "day1_dinner": {"price_krw": 8500,  "kcal": 550.0, "protein_g": 38.5, "sodium_mg": 1905.0}},
 "days":  {"day1": {"price_krw": 18500, "kcal": 920.0, "protein_g": 77.0, "sodium_mg": 3095.0}},
 "total": {"price_krw": 18500, "kcal": 920.0, "protein_g": 77.0, "sodium_mg": 3095.0},
 "unknown_codes": []}
```

### 2.5 verifier 도구 ③ `check_plan(plan, user_constraint) -> {"passed": bool, "violations": [str]}`

`user_constraint`(1.4 형식)를 기준으로 plan 을 룰 검사한다. 검사 항목과 메시지 형식:

| 검사 | violation 메시지 예 |
|---|---|
| 요구 slot 누락 | `missing slots: ['day1_dinner']` |
| 요구하지 않은 slot | `unrequested slots: ['day2_lunch']` |
| DB 에 없는 코드 | `food codes not in DB: ['ZZZ']` |
| 총예산 | `total price 26500 > 25000` |
| 끼니 가격 | `price per meal out of range [None, 8000]: {'day1_lunch': 10000}` |
| 끼니 kcal / 단백질 | `kcal per meal out of range [250, 700]: {'day1_lunch': 1518.0}` (불고기피자 600 g serving) |
| 하루 나트륨 | `sodium per day out of range [None, 1600]: {'day1': 3095.0}` |
| 알레르겐 | `contains excluded allergen: ['day1_dinner:콩나물국밥(F008)']` |
| 제외 코드 | `excluded food code: ['day1_lunch:불고기피자(F001)']` |
| 허용 분류 밖 / 금지 분류 | `cuisine not allowed: ['day1_lunch:불고기피자(F001)']` / `excluded cuisine: [...]` |
| 필수 태그 | `required tags ['매운맛'] missing in: ['day1_dinner']` |
| 제외 태그 | `has excluded tag: ['day1_lunch:제육볶음(F020)']` |

`metric.py` 의 `evaluate_plan` 과 **같은 규칙** 이지만 평가 코드와 섞이지 않도록 따로 구현되어 있다. 따라서 `check_plan` 이 통과하면 metric 의 structure/constraint/safety 도 통과한다 — **단, verifier 가 `user_constraint` 를 테스트 케이스와 같게 채웠을 때만** 그렇다. verifier 가 제약을 빠뜨리면 check_plan 은 통과하고 metric 은 실패한다.

### 2.6 시스템 프롬프트가 요구하는 최종 답변 형식

**planner** (`PLANNER_SYSTEM_PROMPT`): 자연어 설명 뒤에 JSON 블록. metric 은 **마지막** ```` ```json ```` 블록을 읽는다.

````
Lunch: 제육볶음, dinner: 된장찌개. Total KRW 18,500.
```json
{"plan": {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}}
```
````

**verifier** (`VERIFIER_SYSTEM_PROMPT`): JSON 블록 하나. `feedback` 은 slot 단위로 무엇을 바꿀지 적는다.

````
```json
{"passed": false, "feedback": "day1_dinner 콩나물국밥 contains 새우 (shrimp allergy). Replace dinner with a Korean dish without 새우, 350-750 kcal, keep total <= 25,000."}
```
````

프롬프트의 다른 지시: planner 는 DB 에 없는 음식을 추천하지 않고, 최종 답변 전에 `compute_plan` 을 호출하며, verifier feedback 을 받으면 **위반된 부분만 고치고 나머지는 유지** 한다. verifier 는 **모든 턴의 사용자 메시지** 를 읽어 `user_constraint` 를 채운다.

---

## 3. `metric.py`

### 3.1 입력: `outputs.json`

```json
{
  "T01": {"output": "<planner 최종 답변 문자열>"},
  "T05": {"output": {"plan": {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}}},
  "T10": {"output": "<1턴 답변>", "follow_up_output": "<2턴 답변>"}
}
```

* `output` 은 ```` ```json ```` 블록을 포함한 **문자열** 이든 `{"plan": {...}}` **dict** 든 된다.
* `follow_up_query` 가 있는 케이스(T10)만 `follow_up_output` 이 필요하다. 없으면 revision 3개 항목이 모두 실패한다.

### 3.2 `extract_plan(output) -> {slot: [code]} | None`

1. 문자열이면 ```` ```json … ``` ```` 블록 중 **마지막 것** 을 파싱. 블록이 없으면 문자열 전체를 JSON 으로 파싱.
2. dict 의 `"plan"` 키를 꺼냄. 없으면 dict 자체를 plan 으로 봄.
3. 값은 리스트로 정규화. 파싱 실패 / dict 가 아니면 `None` → 모든 slot 누락으로 채점된다.

### 3.3 `evaluate_plan(plan, case) -> [check]` — 검사 항목

제약이 `null` / `[]` 이면 그 항목은 **결과 목록에 아예 나오지 않는다** (해당 없음).

| name | category | 언제 검사 | 내용 |
|---|---|---|---|
| `slots_complete` | structure | 항상 | 요구 slot 누락 / 추가 slot |
| `foods_in_db` | structure | 항상 | DB 에 없는 코드 |
| `budget_total` | constraint | `total_max` 있을 때 | 전체 가격 합 |
| `budget_per_meal` | constraint | `per_meal_max` 있을 때 | 끼니 가격 |
| `kcal_per_meal` | constraint | min/max 중 하나라도 | 끼니 kcal |
| `protein_per_meal` | constraint | min/max 중 하나라도 | 끼니 단백질 |
| `sodium_per_day` | constraint | min/max 중 하나라도 | 하루 나트륨 합 |
| `allergens` | **safety** | `excluded_allergens` 비어있지 않을 때 | 알레르겐 포함 음식 |
| `excluded_food_codes` | constraint | 비어있지 않을 때 | 제외 코드 사용 |
| `cuisine_types` | constraint | `null` 아닐 때 | 허용 분류 밖 음식 |
| `excluded_cuisine_types` | constraint | 비어있지 않을 때 | 금지 분류 음식 |
| `required_tags` | constraint | 비어있지 않을 때 | 끼니별 태그 합집합 검사 |
| `excluded_tags` | constraint | 비어있지 않을 때 | 제외 태그 음식 |

각 check: `{"name", "category", "passed": bool, "detail": str}`. `detail` 은 실패 시 위반 목록 문자열, 성공 시 `"ok"` 또는 `"18500 <= 25000"` 같은 요약.

### 3.4 `evaluate_revision(orig, new, case) -> [check]` — 멀티턴 (T10)

`case["expected_revision"]` 기준:

| name | 통과 조건 |
|---|---|
| `revision_preserved` | `preserve_slots` 의 음식 코드 집합이 1턴과 2턴에서 **동일** |
| `revision_changed` | `change_slots` 가 2턴에 **존재하고** 1턴과 **다름** |
| `revision_constraints_kept` | 2턴 plan 이 원래 `user_constraint` 의 structure/constraint/safety 를 모두 통과 (`preserve_all_original_constraints: true` 일 때) |

### 3.5 `evaluate_case(case, entry) -> dict` / `evaluate_all(cases, outputs)` / `print_report(report)`

```python
import json
from metric import evaluate_all, print_report, evaluate_case

cases   = json.load(open("diet_test_cases_10.json", encoding="utf-8"))
outputs = json.load(open("outputs.json", encoding="utf-8"))
report  = evaluate_all(cases, outputs)   # {"summary": {...}, "results": [...]}
print_report(report)
```

`evaluate_case` 결과 (T05 통과 예):

```json
{"test_id": "T05",
 "plan": {"day1_lunch": ["F020"], "day1_dinner": ["F048"]},
 "checks": [{"name": "slots_complete", "category": "structure", "passed": true, "detail": "2 slots"},
            {"name": "foods_in_db",    "category": "structure", "passed": true, "detail": "ok"},
            {"name": "budget_total",   "category": "constraint","passed": true, "detail": "18500 <= 25000"},
            {"name": "kcal_per_meal",  "category": "constraint","passed": true, "detail": "ok"},
            {"name": "allergens",      "category": "safety",    "passed": true, "detail": "ok"},
            {"name": "cuisine_types",  "category": "constraint","passed": true, "detail": "ok"}],
 "requirement_pass": true,   // (1) structure + constraint 전부 통과
 "revision_pass": null,      // (2) follow_up 없는 케이스는 null
 "safety_pass": true,        // (3) allergens 검사가 없는 케이스는 null
 "overall_pass": true}
```

`summary` 의 키: `n_cases`, `overall_pass`, `requirement_pass`, `revision_pass`("1/1" 문자열), `safety_violations`("0/3" 문자열), `per_check`(항목별 `{passed, total}`).

> **주의: `metric.py` 에는 `if __name__ == "__main__"` 블록이 없다.** `python metric.py outputs.json` 은 아무 일도 하지 않는다. 루프 코드(main) 에서 위처럼 import 해서 호출해야 한다.

---

## 4. planner ↔ verifier 루프 설계

### 4.1 메시지 흐름

```
planner 대화 = [system: PLANNER_SYSTEM_PROMPT] + [user: test_query] + (tool_use/tool_result …) + [assistant: 최종 답변]
verifier 대화 = [system: VERIFIER_SYSTEM_PROMPT] + [user: 사용자 질문 원문(모든 턴) + planner 의 plan JSON]
```

* verifier 에게는 **사용자 질문 원문과 plan JSON 만** 넘긴다. planner 의 추론·검색 결과·자연어 설명은 넘기지 않는다 (planner 가 말한 숫자에 verifier 가 끌려가지 않도록).
* verifier 가 `passed: false` 를 돌려주면 `feedback` 을 planner 대화에 **user 메시지로 덧붙여** 다시 돌린다. planner 대화는 누적되므로 이전 검색 결과를 재활용할 수 있다.
* `passed: true` 가 나오거나 **최대 라운드(예: 3)** 에 도달하면 종료하고, planner 의 마지막 최종 답변을 `outputs.json` 에 저장한다.
* 멀티턴 케이스(T10)는 1턴 루프가 끝난 뒤 `follow_up_query` 를 planner 대화에 user 메시지로 추가하고 같은 루프를 한 번 더 돈다. 이때 verifier 에는 **두 턴의 사용자 메시지를 모두** 넘겨 "점심 유지" 조건까지 `user_constraint` 에 반영하게 한다 (유지/변경 slot 자체는 `check_plan` 이 검사하지 않으므로 verifier LLM 이 feedback 에서 직접 지적해야 한다).

### 4.2 루프 의사코드

```python
def run_case(case, max_rounds=3):
    planner_msgs = [{"role": "user", "content": case["test_query"]}]
    user_turns = [case["test_query"]]

    def one_turn():
        for _ in range(max_rounds):
            answer = run_agent(PLANNER_SYSTEM_PROMPT, planner_msgs, planner_tools)   # tool_use 루프 포함
            plan = extract_plan(answer)                                               # metric.extract_plan 재사용 가능
            verdict = run_agent(VERIFIER_SYSTEM_PROMPT,
                                [{"role": "user", "content": format_for_verifier(user_turns, plan)}],
                                verifier_tools)
            if json.loads(last_json_block(verdict))["passed"]:
                break
            planner_msgs.append({"role": "user", "content": "Verifier feedback: " + feedback})
        return answer

    out = {"output": one_turn()}
    if "follow_up_query" in case:
        planner_msgs.append({"role": "user", "content": case["follow_up_query"]})
        user_turns.append(case["follow_up_query"])
        out["follow_up_output"] = one_turn()
    return out
```

`run_agent` 안의 tool_use 루프: `stop_reason == "tool_use"` 인 동안 각 `tool_use` 블록을 `dispatch_tool(block.name, block.input)` 로 실행하고 `tool_result` 로 돌려준다. `end_turn` 이면 텍스트를 최종 답변으로 쓴다.

### 4.3 예시 트레이스 ① T05 — 단일턴, 알레르기 (verifier 가 1회차에서 잡는 경우)

사용자 질문: *"I have a shrimp allergy … Korean-style lunch and dinner for today. Each meal 350–750 kcal, two meals together ≤ KRW 25,000."*
테스트 케이스의 `user_constraint`: `excluded_allergens=["새우"]`, `cuisine_types=["한식"]`, kcal 350–750, `total_max=25000`.

**[planner 1회차]** — 알레르기 필터를 빠뜨리는 상황

| # | 주체 | 내용 |
|---|---|---|
| 1 | LLM → tool_use | `search_foods(cuisine_types=["한식"], kcal_min=350, kcal_max=750, price_max=25000)` |
| 2 | tool_result | 12개 후보. 그중 `F008 콩나물국밥` (8,500원, 480 kcal) 의 allergy 에 `새우` 가 있음 |
| 3 | LLM → tool_use | `compute_plan({"day1_lunch": ["F020"], "day1_dinner": ["F008"]})` |
| 4 | tool_result | `total.price_krw=18500`, 끼니 kcal 370 / 480. 숫자 조건은 모두 만족 |
| 5 | LLM → end_turn | `"Lunch: 제육볶음, dinner: 콩나물국밥. Total KRW 18,500."` + ```` ```json {"plan": {"day1_lunch": ["F020"], "day1_dinner": ["F008"]}} ``` ```` |

**[verifier 1회차]** — 입력: 사용자 질문 원문 + plan JSON

| # | 주체 | 내용 |
|---|---|---|
| 6 | LLM → tool_use | `check_plan(plan=…, user_constraint={… "excluded_allergens": ["새우"], "cuisine_types": ["한식"], kcal 350–750, total_max 25000 …})` |
| 7 | tool_result | `{"passed": false, "violations": ["contains excluded allergen: ['day1_dinner:콩나물국밥(F008)']"]}` |
| 8 | LLM → end_turn | ```` ```json {"passed": false, "feedback": "day1_dinner 콩나물국밥 contains 새우 (shrimp allergy). Replace dinner with a Korean dish without 새우, 350-750 kcal, keep total <= 25,000."} ``` ```` |

**[planner 2회차]** — feedback 이 user 메시지로 덧붙여짐

| # | 주체 | 내용 |
|---|---|---|
| 9 | LLM → tool_use | `search_foods(cuisine_types=["한식"], excluded_allergens=["새우"], kcal_min=350, kcal_max=750, price_max=15000)` |
| 10 | tool_result | 8개 후보. 콩나물국밥·순대국·부대찌개(새우)와 차돌박이구이(가격) 가 빠짐 |
| 11 | LLM → tool_use | `compute_plan({"day1_lunch": ["F020"], "day1_dinner": ["F048"]})` — 점심 유지, 저녁만 된장찌개로 교체 |
| 12 | tool_result | `total.price_krw=18500`, 끼니 kcal 370 / 550 |
| 13 | LLM → end_turn | `"Lunch: 제육볶음, dinner: 된장찌개. Total KRW 18,500."` + ```` ```json {"plan": {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}} ``` ```` |

**[verifier 2회차]**

| # | 주체 | 내용 |
|---|---|---|
| 14 | LLM → tool_use | `check_plan(plan=…, user_constraint=…)` (같은 제약) |
| 15 | tool_result | `{"passed": true, "violations": []}` |
| 16 | LLM → end_turn | ```` ```json {"passed": true, "feedback": ""} ``` ```` → 루프 종료 |

**[저장과 평가]**

| # | 내용 |
|---|---|
| 17 | 13번 최종 답변을 `outputs.json` 의 `"T05": {"output": ...}` 에 저장 |
| 18 | `evaluate_all(cases, outputs)` → `extract_plan` 이 JSON 블록에서 plan 을 꺼내 DB 로 재계산. T05 결과: `overall_pass=true, requirement_pass=true, safety_pass=true` (3.5 의 결과 JSON 참고) |

핑퐁 횟수: planner API 호출 3회(도구 2 + 최종 1) × 2회차, verifier 2회 × 2회차 = **총 10회**. 1회차에 verifier 가 통과시키면 5회. 최대 3회차 기준 상한은 15회.

만약 5번의 plan 을 그대로 저장했다면 metric 은 `allergens` 항목만 실패시키고 `requirement_pass=true, safety_pass=false, overall_pass=false` 로 채점한다 — "요구 충족" 과 "안전" 이 별도 축이기 때문이다.

### 4.4 예시 트레이스 ② T10 — 멀티턴, 저녁만 교체

사용자 질문 1턴: *Korean lunch and dinner for today, shrimp allergy, exclude "매운맛", 350–750 kcal, ≤ KRW 12,000 per meal, total ≤ KRW 21,000.*
`user_constraint`: `excluded_allergens=["새우"]`, `excluded_tags=["매운맛"]`, `cuisine_types=["한식"]`, kcal 350–750, `per_meal_max=12000`, `total_max=21000`.

**1턴** — `search_foods(cuisine_types=["한식"], excluded_allergens=["새우"], excluded_tags=["매운맛"], kcal_min=350, kcal_max=750, price_max=12000)` → 5개 후보:

| food_code | name | price_krw | kcal | tags |
|---|---|---|---|---|
| F033 | 소시지볶음 | 5,000 | 560.0 | 볶음류, 반찬류, 육류요리 |
| F024 | 잔치국수 | 7,000 | 435.5 | 면류, 국물요리 |
| F048 | 된장찌개 | 8,500 | 550.0 | 찌개류, 국물요리 |
| F047 | 떡국 | 10,000 | 588.0 | 떡류, 국물요리 |
| F010 | 콩국수 | 11,000 | 700.0 | 면류, 찬음식 |

(`F020 제육볶음` 은 `매운맛` 태그 때문에 빠진다. T05 에서 쓰던 조합을 그대로 쓰면 `excluded_tags` 위반.)

planner 최종: `{"plan": {"day1_lunch": ["F048"], "day1_dinner": ["F024"]}}` — 총 15,500원. verifier `check_plan` → `passed: true`.

**2턴** — `follow_up_query`: *"Keep the lunch menu exactly as it is, but replace the dinner with a different dish. Preserve all my earlier constraints …"* 를 planner 대화에 user 메시지로 추가.

planner 최종: `{"plan": {"day1_lunch": ["F048"], "day1_dinner": ["F047"]}}` — 총 18,500원. verifier 는 두 턴의 사용자 메시지를 모두 받아 같은 `user_constraint` 로 `check_plan` → `passed: true`, 그리고 점심 slot 이 그대로인지 스스로 확인해 feedback 을 비운다.

**저장**: `"T10": {"output": <1턴 답변>, "follow_up_output": <2턴 답변>}`

**metric 결과**: `requirement_pass=true, safety_pass=true, revision_pass=true, overall_pass=true`. revision 항목 3개 모두 `ok`.

실패 예: 2턴에서 점심까지 `F024` 로 바꿨다면 →
`revision_preserved: ["day1_lunch:['F048']->['F024']"]` 실패, `revision_changed: ok`, `revision_constraints_kept: ok`, `revision_pass=false`.

---

## 5. 자주 하는 실수 / 체크리스트

**planner**

* `search_foods` 에 `excluded_allergens` / `excluded_food_codes` / `excluded_tags` 를 **항상** 같이 넘겨라. 후보 목록에서 빼지 않으면 T05 1회차처럼 금지 음식을 고르게 된다.
* 끼니 수치 필터(`kcal_min/max`, `price_max`)는 "한 끼 = 음식 하나" 전제다. 한 끼에 두 음식을 넣으면 `compute_plan` 으로 합계를 확인해야 한다.
* `compute_plan` 은 합산만 한다. `total_max`, `sodium_per_day`, `per_meal_max` 와의 비교는 planner 가 결과를 보고 직접 해야 한다.
* 끼니 가격 상한(`per_meal_max`)은 `search_foods` 의 `price_max` 로, 총예산은 `compute_plan` 으로 맞춘다.
* feedback 을 받으면 **지적된 slot 만** 바꿔라. 나머지를 바꾸면 T10 의 `revision_preserved` 가 깨진다.
* 최종 답변의 마지막 ```` ```json ```` 블록이 plan 이어야 한다. 설명 중간에 다른 JSON 블록을 넣으면 `extract_plan` 이 마지막 것을 읽는다.

**verifier**

* `user_constraint` 의 **모든 키** 를 채워라 (없는 건 `null`/`[]`). 키가 빠지면 `KeyError` 가 돌아온다.
* 어휘는 DB 한국어로: `shrimp→새우`, `wheat→밀`, `beef→쇠고기`, `Korean→한식`, `spicy→매운맛`, `broth→국물요리`, `fast food→패스트푸드`.
* T06 처럼 사용자가 "beef 가 들어간 메뉴 전부 제외" 라고 하면 `excluded_allergens=["쇠고기"]` 로 채워도 `check_plan` 이 같은 음식을 잡는다 (테스트 케이스는 `excluded_food_codes` 로 적혀 있지만 둘 다 유효).
* `check_plan` 은 slot 유지/변경(멀티턴) 을 검사하지 않는다. T10 2턴에서는 verifier 가 1턴 plan 과 비교해 점심이 그대로인지 **직접** 확인하고 feedback 에 써야 한다.
* 사용자 원문만 믿어라. planner 의 설명("총 18,500원")을 입력으로 받지 않도록 루프 코드가 걸러야 한다.

**루프 / 평가 코드**

* `outputs.json` 에는 planner 의 **마지막** 최종 답변만 저장한다 (중간 회차 답변 아님).
* `follow_up_query` 가 있는 케이스는 `follow_up_output` 을 꼭 채워라. 없으면 revision 3항목 전부 실패.
* `metric.py` 는 CLI 가 없다. main 에서 `evaluate_all` 을 import 해 호출하고, 필요하면 `report` 를 JSON 으로 저장한다.
* 두 모듈은 `food_DB.json` 을 **각자** 읽는다. DB 파일을 바꾸면 둘 다 영향을 받고, 영양 환산 규칙이 둘 다 같아야 한다 (`serving.amount / nutrition_basis.amount`).
