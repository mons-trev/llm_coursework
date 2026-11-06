# 식단 추천 Planner / Verifier

사용자가 예산·음식 선호·영양 조건·알레르기를 포함한 자연어 요청을 전달하면,
Planner가 `food_DB.json`을 검색해 식단을 만들고 Verifier가 사후 검수합니다.
사용자의 후속 요청에서는 변경한 조건을 적용하고 유지/변경할 끼니를 검사합니다.
기본 모드는 `planner_verifier`이며, 같은 Planner에서 Verifier만 제외한
`planner_only`를 `--mode`로 선택할 수 있습니다.

기본 모델은 **gpt-4o-mini**입니다. 개발 중 도구 연결과 오류 처리를 확인한 뒤,
같은 한국어 테스트를 **gpt-5-mini**로 실행해 모델별 성공률을 따로 확인할 수 있습니다.

## 설치

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

API 키는 로컬 셸의 환경변수로 전달합니다. 다음 입력은 터미널에 표시되지 않습니다.

```bash
read -r -s -p 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
```

`.env.example`은 설정 예시이며 자동으로 읽지 않습니다. 실제 키를 소스나 명령행 인자에 넣지 마세요.

## 실행

```bash
# 대화: 최초 조건을 포함해 요청하고, 이어서 수정 요청
.venv/bin/python chat.py

# 대화를 파일로 저장하고 다음 실행에서 재개
.venv/bin/python chat.py --session-file artifacts/session.json

# 한 요청 실행
.venv/bin/python chat.py --query '새우 알레르기가 있어. 오늘 한식 점심과 저녁을 총 25000원 이하로 추천해줘.'

# 저렴한 모델로 한국어 테스트 10개 실행
.venv/bin/python run_eval.py --model gpt-4o-mini --output-dir artifacts/4o-mini

# 같은 입력을 GPT-5 mini로 평가
.venv/bin/python run_eval.py --model gpt-5-mini --output-dir artifacts/5-mini

# 일부 케이스만 실행
.venv/bin/python run_eval.py --model gpt-4o-mini --cases T05 T10 --output-dir artifacts/smoke

# 기존 영어 데이터셋도 선택 가능
.venv/bin/python run_eval.py --cases-file diet_test_cases_10.json
```

대화 명령은 `/new`, `/usage`, `/quit`입니다. `/new`는 대화만 초기화하며 사용 금액은 유지합니다.
기본 대화 화면은 자연어 요청과 한국어 응답만 보여 줍니다. 내부 JSON, 음식 코드, 검수 상태는
표시하지 않습니다. 개발 중 모델 이름과 검수 상태가 필요하면 `chat.py --debug`를 사용합니다.
`OPENAI_MODEL`, `PLANNER_MODEL`, `VERIFIER_MODEL` 환경변수 또는 CLI 옵션으로 모델을 선택합니다.
`--model`은 두 역할에 적용되며 역할별 CLI 옵션이 있으면 그것이 우선합니다.
GPT-5 mini는 기본 추론 강도 `low`를 사용하고, GPT-4o mini에는 reasoning 옵션을 보내지 않습니다.

## 발표용 대화 확인과 촬영

### 1. 실시간 시연 실행

설치를 마친 뒤 **Bash 터미널**에서 다음 순서로 실행합니다. 아래 경로는 현재 작업 환경 기준입니다.
API 키를 입력할 때는 화면에 표시되지 않으며, 실제 모델 호출에는 비용이 발생합니다.


