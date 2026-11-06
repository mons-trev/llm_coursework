"""Planner first, verifier second. Benchmark labels never enter this module."""
import copy
import json
import time
from dataclasses import asdict, dataclass, field

from agents import AgentError, AgentRunner
from budget import BudgetExceeded
from presentation import render_plan
from schemas import VERDICT_SCHEMA, extract_json, extract_plan, validate
from session import Session
from tool_calling_function import dispatch_tool, VERIFIER_TOOLS


@dataclass
class TurnResult:
    status: str
    answer: str
    plan: dict | None = None
    rounds: list = field(default_factory=list)
    mode: str = "planner_verifier"
    termination_reason: str | None = None
    elapsed_seconds: float = 0.0
    model_calls: int = 0

    def to_dict(self):
        return asdict(self)


class MealChatbot:
    def __init__(self, client, settings):
        self.settings = settings
        self.runner = AgentRunner(client, settings)
        self.trace_context = {}  # Evaluation metadata; never added to model messages.

    def respond(self, session: Session, query: str):
        if not query.strip():
            raise ValueError("사용자 요청이 비어 있습니다.")
        session.ensure_mode(self.settings.mode)
        start = time.monotonic()
        if not session.planner_history:
            session.planner_history = [{"role": "user", "content": q} for q in session.user_turns]
        session.user_turns.append(query)
        session.planner_history.append({"role": "user", "content": query})
        baseline = copy.deepcopy(session.last_returned_plan)
        if baseline:
            session.planner_history.append({"role": "developer", "content":
                "이전 반환 식단은 비교 기준입니다. 현재 사용자 요청의 조건으로 전체 식단을 다시 검사하세요:\n"
                + json.dumps(baseline, ensure_ascii=False)})
        attempts, planner_events, calls = [], [], 0

        def before_call():
            nonlocal calls
            if calls >= self.settings.max_turn_calls:
                raise AgentError("per-user-turn model call limit reached")
            calls += 1

        def finish(result):
            result.mode = self.settings.mode
            result.elapsed_seconds = time.monotonic() - start
            result.model_calls = calls
            if result.plan is not None and result.status in {"approved", "generated"}:
                session.last_returned_plan = copy.deepcopy(result.plan)
                session.returned_at_turn = len(session.user_turns)
            session.results.append(result.to_dict())
            return result

        def run_agent(role, messages, round_number, **kwargs):
            self.runner.client.call_context = {**self.trace_context, "mode": self.settings.mode,
                "role": role, "turn": len(session.user_turns), "round": round_number}
            return self.runner.run(role, messages, before_call, **kwargs)

        last_reason = "candidate_not_submitted"
        for round_number in range(1, self.settings.max_rounds + 1):
            trace = {"round": round_number, "baseline": copy.deepcopy(baseline)}
            attempts.append(trace)
            feedback = []
            phase = "planner"
            try:
                proposed = run_agent("planner", session.planner_history, round_number)
                session.planner_history = proposed.messages
                planner_events.extend(proposed.events)
                trace.update(planner_output=proposed.text, planner_tools=proposed.events)
                phase = "execution_conditions"
                try:
                    candidate = extract_plan(proposed.text)
                except ValueError as exc:
                    raise ValueError("전체 plan 을 포함한 JSON 객체를 반환하세요. "
                                     "예: {\"plan\": {\"day1_lunch\": [\"F020\"]}}. " + str(exc)) from exc
                trace["candidate"] = candidate
                searches = [e for e in planner_events if e["name"] == "search_foods"
                            and isinstance(e["result"], list)]
                retrieved = {r["food_code"] for e in searches for r in e["result"]}
                if baseline:
                    retrieved.update(c for codes in baseline.values() for c in codes)
                if not searches:
                    feedback.append("식단을 제안하기 전에 search_foods 를 호출하세요.")
                if any(c not in retrieved for codes in candidate.values() for c in codes):
                    feedback.append("검색에 성공한 결과나 이전 식단에 있는 food_code 만 사용하세요.")
                computed = [e for e in proposed.events if e["name"] == "compute_plan"
                            and e["arguments"].get("plan") == candidate
                            and "error" not in e["result"]]
                if not computed:
                    feedback.append("답변 전에 현재 최종 후보와 동일한 식단으로 compute_plan 을 호출하세요.")
                if feedback:
                    raise ValueError("; ".join(feedback))
                trace["execution_conditions_passed"] = True
                if self.settings.mode == "planner_only":
                    # No constraint checker, review feedback, or gold labels on this path.
                    answer = render_plan(candidate, previous_plan=baseline, status="generated")
                    return finish(TurnResult("generated", answer, candidate, attempts,
                                             termination_reason="returned_unverified"))

                phase = "verifier"
                def reviewer_tool(name, arguments):
                    # Already-known plans never need to be generated as tool arguments.
                    arguments["plan"] = copy.deepcopy(candidate)
                    if name == "check_revision":
                        if baseline is None:
                            return {"error": "비교할 이전 승인 식단이 없습니다."}
                        arguments["previous_plan"] = copy.deepcopy(baseline)
                    return dispatch_tool(name, arguments, allowed_tools=VERIFIER_TOOLS)

                reviewed = run_agent("verifier", [{"role": "user", "content": json.dumps({
                    "original_user_turns": session.user_turns,
                    "candidate_plan": candidate, "previous_plan": baseline,
                }, ensure_ascii=False)}], round_number, handler=reviewer_tool)
                trace.update(verifier_output=reviewed.text, verifier_tools=reviewed.events)
                verdict = extract_json(reviewed.text)
                validate(verdict, VERDICT_SCHEMA)
                required = ["check_plan"] + (["check_revision"] if baseline else [])
                feedback = []
                for name in required:
                    checks = [e for e in reviewed.events if e["name"] == name]
                    if not checks:
                        feedback.append(f"Verifier 가 {name} 을 실행하지 않아 승인할 수 없습니다.")
                    else:
                        result = checks[-1]["result"]
                        if result.get("passed") is not True:
                            feedback.extend(result.get("violations", [result.get("error", name + " failed")]))
                if verdict["passed"] and not feedback:
                    session.accepted_plan = copy.deepcopy(candidate)
                    session.accepted_at_turn = len(session.user_turns)
                    trace["passed"] = True
                    checked_constraints = next(e["arguments"]["user_constraint"]
                                               for e in reversed(reviewed.events) if e["name"] == "check_plan")
                    answer = render_plan(candidate, previous_plan=baseline, user_constraint=checked_constraints)
                    return finish(TurnResult("approved", answer, candidate, attempts,
                                             termination_reason="verified"))
                if verdict["feedback"]:
                    feedback.append(verdict["feedback"])
                if not feedback:
                    feedback.append("Verifier 가 이유를 설명하지 않고 후보를 거절했습니다.")
                last_reason = "verifier_rejected"
            except BudgetExceeded as exc:
                trace["error"] = str(exc)
                return finish(TurnResult("budget_exceeded", "챗봇의 사용 한도에 도달해 "
                                         "이번 요청을 완료하지 못했어요.", rounds=attempts,
                                         termination_reason="budget_exceeded"))
            except AgentError as exc:
                if exc.role:
                    trace[exc.role + "_tools"] = exc.events
                    if exc.role == "planner":
                        session.planner_history = exc.history
                        planner_events.extend(exc.events)
                feedback = [str(exc)]
                last_reason = "call_limit" if "limit" in str(exc) else "candidate_not_submitted"
                if phase == "verifier" and last_reason != "call_limit":
                    last_reason = "technical_execution_failure"
            except (ValueError, TypeError, KeyError) as exc:
                feedback = [str(exc)]
                last_reason = "technical_execution_failure"
            except RuntimeError as exc:
                trace["error"] = str(exc)
                return finish(TurnResult("api_error", "모델 연결에 문제가 생겨 요청을 완료하지 못했어요. "
                                         "잠시 후 다시 시도해 주세요.", rounds=attempts,
                                         termination_reason="api_error"))
            trace.update(passed=False, feedback=feedback, failure_phase=phase,
                         failure_reason=last_reason)
            session.planner_history.append({"role": "developer", "content":
                "내부 실행 피드백입니다. 새로운 사용자 요청이 아니므로 사용자 조건을 완화하지 마세요:\n"
                + json.dumps(feedback, ensure_ascii=False)})
        return finish(TurnResult("not_verified", "현재 조건을 모두 만족하는 식단을 아직 찾지 못했어요. "
                                 "다시 요청해 주시면 조건을 유지하면서 다른 조합을 찾아볼게요.", rounds=attempts,
                                 termination_reason=last_reason))
