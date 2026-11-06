"""Bounded tool-calling loop with separate planner/reviewer contexts."""
import copy
import json
from dataclasses import dataclass, field

from schemas import object_schema, validate
from tool_calling_function import (
    FOOD_DB, PLANNER_SYSTEM_PROMPT, PLANNER_TOOLS, TOOL_SPECS,
    VERIFIER_SYSTEM_PROMPT, VERIFIER_TOOLS, dispatch_tool,
)


class AgentError(RuntimeError):
    def __init__(self, message, *, role=None, history=None, events=None):
        super().__init__(message)
        self.role, self.history, self.events = role, history, events


@dataclass
class AgentResult:
    text: str
    messages: list
    events: list = field(default_factory=list)


def openai_tools(names):
    """Strict wire schemas; public Python functions keep their original contracts.

    Known review plans are bound in Python. A generated plan is represented as
    slot records on the wire so strict schemas need no dynamic dictionary keys.
    """
    def strict_schema(value):
        if isinstance(value, list):
            return [strict_schema(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {k: strict_schema(v) for k, v in value.items() if k != "uniqueItems"}
        if result.get("type") == "object":
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        return result

    result = []
    for spec in TOOL_SPECS:
        name = spec["name"]
        if name not in names:
            continue
        schema = copy.deepcopy(spec["input_schema"])
        description = spec["description"]
        if name == "search_foods":
            schema = object_schema({key: {"anyOf": [value, {"type": "null"}]}
                                    for key, value in schema["properties"].items()})
            description += " 사용하지 않는 필터는 null 로 전달하세요. 모든 필터는 중첩 없이 이름 있는 인자로 전달합니다."
        elif name == "compute_plan":
            schema = object_schema({"slots": {
                "type": "array", "minItems": 1,
                "items": object_schema({
                    "slot": {"type": "string", "pattern": r"^day[1-9][0-9]*_[a-z][a-z0-9]*$"},
                    "food_codes": {"type": "array", "minItems": 1,
                                   "items": {"type": "string", "pattern": r"^F[0-9]{3}$"}},
                }),
            }})
            description += (" 현재 API 의 인자는 plan 딕셔너리가 아니라 모든 끼니를 담은 slots 배열입니다. "
                            "예: {'slots': [{'slot': 'day1_lunch', 'food_codes': ['F020']}]}. "
                            "최종 응답에는 {'plan': {slot: [codes]}} 딕셔너리 형식을 사용하세요.")
        else:
            for bound in ("plan", "previous_plan"):
                schema["properties"].pop(bound, None)
            description += " 검사할 후보와 이전 식단은 실행 코드가 고정하여 전달하므로 도구 인자로 직접 작성하지 마세요."
        result.append({"type": "function", "name": name, "description": description,
                       "parameters": strict_schema(schema), "strict": True})
    return result


def decode_arguments(name, arguments):
    if name == "compute_plan":
        slots = arguments["slots"]
        if len({r["slot"] for r in slots}) != len(slots):
            raise ValueError("duplicate slots in compute_plan")
        return {"plan": {r["slot"]: r["food_codes"] for r in slots}}
    return arguments


class AgentRunner:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    def run(self, role, messages, before_call, handler=None):
        planner = role == "planner"
        if role not in {"planner", "verifier"}:
            raise ValueError("unknown agent role")
        allowed = PLANNER_TOOLS if planner else VERIFIER_TOOLS
        tools = openai_tools(allowed)
        specs = {t["name"]: t["parameters"] for t in tools}
        model = self.settings.planner_model if planner else self.settings.verifier_model
        prompt = PLANNER_SYSTEM_PROMPT if planner else VERIFIER_SYSTEM_PROMPT
        if not planner:
            prompt += ("\ncheck_plan/check_revision 의 검사 대상 후보와 이전 식단은 Python 코드가 고정합니다. "
                       "도구 스키마에 따라 user_constraint 또는 수정 범위만 인자로 작성하세요. "
                       "조건의 모든 키를 채우고, 사용자가 말하지 않은 수치의 상한과 하한은 null 로 두세요. "
                       "user_constraint.plan 은 기간과 끼니 종류를 나타내며 음식 배정표가 아닙니다. "
                       "패스트푸드와 국물요리는 cuisine_type 이 아니라 tags 입니다.")
            vocabulary = {key: sorted({item for r in FOOD_DB.values() for item in r[key]})
                          for key in ("allergy", "tags")}
            vocabulary["cuisine_type"] = sorted({r["cuisine_type"] for r in FOOD_DB.values()})
            prompt += "\nDB 에서 사용하는 정확한 어휘: " + json.dumps(vocabulary, ensure_ascii=False)
        history, events = copy.deepcopy(messages), []

        def failure(message):
            return AgentError(message, role=role, history=history, events=events)

        for _ in range(self.settings.max_agent_calls):
            try:
                before_call()
            except AgentError as exc:
                raise failure(str(exc)) from exc
            response = self.client.create(model=model, instructions=prompt,
                                          messages=history, tools=tools)
            if response.status != "completed":
                raise failure("model response incomplete; candidate cannot be approved")
            # Preserve ALL output items, including GPT-5 reasoning/encrypted state.
            items = [item.model_dump(exclude_none=True) if hasattr(item, "model_dump")
                     else item for item in response.output]
            history.extend(items)
            calls = [item for item in items if item.get("type") == "function_call"]
            if not calls:
                if not response.output_text.strip():
                    raise failure("model returned no final text")
                return AgentResult(response.output_text, history, events)
            for call in calls:
                name, arguments = call["name"], None
                try:
                    if name not in allowed:
                        raise ValueError(f"tool {name!r} is not allowed for {role}")
                    arguments = json.loads(call["arguments"])
                    validate(arguments, specs[name])
                    arguments = decode_arguments(name, arguments)
                    result = (handler(name, arguments) if handler else
                              dispatch_tool(name, arguments, allowed_tools=allowed))
                except (ValueError, TypeError, KeyError) as exc:
                    result = {"error": str(exc)}
                events.append({"name": name, "arguments": arguments, "result": result})
                history.append({"type": "function_call_output", "call_id": call["call_id"],
                                "output": json.dumps(result, ensure_ascii=False)})
        raise failure(f"{role} exceeded per-agent model call limit")
