import copy
import io
import json
import tempfile
import unittest
from dataclasses import replace
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from budget import BudgetExceeded, BudgetLedger, token_cost
from agents import decode_arguments
from config import Settings
from llm_client import OpenAIClient
from metric import evaluate_plan, evaluate_revision, extract_plan as metric_extract_plan
from orchestrator import MealChatbot
from presentation import render_plan
from replay import saved_conversation
from run_eval import run_cases
from schemas import validate_constraints
from session import Session
from tool_calling_function import FOOD_DB, check_plan, check_revision, dispatch_tool


HERE = Path(__file__).resolve().parents[1]
CASES = json.loads((HERE / "diet_persona_test_cases_10.json").read_text(encoding="utf-8"))


def tool(name, arguments):
    if name == "search_foods":
        defaults = {k: None for k in (
            "cuisine_types", "excluded_cuisine_types", "excluded_allergens", "excluded_food_codes",
            "required_tags", "excluded_tags", "kcal_min", "kcal_max", "protein_min", "protein_max",
            "sodium_max", "price_max")}
        arguments = {**defaults, **arguments}
    if name == "compute_plan" and "plan" in arguments:
        arguments = {"slots": [{"slot": s, "food_codes": codes} for s, codes in arguments["plan"].items()]}
    return SimpleNamespace(status="completed", output_text="", output=[{
        "type": "function_call", "call_id": name + "_call", "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False),
    }])


def final(value):
    text = json.dumps(value, ensure_ascii=False)
    return SimpleNamespace(status="completed", output_text=text, output=[{
        "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}],
    }])


class ScriptedClient:
    """Deterministic model stand-in, not an LLM success-rate measurement."""
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        return next(self.responses)


def planner(plan, search=True):
    return ([tool("search_foods", {})] if search else []) + [
        tool("compute_plan", {"plan": plan}), final({"plan": plan})]


def reviewer(plan, constraints, previous=None, preserve=None, change=None, claimed=True):
    responses = [tool("check_plan", {"user_constraint": constraints})]
    if previous:
        responses.append(tool("check_revision", {
                         "preserve_slots": preserve or [], "change_slots": change or [],
                         "allowed_change_slots": change if change else None}))
    return responses + [final({"passed": claimed, "feedback": "" if claimed else "fix violations"})]