# GPT-5 mini와 실제 대화하고 입력·응답·검수 기록 저장
.venv/bin/python chat.py --model gpt-5-mini --session-file artifacts/demo/live-session.json
```

기본 화면에는 한국어 입력과 응답이 표시됩니다. 촬영에서는 `--debug`를 붙이지 않습니다.
같은 세션 파일이 이미 있으면 이전 대화가 이어지므로, 새 촬영을 시작할 때는 챗봇 입력창에
`/new`를 먼저 입력하거나 새로운 `--session-file` 경로를 사용합니다.

첫 번째 요청으로 아래 내용을 입력합니다.

```text
오늘 점심과 저녁을 한식으로 추천해 줘. 새우 알레르기가 있으니 새우가 표시된 메뉴는 제외하고, 매운맛 태그가 있는 음식도 빼줘. 한 끼는 350~750kcal, 한 끼 12,000원 이하, 두 끼 총 21,000원 이하로 부탁해.
```

응답을 확인한 다음, 같은 대화에서 다음 수정 요청을 입력합니다.

```text
점심 메뉴는 그대로 유지하고 저녁 메뉴만 다른 음식으로 바꿔줘. 앞에서 말한 예산, 칼로리, 한식, 새우 알레르기, 매운맛 제외 조건은 전부 그대로 지켜줘.
```

영상에서는 최초 식단의 가격·열량·제외 조건을 확인하고, 수정 후 **점심은 유지되고 저녁만 바뀌는지**
보여 주면 됩니다. 실시간 응답의 메뉴는 과거 실험과 다를 수 있습니다. 종료할 때는 `/quit`를 입력합니다.
촬영 기록은 `artifacts/demo/live-session.json`에 저장되며, `/usage`로 누적 API 비용을 확인할 수 있습니다.

더 저렴한 모델로 실시간 리허설을 할 때는 아래 명령을 사용합니다. 이 실행도 API 호출 비용이 발생합니다.

```bash
.venv/bin/python chat.py --model gpt-4o-mini --session-file artifacts/demo/rehearsal-session.json
```

### 2. 저장된 실험 기록 재생 — API 키·추가 과금 없음

프로젝트 루트에서 실행합니다. `--step`을 사용하면 사용자 요청을 표시한 뒤,
**Enter를 누를 때마다 저장된 챗봇 응답**을 보여 줍니다.

```bash
# GPT-5 mini의 T10: 최초 요청 → 점심 유지·저녁 변경 요청
.venv/bin/python replay.py --run-dir artifacts/5-mini-ko-strict --case T10 --step

# GPT-4o mini의 같은 실험과 비교
.venv/bin/python replay.py --run-dir artifacts/4o-mini-ko-strict --case T10 --step

# GPT-5 mini의 T08: 이틀 식단의 하루별 나트륨 제한 확인
.venv/bin/python replay.py --run-dir artifacts/5-mini-ko-strict --case T08 --step

# T10 대화를 한 번에 출력하고 발표용 텍스트로 저장
.venv/bin/python replay.py --case T10 --export artifacts/demo/T10_gpt5mini.txt
```

재생에는 지정한 디렉터리의 `outputs.json`, `traces.json`, `usage.json`이 필요합니다.
`artifacts/`는 Git 관리 대상이 아니므로 다른 PC에서 재생하려면 해당 실험 디렉터리를 함께 복사해야 합니다.

`replay.py`는 저장 기록의 재생임을 화면에 명시합니다. 메뉴와 수치는 과거 실험에서 나온 것이며,
문장 표현은 현재 표시 함수로 변환한 것입니다. 이 기록은 한글 시스템 프롬프트 반영 전 실험이며,
현재 프롬프트의 새로운 성능 측정이나 실시간 생성으로 해석하지 않습니다.

### 3. 발표 전 실험 평가 실행

아래 명령은 자연어 대화 촬영이 아니라 **테스트 데이터셋의 통과율과 비용을 측정하는 용도**입니다.
API 키가 필요하며 호출 비용이 발생합니다. 결과는 실행마다 새로운 `artifacts/날짜-시간/` 디렉터리에 저장됩니다.

```bash
# 알레르기(T05)와 부분 수정(T10)만 먼저 확인
.venv/bin/python run_eval.py --model gpt-4o-mini --cases T05 T10

# 한국어 테스트 10개 전체를 GPT-5 mini로 평가
.venv/bin/python run_eval.py --model gpt-5-mini

# API 호출 없이 데이터·도구 스키마만 사전 점검
.venv/bin/python run_eval.py --check-only
```

확정된 식단은 `presentation.py`가 검증된 DB 수치로 한국어 문장으로 표시합니다.
모델 간 전달과 평가에는 구조화된 식단을 계속 사용합니다.

## 데이터와 평가

- 기본 테스트: `diet_persona_test_cases_10.json` (한국어, 원격 커밋 `43aeb9c`)
- 기존 영어 테스트: `diet_test_cases_10.json` (동일한 정답 제약)
- 런타임 음식 데이터: `food_DB.json`만 사용
- 평가: 기존 `metric.py`를 실행 루프 종료 후 호출

에이전트에는 `test_query`와 `follow_up_query`만 전달합니다. `user_constraint`,
`expected_revision`, persona, 테스트 ID는 에이전트 입력으로 전달하지 않습니다.
Verifier는 후보 생성 후 사용자 원문에서 검사 인자를 작성합니다.
Verifier가 조건을 잘못 해석할 가능성은 남아 있으며, 독립된 정답 제약으로 이를 평가합니다.

각 실행 디렉터리에는 다음 결과가 저장됩니다.

| 파일 | 내용 |
|---|---|
| `outputs.json` / `report.json` | 실제 반환한 구조화 식단(`approved` 또는 `generated`)과 독립 평가 결과 |
| `initial_outputs.json` / `initial_report.json` | 첫 후보와 해당 후보의 평가 결과 |
| `traces.json` | 사용자용 자연어 응답, 각 라운드의 도구 인자·결과, 후보, 검수 피드백, 종료 상태 |
| `usage.json` | 모델 설정, 호출별 토큰·시간·비용, 누적 비용 |
| `manifest.json` | 모드, 반복 번호, 실제 설정, 코드 커밋·작업 트리 상태, DB·테스트·프롬프트·도구·소스 해시 |
| `cases.json` | 해당 실행의 독립 평가 데이터 스냅샷. 에이전트 입력으로 사용하지 않음 |

Planner + Verifier의 실패 후보는 진단 기록에 남기고 승인된 응답으로 제공하지 않습니다. 재시도 소진은
조건이 수학적으로 불가능하다는 판정이 아닙니다. 실패한 후속 요청은 과거 승인 식단을
현재 조건에서도 유효한 것처럼 제공하지 않습니다. 추천 다양성과 끼니 구성 품질은 현재 범위 밖입니다.

## 비용 제한

기본 누적 한도는 **$15**, 장부는 `.usage/ledger.json`입니다. 모델을 바꾸거나 프로그램을
다시 실행해도 같은 장부의 누적 금액을 확인합니다. `--budget-usd 1`은 해당 실행만의
$1 추가 한도가 아니라 **장부 전체의 누적 $1 한도**입니다.

```bash
.venv/bin/python run_eval.py --model gpt-4o-mini --budget-usd 1 --output-dir artifacts/budgeted
```

호출 전에 입력 바이트 수와 출력 상한을 이용해 보수적으로 비용을 예약하고, API가 반환한
사용량으로 정산합니다. 내부 추론은 `output_tokens`에 포함해 계산하며 입력 캐시 할인도 반영합니다.
응답 유실·네트워크 오류처럼 실제 사용량을 알 수 없으면 예약 금액을 유지하고 중단합니다.
SDK 자동 재시도는 끕니다. 이 장부는 이 프로그램의 사용만 관리하며 세금이나 다른 프로그램의
사용액까지 제어하는 OpenAI 계정 결제 한도는 아닙니다.

Standard 요금 기준(USD/100만 토큰, 2026-11-05 확인):

| 모델 | 입력 | 캐시 입력 | 출력 |
|---|---:|---:|---:|
| gpt-4o-mini | 0.15 | 0.075 | 0.60 |
| gpt-5-mini | 0.25 | 0.025 | 2.00 |

[공식 요금표](https://developers.openai.com/api/docs/pricing).
요금이 변경되면 `budget.py`의 `RATES`를 갱신해야 합니다.
`--max-rounds`, `--max-agent-calls`, `--max-turn-calls`, `--max-output-tokens`로 추가 제한을 설정합니다.

## 과금 없는 검증

```bash
.venv/bin/python run_eval.py --check-only
.venv/bin/python -m unittest discover -s tests -v