class WorkflowTests(unittest.TestCase):
    def test_failed_allergy_check_overrides_model_approval_and_repairs(self):
        case = CASES[4]
        bad = {"day1_lunch": ["F020"], "day1_dinner": ["F008"]}
        good = {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}
        fake = ScriptedClient(planner(bad) + reviewer(bad, case["user_constraint"])
                              + planner(good, search=False) + reviewer(good, case["user_constraint"]))
        session = Session()
        result = MealChatbot(fake, Settings()).respond(session, case["test_query"])
        self.assertEqual(result.status, "approved")
        self.assertEqual(len(result.rounds), 2)
        self.assertEqual(session.accepted_plan, good)
        self.assertTrue(all(c["passed"] for c in evaluate_plan(result.plan, case)))
        self.assertIn("excluded allergen", " ".join(result.rounds[0]["feedback"]))
        # Reviewer only sees user originals and plan JSON, never planner narration/tools.
        request = next(r for r in fake.requests if any(t["name"] == "check_plan" for t in r["tools"]))
        context = json.loads(request["messages"][0]["content"])
        self.assertEqual(set(context), {"original_user_turns", "candidate_plan", "previous_plan"})

    def test_follow_up_preserves_lunch_and_rechecks_full_constraints(self):
        case = CASES[9]
        old = {"day1_lunch": ["F048"], "day1_dinner": ["F024"]}
        new = {"day1_lunch": ["F048"], "day1_dinner": ["F047"]}
        fake = ScriptedClient(planner(old) + reviewer(old, case["user_constraint"])
                              + planner(new) + reviewer(new, case["user_constraint"], old,
                                                        ["day1_lunch"], ["day1_dinner"]))
        session, bot = Session(), MealChatbot(fake, Settings())
        self.assertEqual(bot.respond(session, case["test_query"]).status, "approved")
        result = bot.respond(session, case["follow_up_query"])
        self.assertEqual(result.status, "approved")
        self.assertTrue(all(c["passed"] for c in evaluate_revision(old, new, case)))
        contexts = [json.loads(r["messages"][0]["content"]) for r in fake.requests
                    if any(t["name"] == "check_plan" for t in r["tools"])]
        self.assertEqual(contexts[-1]["original_user_turns"],
                         [case["test_query"], case["follow_up_query"]])

    def test_old_approval_does_not_override_new_budget(self):
        case = CASES[9]
        old = {"day1_lunch": ["F048"], "day1_dinner": ["F024"]}
        tightened = copy.deepcopy(case["user_constraint"])
        tightened["constraints"]["budget_krw"]["total_max"] = 12000
        fake = ScriptedClient(planner(old) + reviewer(old, tightened, old))
        session = Session(user_turns=[case["test_query"]], accepted_plan=old, accepted_at_turn=1)
        result = MealChatbot(fake, replace(Settings(), max_rounds=1)).respond(
            session, "총예산을 12,000원으로 낮춰줘.")
        self.assertEqual(result.status, "not_verified")
        self.assertIsNone(result.plan)
        self.assertEqual(session.accepted_plan, old)  # Historical baseline only.
        self.assertFalse(session.has_current_plan)

    def test_model_cannot_approve_without_checker_execution(self):
        plan = {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}
        fake = ScriptedClient(planner(plan) + [final({"passed": True, "feedback": ""})])
        result = MealChatbot(fake, replace(Settings(), max_rounds=1)).respond(Session(), CASES[4]["test_query"])
        self.assertEqual(result.status, "not_verified")

    def test_checker_cannot_substitute_a_different_candidate(self):
        bad = {"day1_lunch": ["F020"], "day1_dinner": ["F008"]}
        other = {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}
        fake = ScriptedClient(planner(bad) + [
            tool("check_plan", {"plan": other, "user_constraint": CASES[4]["user_constraint"]}),
            final({"passed": True, "feedback": ""})])
        result = MealChatbot(fake, replace(Settings(), max_rounds=1)).respond(Session(), CASES[4]["test_query"])
        self.assertEqual(result.status, "not_verified")
        self.assertIn("Additional properties", " ".join(result.rounds[0]["feedback"]))

    def test_revision_checker_is_mandatory_after_previous_approval(self):
        old = {"day1_lunch": ["F048"], "day1_dinner": ["F024"]}
        new = {"day1_lunch": ["F048"], "day1_dinner": ["F047"]}
        fake = ScriptedClient(planner(new) + reviewer(new, CASES[9]["user_constraint"]))
        session = Session(user_turns=[CASES[9]["test_query"]], accepted_plan=old, accepted_at_turn=1)
        result = MealChatbot(fake, replace(Settings(), max_rounds=1)).respond(session, CASES[9]["follow_up_query"])
        self.assertEqual(result.status, "not_verified")

    def test_tool_history_survives_agent_call_limit(self):
        fake = ScriptedClient([tool("search_foods", {})])
        session = Session()
        result = MealChatbot(fake, replace(Settings(), max_rounds=1, max_agent_calls=1)).respond(
            session, CASES[0]["test_query"])
        self.assertEqual(result.status, "not_verified")
        self.assertEqual(result.rounds[0]["planner_tools"][0]["name"], "search_foods")
        self.assertTrue(any(m.get("type") == "function_call_output" for m in session.planner_history))

    def test_benchmark_labels_never_enter_chatbot(self):
        class SpyBot:
            def __init__(self):
                self.queries = []

            def respond(self, session, query):
                from orchestrator import TurnResult
                self.queries.append(query)
                return TurnResult("approved", "{}")
        spy = SpyBot()
        with redirect_stdout(io.StringIO()):
            run_cases(spy, [CASES[9]])
        self.assertEqual(spy.queries, [CASES[9]["test_query"], CASES[9]["follow_up_query"]])


class CheckerTests(unittest.TestCase):
    def test_duplicate_wire_slots_cannot_overwrite_a_meal(self):
        with self.assertRaisesRegex(ValueError, "duplicate slots"):
            decode_arguments("compute_plan", {"slots": [
                {"slot": "day1_lunch", "food_codes": ["F020"]},
                {"slot": "day1_lunch", "food_codes": ["F048"]},
            ]})

    def test_food_precision_matches_independent_metric(self):
        constraints = copy.deepcopy(CASES[3]["user_constraint"])
        constraints["plan"] = {"days": 1, "meals_per_day": ["lunch"]}
        constraints["constraints"]["nutrition"]["per_meal"]["protein_g"]["min"] = 32.3
        plan = {"day1_lunch": ["F010"]}
        self.assertEqual(FOOD_DB["F010"]["protein_g"], 32.27)
        self.assertFalse(check_plan(plan, constraints)["passed"])
        self.assertTrue(any(not c["passed"] for c in evaluate_plan(plan, {"user_constraint": constraints})))

    def test_revision_rejects_quantity_change_and_unrequested_change(self):
        old = {"day1_lunch": ["F048", "F048"], "day1_dinner": ["F024"]}
        new = {"day1_lunch": ["F048"], "day1_dinner": ["F047"]}
        result = check_revision(new, old, ["day1_lunch"], ["day1_dinner"], ["day1_dinner"])
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["violations"]), 2)

    def test_missing_constraint_and_role_tool_escape_rejected(self):
        with self.assertRaises(ValueError):
            validate_constraints({"plan": {"days": 1, "meals_per_day": ["lunch"]}})
        self.assertIn("error", dispatch_tool("check_plan", {}, allowed_tools=["search_foods"]))

    def test_non_db_allergen_cannot_silently_pass(self):
        constraints = copy.deepcopy(CASES[4]["user_constraint"])
        constraints["constraints"]["excluded_allergens"] = ["shrimp"]
        with self.assertRaisesRegex(ValueError, "exact DB vocabulary"):
            check_plan({"day1_lunch": ["F020"], "day1_dinner": ["F008"]}, constraints)