# 저장된 응답 재평가 (API 호출 없음)
.venv/bin/python run_eval.py --evaluate-only artifacts/4o-mini/outputs.json --output-dir artifacts/rescore
```

회귀 테스트는 알레르기 위반, 현재 예산 재검사, 수정 범위, 검사 누락·대상 바꿔치기,
정답 데이터 분리, 정밀도, 누적 예산을 검증합니다. 가짜 모델 응답을 사용하는 테스트이므로
그 통과율을 실제 모델 성공률로 해석하지 않습니다.

## 코드 구성

`agents.py`는 Responses 함수 호출 루프와 역할별 도구를 관리하고,
`orchestrator.py`는 Planner → Verifier → 재작성 순서와 최종 승인을 관리합니다.
`tool_calling_function.py`의 `check_plan`은 현재 조건을, `check_revision`은 이전 식단과의 차이를 검사합니다.
`schemas.py`는 함수 인자와 최종 JSON을 검증합니다. API 함수 정의는 `strict: true`입니다.
`compute_plan`의 API 인자는 `slots: [{slot, food_codes}]`이며 어댑터가 기존 Python 함수의
슬롯 딕셔너리로 변환합니다. Verifier의 검사 대상과 이전 계획은 Python이 고정해 전달하고,
모델은 사용자 조건 또는 수정 정책만 인자로 작성합니다. 최종 응답은 JSON 모드를 사용하고
로컬에서 형식을 검증한 뒤 DB 값으로 사용자용 설명을 생성합니다.
`llm_client.py`는 모델별 API 옵션과 비용 정산, `session.py`는 대화 상태를 담당합니다.
`presentation.py`는 사용자용 한국어 문장, `replay.py`는 과거 대화 기록의 재생을 담당합니다.

## Planner-only ablation

이번 변경의 완료 범위는 구현과 API 호출 없는 검증(요청 1~7번)입니다.
실제 API smoke test와 모델별 3회 반복 실험(8번)은 아직 실행하지 않았습니다.
아래 실제 실험 명령은 후속 실행용이며, 오프라인 테스트 결과를 모델 성적으로 해석하지 않습니다.

| 모드 | 실행 흐름 | 반환 상태 | 반환 전 사용자 제약 검사 |
|---|---|---|---|
| `planner_verifier` (기본) | Planner → Verifier → 필요 시 피드백·재계획 | `approved` | Verifier가 사용자 원문에서 해석한 조건으로 검사 |
| `planner_only` | 같은 Planner의 검색·계산·자체 수정 → 반환 | `generated` | 별도 검사 없음. 위반 후보도 공통 실행 조건을 만족하면 반환 |

두 모드는 `agents.py`와 `tool_calling_function.py`의 기존 Planner 프롬프트·도구를
그대로 사용합니다. Planner-only도 `search_foods`와 `compute_plan`을 여러 번 호출할 수 있습니다.
두 모드 모두 최종 JSON 스키마, 성공한 검색 결과/직전 반환 식단의 코드 사용,
최종 후보와 동일한 `compute_plan` 실행, 호출·출력 토큰·누적 비용 제한을 유지합니다.
공통 실행 오류는 같은 피드백 문구와 `max_rounds` 한도로 재시도합니다.
Verifier 피드백에 의한 추가 라운드는 검수 모드에만 존재합니다.
모드 분기는 `orchestrator.py`에서 공통 실행 조건을 통과한 직후에 있습니다.

Planner-only 반환 경로는 Verifier LLM, `check_plan`, `check_revision`을 실행하지 않습니다.
표시할 때 `status="generated"`를 사용하며, `user_constraint`가 잘못 전달되더라도
표시 함수가 이를 사용하지 않도록 했습니다. DB 가격·열량 표시는 유지하며 별도 검수 없는
생성임을 표시합니다. 독립 평가 결과를 Planner에 피드백하지 않습니다.

`Session.last_returned_plan` / `returned_at_turn`은 실제 반환한 식단만 보관합니다.
`accepted_plan` / `accepted_at_turn`은 기존 승인 의미를 유지합니다.
T10 첫 반환이 사후 평가에서 실패해도 그 식단을 그대로 비교 기준으로 사용하고 두 번째 턴을 실행합니다.
실제 미반환 턴만 후속 실행을 중단하며, 실패 후보로 기준 식단을 덮어쓰지 않습니다.
모드를 기록해 다른 모드의 세션 재사용을 거절합니다. 모드가 없는 기존 세션은
`planner_verifier`로 읽고 과거 승인 식단을 반환 기준으로 이관합니다.
`chat.py`도 저장·재개 및 `generated` 반환 처리를 지원합니다.

`not_verified`는 기존 클라이언트 호환을 위해 유지하며, `termination_reason`이 종료 원인을 구분합니다.
`candidate_not_submitted`, `technical_execution_failure`, `call_limit`, `verifier_rejected`,
`api_error`, `budget_exceeded`를 기록하고, 정상 반환은 `verified` / `returned_unverified`입니다.
라운드에는 실패 단계·피드백과 실제 기준 식단을, 턴에는 전체 소요 시간과 호출 시도 수를 저장합니다.
실제 API 호출 수는 `usage.json`의 `api_called`로 세며 예약 단계에서 거절된 호출은 제외합니다.
사용량의 `role`, `case_id`, `output_field`, `turn`, `round`, `mode`는 로깅 메타데이터로만
기록합니다. 두 역할이 같은 모델이어도 구분 가능하며 이 메타데이터를 모델 요청에 추가하지 않습니다.
API 오류는 미정산 최대 비용 예약액과 토큰 미상을 기록하고 기존 누적 장부는 유지합니다.

```bash
# API 호출 없는 검증
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_eval.py --check-only
.venv/bin/python run_eval.py --mode planner_only --check-only

# 후속 실제 실험: 키와 기존 장부의 잔여 예산을 확인한 뒤 실행
.venv/bin/python run_eval.py --mode planner_only --model gpt-4o-mini --cases T05 T08 T10 --output-dir artifacts/ablation/4o-mini/smoke-planner-only
.venv/bin/python run_eval.py --mode planner_verifier --model gpt-4o-mini --cases T05 T08 T10 --output-dir artifacts/ablation/4o-mini/smoke-planner-verifier

# 1회차: 각각 새 세션·디렉터리, 동일 설정 사용
.venv/bin/python run_eval.py --mode planner_only --model gpt-4o-mini --repetition 1 --output-dir artifacts/ablation/4o-mini/planner-only-r1
.venv/bin/python run_eval.py --mode planner_verifier --model gpt-4o-mini --repetition 1 --output-dir artifacts/ablation/4o-mini/planner-verifier-r1

# 저장 결과만 비교: 아래는 r1 예시. 전체 실험에서는 r1~r3의 모든 디렉터리를 전달
.venv/bin/python compare_ablation.py artifacts/ablation/4o-mini/planner-only-r1 artifacts/ablation/4o-mini/planner-verifier-r1 --output-dir artifacts/ablation/compare-4o-mini-r1

# Planner-only / 기존 검수 기록 모두 재생 가능. 저장 모드를 화면에 표시
.venv/bin/python replay.py --run-dir artifacts/ablation/4o-mini/planner-only-r1 --case T10
```

2회차는 Verifier 모드부터, 3회차는 Planner-only부터 실행하고 `--repetition`과 디렉터리를 바꿉니다.
잔여 승인 예산이 충분할 때 GPT-5 mini도 같은 방식으로 실행합니다. 평가 실패의 종료 코드 `1`은
실험 결과이므로 다음 실행을 계속하며, `2`는 API·예산 실행 오류이므로 원인을 확인합니다.
설정·입력 오류는 argparse도 `2`로 반환하므로 메시지와 `traces.json`을 함께 확인합니다.
기존 디렉터리는 비어 있어도 재사용하지 않습니다. 한도를 높이거나 장부를 바꿔 한도를 우회하지 않습니다.

`compare_ablation.py`는 `comparison.json`과 `comparison.md`를 새 디렉터리에 생성합니다.
기존 `metric.py`의 케이스 단위 Overall/Requirement/Revision 정의를 유지하고, 별도로
전체 예정 턴(기본 데이터 11턴) 대비 반환·미반환·반환 후 실패와 알레르기 위반을 집계합니다.
알레르기 열은 **위반 수 / 알레르기 조건이 있는 반환 턴 수 / 알레르기 조건이 있는 전체 예정 턴 수**입니다.
빈 출력의 개별 검사가 통과하더라도 미반환을 안전한 식단 성공으로 세지 않습니다.
케이스/턴별 실패 검사, 종료 원인, 역할별 비용·토큰·호출 수, 턴 전체 시간도 기록합니다.
반복 평균·최소·최대는 동일 코드·데이터·프롬프트·설정 해시 그룹 안에서 계산합니다.
저장 DB가 현재 DB와 다르면 재평가를 거절하고, 저장 테스트 스냅샷의 해시도 확인합니다.

오류 사례는 같은 실행 안의 후보 → 독립 평가/실제 검수 → 피드백 → 수정 후보 → 최종 상태를
추적합니다. 요청·정답 범위·실제 계산값·검사 인자/결과·수정 전후 식단을 JSON 증거로 남깁니다.
예산/영양/제외/멀티턴 위반과 후보 미제출·실행 오류를 구분하고, 잘못된 후보의 수정·차단·승인,
올바른 후보의 거절, 검사 인자와 정답의 해석 불일치를 기록합니다. 독립 실행의 점수 차이만으로
특정 오류의 수정 효과를 주장하지 않습니다. 중간 `compute_plan`은 진단 자료이며 최종 반환이 아닙니다.
`initial_outputs.json`도 첫 후보 진단으로만 사용합니다. 특히 멀티턴 첫 후보는 이전 턴의 검수 이력을
이미 받았을 수 있으므로 독립 Planner-only baseline으로 볼 수 없습니다.

현재 저장된 `artifacts/4o-mini-ko-strict`, `artifacts/5-mini-ko-strict`를 재확인한 결과는 다음과 같습니다.
두 기록은 현재 한국어 프롬프트 전의 **과거 검수 시스템 기록**이며 새 ablation의 주 비교 대상이 아닙니다.

| 과거 모델 | 첫 후보 Overall | 최종 Overall | T08 |
|---|---:|---:|---|
| GPT-4o mini | 9/10 | 9/10 | 최종 후보 미제출, Verifier 시작 안 함 |
| GPT-5 mini | 10/10 | 10/10 | 승인 |

새 테스트는 가짜 응답으로 위반 후보 반환/차단/수정, 여러 도구 호출과 자체 수정,
공통 실행 오류의 동등한 재시도, T10의 실제 반환 기준 유지, 정답 메타데이터 분리,
세션/출력 저장·재생, 역할별 사용량, 오류 증거와 반복 집계를 검증합니다.
테스트 통과만으로 실제 모델에서 Verifier가 성능을 높였다고 결론낼 수 없습니다.
실제 반복 실험에서 차이가 없으면 그대로 보고하며, 추가 고난도 테스트는 별도 후속 실험으로 남깁니다.