class PresentationTests(unittest.TestCase):
    def test_natural_revision_has_correct_values_and_no_internal_identifiers(self):
        old = {"day1_lunch": ["F024"], "day1_dinner": ["F048"]}
        new = {"day1_lunch": ["F024"], "day1_dinner": ["F033"]}
        answer = render_plan(new, previous_plan=old, user_constraint=CASES[9]["user_constraint"])
        self.assertIn("점심 메뉴는 잔치국수 그대로 유지", answer)
        self.assertIn("된장찌개 대신 소시지볶음", answer)
        self.assertIn("12,000원", answer)
        self.assertIn("21,000원 이내", answer)
        self.assertIn("560kcal", answer)
        self.assertIn("새우", answer)
        for internal in ("day1_", "F024", "F033", "```", '"plan"', "approved"):
            self.assertNotIn(internal, answer)

    def test_natural_answers_and_machine_evaluation_use_separate_fields(self):
        case = CASES[4]
        plan = {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}
        fake = ScriptedClient(planner(plan) + reviewer(plan, case["user_constraint"]))
        bot = MealChatbot(fake, Settings())
        with redirect_stdout(io.StringIO()):
            outputs, _, traces = run_cases(bot, [case])
        self.assertEqual(metric_extract_plan(outputs["T05"]["output"]), plan)
        self.assertIn("점심 메뉴", traces["T05"][0]["answer"])
        self.assertNotIn("```", traces["T05"][0]["answer"])

    def test_saved_record_replay_needs_no_model_or_api_key(self):
        case = CASES[9]
        plan = {"day1_lunch": ["F024"], "day1_dinner": ["F048"]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "outputs.json").write_text(json.dumps({"T10": {"output": {"plan": plan}}}))
            (base / "traces.json").write_text(json.dumps({"T10": [{"status": "approved", "rounds": []}]}))
            (base / "usage.json").write_text(json.dumps({"settings": {"planner_model": "saved", "verifier_model": "saved"}}))
            settings, messages = saved_conversation(base, case)
        self.assertEqual(settings["planner_model"], "saved")
        self.assertEqual(messages[0], ("사용자", case["test_query"]))
        self.assertIn("잔치국수", messages[1][1])
        self.assertIn("반환하지 못했어요", messages[-1][1])


class BudgetTests(unittest.TestCase):
    def test_shared_ledger_reserves_settles_and_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = BudgetLedger(path, 0.01)
            key = ledger.reserve("gpt-5-mini", 1000, 3000)
            with self.assertRaises(BudgetExceeded):
                BudgetLedger(path, 0.01).reserve("gpt-5-mini", 1000, 3000)
            cost = ledger.settle(key, 1000, 100, 500)
            self.assertAlmostEqual(cost, token_cost("gpt-5-mini", 1000, 100, 500))
            self.assertEqual(BudgetLedger(path, 0.01).summary()["calls"], 1)
            self.assertAlmostEqual(ledger.summary()["spent_usd"], cost)

    def test_transport_sends_model_specific_options_and_counts_hidden_output(self):
        class SDK:
            def __init__(self):
                self.responses = self
                self.requests = []

            def create(self, **request):
                self.requests.append(request)
                return SimpleNamespace(status="completed", usage=SimpleNamespace(
                    input_tokens=100, output_tokens=1500,
                    input_tokens_details=SimpleNamespace(cached_tokens=0)))
        with tempfile.TemporaryDirectory() as tmp:
            sdk = SDK()
            ledger = BudgetLedger(Path(tmp) / "ledger.json", 1)
            client = OpenAIClient(ledger, Settings(), sdk_client=sdk)
            for model in ("gpt-4o-mini", "gpt-5-mini"):
                client.create(model=model, instructions="test", messages=[], tools=[])
            self.assertIn("temperature", sdk.requests[0])
            self.assertNotIn("reasoning", sdk.requests[0])
            self.assertNotIn("temperature", sdk.requests[1])
            self.assertEqual(sdk.requests[1]["reasoning"], {"effort": "low"})
            self.assertIn("reasoning.encrypted_content", sdk.requests[1]["include"])
            self.assertEqual(sdk.requests[0]["text"], {"format": {"type": "json_object"}})
            self.assertIn("JSON", sdk.requests[0]["input"][0]["content"])
            self.assertAlmostEqual(client.usage[1]["cost_usd"], 0.003025)

    def test_unknown_request_outcome_retains_budget_reservation(self):
        class BrokenSDK:
            @property
            def responses(self):
                return self

            def create(self, **kwargs):
                raise TimeoutError("sensitive details must not be propagated")
        with tempfile.TemporaryDirectory() as tmp:
            ledger = BudgetLedger(Path(tmp) / "ledger.json", 1)
            client = OpenAIClient(ledger, Settings(), sdk_client=BrokenSDK())
            with self.assertRaisesRegex(RuntimeError, "TimeoutError"):
                client.create(model="gpt-4o-mini", instructions="", messages=[], tools=[])
            self.assertGreater(ledger.summary()["spent_usd"], 0)
            self.assertEqual(ledger.summary()["uncertain_calls"], 1)


if __name__ == "__main__":
    unittest.main()
