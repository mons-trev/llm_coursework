"""Scripted/offline regression checks. These are NOT model evaluations."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from budget import BudgetExceeded, BudgetLedger
from compare_ablation import aggregate, analyze_run, main as compare_main
from config import Settings
from llm_client import OpenAIClient
from metric import evaluate_all, evaluate_case
from orchestrator import MealChatbot
from presentation import render_plan
from replay import main as replay_main, saved_conversation
from run_eval import main as eval_main, provenance, run_cases, write_json
from session import Session
from test_workflow import CASES, HERE, ScriptedClient, final, planner, reviewer, tool


BAD = {"day1_lunch": ["F020"], "day1_dinner": ["F008"]}
GOOD = {"day1_lunch": ["F020"], "day1_dinner": ["F048"]}


def save_scripted_run(directory, mode, responses, cases=None, repetition=1):
    """Persist the same artifact contract with an explicit non-model label."""
    cases = cases or [CASES[4]]
    settings = Settings(mode=mode)
    client = ScriptedClient(responses)
    bot = MealChatbot(client, settings)
    with redirect_stdout(io.StringIO()):
        outputs, initial, traces = run_cases(bot, cases)
    directory = Path(directory)
    manifest = provenance(settings, HERE / "diet_persona_test_cases_10.json", cases, repetition)
    manifest["kind"] = "scripted_offline_test"
    values = {"outputs": outputs, "initial_outputs": initial, "traces": traces,
              "report": evaluate_all(cases, outputs), "initial_report": evaluate_all(cases, initial),
              "manifest": manifest, "cases": cases,
              "usage": {"settings": asdict(settings), "run_calls": [], "run_cost_usd": 0.0}}
    for name, value in values.items():
        write_json(directory / (name + ".json"), value)
    return values


class AblationWorkflowTests(unittest.TestCase):
    def test_mode_validation_and_default(self):
        self.assertEqual(Settings().mode, "planner_verifier")
        with self.assertRaisesRegex(ValueError, "mode"):
            Settings(mode="invalid")
        for mode in ("planner_only", "planner_verifier"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(eval_main(["--check-only", "--mode", mode]), 0)

    def test_planner_only_returns_bad_candidate_without_any_reviewer_or_check(self):
        client = ScriptedClient(planner(BAD))
        bot, session = MealChatbot(client, Settings(mode="planner_only")), Session()
        with patch("orchestrator.dispatch_tool", side_effect=AssertionError("review executed")), \
             patch("presentation.check_plan", side_effect=AssertionError("presentation check executed")):
            result = bot.respond(session, CASES[4]["test_query"])
        self.assertEqual(result.status, "generated")
        self.assertEqual(result.termination_reason, "returned_unverified")
        self.assertEqual(result.plan, BAD)
        self.assertEqual(session.last_returned_plan, BAD)
        self.assertIsNone(session.accepted_plan)
        self.assertTrue(session.has_current_plan)
        score = evaluate_case(CASES[4], {"output": {"plan": result.plan}})
        self.assertFalse(score["overall_pass"])
        self.assertFalse(score["safety_pass"])
        self.assertTrue(all({t["name"] for t in r["tools"]} == {"search_foods", "compute_plan"} for r in client.requests))
        for text in ("승인", "충족", "이내", "새우 표시가 있는 메뉴는 제외"):
            self.assertNotIn(text, result.answer)

    def test_same_bad_candidate_is_blocked_by_verifier(self):
        client = ScriptedClient(planner(BAD) + reviewer(BAD, CASES[4]["user_constraint"]))
        result = MealChatbot(client, Settings(max_rounds=1)).respond(Session(), CASES[4]["test_query"])
        self.assertEqual(result.status, "not_verified")
        self.assertEqual(result.termination_reason, "verifier_rejected")
        self.assertIsNone(result.plan)
        self.assertIn("excluded allergen", " ".join(result.rounds[0]["feedback"]))

    def test_multiple_search_and_compute_calls_allow_planner_self_correction(self):
        client = ScriptedClient([tool("search_foods", {}), tool("compute_plan", {"plan": BAD}),
                                 tool("search_foods", {"excluded_allergens": ["새우"]}),
                                 tool("compute_plan", {"plan": GOOD}), final({"plan": GOOD})])
        result = MealChatbot(client, Settings(mode="planner_only")).respond(Session(), CASES[4]["test_query"])
        self.assertEqual(result.status, "generated")
        self.assertEqual(result.plan, GOOD)
        self.assertEqual(result.model_calls, 5)

    def test_common_execution_conditions_and_retry_feedback_match_across_modes(self):
        scenarios = [
            [final({"plan": GOOD})],  # no tools
            [tool("search_foods", {"cuisine_types": ["중식"]}), tool("compute_plan", {"plan": GOOD}), final({"plan": GOOD})],
            [tool("search_foods", {}), tool("compute_plan", {"plan": BAD}), final({"plan": GOOD})],
            [final({"plan": {"invalid_slot": ["F020"]}})],
            [final("malformed json")],
        ]
        for responses in scenarios:
            traces = []
            for mode in ("planner_only", "planner_verifier"):
                with self.subTest(mode=mode, scenario=responses):
                    client = ScriptedClient(responses + planner(GOOD) + (reviewer(GOOD, CASES[4]["user_constraint"]) if mode == "planner_verifier" else []))
                    result = MealChatbot(client, Settings(mode=mode)).respond(Session(), CASES[4]["test_query"])
                    self.assertEqual(result.status, "generated" if mode == "planner_only" else "approved")
                    self.assertEqual(result.rounds[0]["failure_reason"], "technical_execution_failure")
                    self.assertNotIn("verifier_tools", result.rounds[0])
                    traces.append(result.rounds[0]["feedback"])
            self.assertEqual(*traces)

    def test_t10_uses_actual_bad_return_as_follow_up_baseline_and_saves_both(self):
        case = copy.deepcopy(CASES[9])
        # Marker labels must never be copied into input or feedback.
        case.update(test_id="SECRET_CASE_ID", persona="SECRET_PERSONA", objective="SECRET_OBJECTIVE")
        old = {"day1_lunch": ["F008"], "day1_dinner": ["F024"]}
        new = {"day1_lunch": ["F008"], "day1_dinner": ["F047"]}
        client = ScriptedClient(planner(old) + planner(new))
        bot = MealChatbot(client, Settings(mode="planner_only"))
        with redirect_stdout(io.StringIO()):
            outputs, _, traces = run_cases(bot, [case])
        self.assertEqual(outputs[case["test_id"]]["output"]["plan"], old)
        self.assertEqual(outputs[case["test_id"]]["follow_up_output"]["plan"], new)
        self.assertEqual(traces[case["test_id"]][1]["rounds"][0]["baseline"], old)
        self.assertFalse(evaluate_case(case, outputs[case["test_id"]])["overall_pass"])
        all_inputs = json.dumps(client.requests, ensure_ascii=False)
        for secret in ("SECRET_CASE_ID", "SECRET_PERSONA", "SECRET_OBJECTIVE", "expected_revision", "user_constraint", "preserve_slots"):
            self.assertNotIn(secret, all_inputs)
        self.assertIn(json.dumps(old, ensure_ascii=False),
                      "\n".join(str(m.get("content", "")) for m in client.requests[-1]["messages"]))

    def test_first_and_follow_up_planner_prompts_and_tools_are_identical(self):
        case = CASES[9]
        old = {"day1_lunch": ["F048"], "day1_dinner": ["F024"]}
        new = {"day1_lunch": ["F048"], "day1_dinner": ["F047"]}
        clients = []
        for mode in ("planner_only", "planner_verifier"):
            responses = planner(old)
            if mode == "planner_verifier":
                responses += reviewer(old, case["user_constraint"])
            responses += planner(new)
            if mode == "planner_verifier":
                responses += reviewer(new, case["user_constraint"], old, ["day1_lunch"], ["day1_dinner"])
            client = ScriptedClient(responses)
            with redirect_stdout(io.StringIO()):
                run_cases(MealChatbot(client, Settings(mode=mode)), [case])
            clients.append([r for r in client.requests if r["tools"][0]["name"] == "search_foods"])
        self.assertEqual(*clients)

    def test_poisoned_gold_labels_never_enter_input_or_technical_feedback_in_either_mode(self):
        case = copy.deepcopy(CASES[4])
        case.update(test_id="SECRET_ID", persona="SECRET_PERSONA", description="SECRET_DESCRIPTION",
                    expected_revision={"preserve_slots": ["SECRET_SLOT"]})
        case["user_constraint"]["constraints"]["budget_krw"]["total_max"] = 987654321
        for mode in ("planner_only", "planner_verifier"):
            responses = [final({"plan": GOOD})] + planner(GOOD)
            if mode == "planner_verifier":
                responses += reviewer(GOOD, CASES[4]["user_constraint"])
            client = ScriptedClient(responses)
            with redirect_stdout(io.StringIO()):
                run_cases(MealChatbot(client, Settings(mode=mode)), [case])
            text = json.dumps(client.requests)
            for label in ("SECRET_ID", "SECRET_PERSONA", "SECRET_DESCRIPTION", "SECRET_SLOT", "987654321"):
                self.assertNotIn(label, text)

    def test_planner_cannot_execute_runtime_checker_by_requesting_forbidden_tool(self):
        client = ScriptedClient([tool("search_foods", {}), tool("check_plan", {}),
                                 tool("compute_plan", {"plan": BAD}), final({"plan": BAD})])
        with patch("tool_calling_function.check_plan", side_effect=AssertionError("check executed")), \
             patch("presentation.check_plan", side_effect=AssertionError("check executed")), \
             patch("orchestrator.dispatch_tool", side_effect=AssertionError("verifier executed")):
            result = MealChatbot(client, Settings(mode="planner_only")).respond(Session(), CASES[4]["test_query"])
        self.assertEqual(result.status, "generated")
        escaped = result.rounds[0]["planner_tools"][1]
        self.assertIn("not allowed for planner", escaped["result"]["error"])

    def test_failure_does_not_overwrite_returned_or_accepted_baseline(self):
        for mode in ("planner_only", "planner_verifier"):
            session = Session(user_turns=["old"], last_returned_plan=GOOD, returned_at_turn=1, mode=mode,
                              accepted_plan=GOOD if mode == "planner_verifier" else None, accepted_at_turn=1)
            client = ScriptedClient([final({"plan": GOOD})])
            result = MealChatbot(client, Settings(mode=mode, max_rounds=1)).respond(session, "new")
            self.assertIsNone(result.plan)
            self.assertEqual(session.last_returned_plan, GOOD)
            self.assertFalse(session.has_current_plan)
            self.assertEqual(result.termination_reason, "technical_execution_failure")

    def test_session_roundtrip_legacy_upgrade_and_mode_mixing(self):
        old = Session(user_turns=["old"], accepted_plan=GOOD, accepted_at_turn=1)
        self.assertEqual(old.mode, "planner_verifier")
        self.assertTrue(old.has_current_plan)
        with self.assertRaisesRegex(ValueError, "session mode"):
            MealChatbot(ScriptedClient([]), Settings(mode="planner_only")).respond(old, "new")
        self.assertEqual(old.user_turns, ["old"])
        new = Session(mode="planner_only", user_turns=["old"], last_returned_plan=BAD, returned_at_turn=1)
        restored = Session(**json.loads(json.dumps(asdict(new))))
        self.assertEqual(restored.last_returned_plan, BAD)
        self.assertIsNone(restored.accepted_plan)
        self.assertTrue(restored.has_current_plan)
        with self.assertRaisesRegex(ValueError, "session mode"):
            restored.ensure_mode("planner_verifier")

    def test_call_limit_api_and_budget_failures_are_distinct_in_both_modes(self):
        for mode in ("planner_only", "planner_verifier"):
            result = MealChatbot(ScriptedClient([tool("search_foods", {})]),
                                 Settings(mode=mode, max_rounds=1, max_agent_calls=1)).respond(Session(), "request")
            self.assertEqual(result.termination_reason, "call_limit")
            for error, status in ((BudgetExceeded("budget"), "budget_exceeded"), (RuntimeError("api"), "api_error")):
                client = ScriptedClient([])
                with patch.object(client, "create", side_effect=error):
                    result = MealChatbot(client, Settings(mode=mode)).respond(Session(), "request")
                self.assertEqual(result.status, status)
                self.assertEqual(result.termination_reason, status)
                self.assertIsNone(result.plan)

    def test_generated_display_cannot_call_checker_even_if_constraints_are_supplied(self):
        with patch("presentation.check_plan", side_effect=AssertionError("checker ran")):
            answer = render_plan(BAD, status="generated", user_constraint=CASES[4]["user_constraint"])
        self.assertIn("검수 없이", answer)
        self.assertNotIn("조건을 충족", answer)


class ArtifactAndComparisonTests(unittest.TestCase):
    def test_saved_planner_only_replay_and_comparison_work_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            po, pv = base / "po", base / "pv"
            save_scripted_run(po, "planner_only", planner(BAD))
            save_scripted_run(pv, "planner_verifier", planner(BAD) + reviewer(BAD, CASES[4]["user_constraint"])
                              + planner(GOOD, search=False) + reviewer(GOOD, CASES[4]["user_constraint"]))
            with patch("llm_client.OpenAIClient.create", side_effect=AssertionError("API called")), \
                 patch("presentation.check_plan", side_effect=AssertionError("replay check ran")), \
                 redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(replay_main(["--run-dir", str(po), "--case", "T05"]), 0)
                self.assertEqual(compare_main([str(po), str(pv), "--output-dir", str(base / "compare")]), 0)
            self.assertIn("planner_only", stdout.getvalue())
            data = json.loads((base / "compare/comparison.json").read_text())
            only, verified = data["runs"]
            self.assertEqual(only["turn_metrics"]["returned_failed"], 1)
            self.assertEqual(only["turn_metrics"]["allergy_violations"], 1)
            self.assertEqual(verified["summary"]["overall_pass"], 1)
            self.assertEqual(only["conditions"], verified["conditions"])
            self.assertEqual(verified["error_categories"]["wrong_candidate_repaired_after_verifier_feedback"], 1)
            evidence = verified["evidence"][0]
            self.assertEqual(evidence["rounds"][0]["candidate"], BAD)
            self.assertEqual(evidence["final_returned_plan"], GOOD)
            self.assertTrue(evidence["rounds"][0]["verifier_tools"])
            with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                compare_main([str(po), "--output-dir", str(base / "compare")])

    def test_no_return_is_not_allergy_success_and_computations_are_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            save_scripted_run(base, "planner_only", [tool("search_foods", {})] * 18)
            result = analyze_run(base)
        self.assertEqual(result["turn_metrics"]["returned"], 0)
        self.assertEqual(result["turn_metrics"]["not_returned"], 1)
        self.assertEqual(result["turn_metrics"]["allergy_violations"], 0)
        self.assertEqual(result["turn_metrics"]["allergy_returned"], 0)
        self.assertEqual(result["turn_metrics"]["allergy_applicable_turns"], 1)
        self.assertEqual(result["error_categories"]["candidate_not_submitted"], 1)

    def test_intermediate_computations_without_final_candidate_stay_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            responses = [tool("search_foods", {}), tool("compute_plan", {"plan": GOOD})] * 9
            values = save_scripted_run(base, "planner_only", responses)
            result = analyze_run(base)
        self.assertIsNone(values["outputs"]["T05"]["output"])
        self.assertIsNone(values["initial_outputs"]["T05"]["output"])
        self.assertIsNone(result["evidence"][0]["final_returned_plan"])
        self.assertTrue(result["evidence"][0]["rounds"][0]["diagnostic_computations"])
        self.assertNotIn("wrong_candidate_repaired_after_verifier_feedback", result["error_categories"])

    def test_comparison_rejects_tampered_test_or_db_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            values = save_scripted_run(base, "planner_only", planner(GOOD))
            modified = copy.deepcopy(values["cases"])
            modified[0]["test_query"] += "tampered"
            write_json(base / "cases.json", modified)
            with self.assertRaisesRegex(ValueError, "test data hash"):
                analyze_run(base)
            write_json(base / "cases.json", values["cases"])
            manifest = values["manifest"]
            manifest["hashes"]["db"] = "tampered"
            write_json(base / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "DB hash"):
                analyze_run(base)

    def test_blocked_wrong_approval_correct_rejection_and_interpretation_evidence(self):
        relaxed = copy.deepcopy(CASES[4]["user_constraint"])
        relaxed["constraints"]["excluded_allergens"] = []
        scenarios = [
            (planner(BAD) + reviewer(BAD, CASES[4]["user_constraint"]) + [final({"plan": BAD})] * 2, "wrong_candidate_blocked"),
            (planner(BAD) + reviewer(BAD, relaxed), "wrong_candidate_approved"),
            (planner(GOOD) + reviewer(GOOD, CASES[4]["user_constraint"], claimed=False) + [final({"plan": GOOD})] * 2, "correct_candidate_rejected"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for index, (responses, label) in enumerate(scenarios):
                base = Path(tmp) / str(index)
                save_scripted_run(base, "planner_verifier", responses)
                result = analyze_run(base)
                self.assertEqual(result["error_categories"][label], 1)
                if label == "wrong_candidate_approved":
                    self.assertEqual(result["error_categories"]["verifier_constraint_interpretation_mismatch"], 1)

    def test_main_writes_all_artifacts_and_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "run"
            client = ScriptedClient(planner(BAD))
            client.usage = []
            args = ["--mode", "planner_only", "--cases", "T05", "--output-dir", str(base),
                    "--ledger", str(Path(tmp) / "ledger.json"), "--repetition", "2"]
            with patch("run_eval.OpenAIClient", return_value=client), redirect_stdout(io.StringIO()):
                self.assertEqual(eval_main(args), 1)  # Independent evaluation failure, not execution error.
                with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                    eval_main(args)
            for name in ("outputs", "report", "initial_outputs", "initial_report", "traces", "usage", "manifest", "cases"):
                self.assertTrue((base / (name + ".json")).exists(), name)
            manifest = json.loads((base / "manifest.json").read_text())
            self.assertEqual(manifest["repetition"], 2)
            self.assertTrue(manifest["source"]["commit"])
            self.assertIn("agents.py", manifest["hashes"]["source_files"])
            self.assertEqual(manifest["mode"], "planner_only")

    def test_repeat_statistics_include_all_runs_and_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = []
            for index, plan in enumerate((BAD, GOOD), 1):
                directory = Path(tmp) / str(index)
                save_scripted_run(directory, "planner_only", planner(plan), repetition=index)
                runs.append(analyze_run(directory))
            group = aggregate(runs)[0]
        self.assertEqual(group["runs"], 2)
        self.assertEqual(group["statistics"]["overall_rate"], {"mean": 0.5, "min": 0, "max": 1, "n": 2})


class UsageMetadataTests(unittest.TestCase):
    def test_same_model_roles_are_logged_without_metadata_in_model_input(self):
        responses = iter(planner(GOOD) + reviewer(GOOD, CASES[4]["user_constraint"]))
        class SDK:
            def __init__(self):
                self.responses, self.requests = self, []

            def create(self, **request):
                self.requests.append(request)
                result = next(responses)
                result.usage = SimpleNamespace(input_tokens=100, output_tokens=100, input_tokens_details=None)
                return result
        with tempfile.TemporaryDirectory() as tmp:
            sdk = SDK()
            client = OpenAIClient(BudgetLedger(Path(tmp) / "ledger.json", 1), Settings(), sdk_client=sdk)
            with redirect_stdout(io.StringIO()):
                run_cases(MealChatbot(client, Settings()), [CASES[4]])
            roles = [u["role"] for u in client.usage]
            self.assertEqual(roles, ["planner"] * 3 + ["verifier"] * 2)
            for u in client.usage:
                self.assertEqual(u["case_id"], "T05")
                self.assertEqual(u["round"], 1)
                self.assertEqual(u["turn"], 1)
            for request in sdk.requests:
                self.assertNotIn("T05", json.dumps(request, ensure_ascii=False))
                self.assertNotIn("case_id", json.dumps(request))

    def test_failed_calls_keep_role_and_uncertain_cost(self):
        class SDK:
            @property
            def responses(self):
                return self

            def create(self, **request):
                raise TimeoutError("private")
        with tempfile.TemporaryDirectory() as tmp:
            client = OpenAIClient(BudgetLedger(Path(tmp) / "ledger.json", 1), Settings(), sdk_client=SDK())
            client.call_context = {"role": "planner", "case_id": "T08", "turn": 1, "round": 1}
            with self.assertRaises(RuntimeError):
                client.create(model="gpt-4o-mini", instructions="", messages=[], tools=[])
            self.assertEqual(client.usage[0]["role"], "planner")
            self.assertTrue(client.usage[0]["cost_is_reservation"])
            self.assertIsNone(client.usage[0]["input_tokens"])
            self.assertGreater(client.usage[0]["cost_usd"], 0)

    def test_budget_denial_is_recorded_without_api_call_or_ledger_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = BudgetLedger(Path(tmp) / "ledger.json", 0.001)
            sdk = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: self.fail("API called")))
            client = OpenAIClient(ledger, Settings(), sdk_client=sdk)
            client.call_context = {"role": "planner", "case_id": "T08", "turn": 1, "round": 1}
            with self.assertRaises(BudgetExceeded):
                client.create(model="gpt-4o-mini", instructions="", messages=[], tools=[])
            self.assertFalse(client.usage[0]["api_called"])
            self.assertEqual(client.usage[0]["status"], "budget_exceeded")
            self.assertEqual(client.usage[0]["cost_usd"], 0)
            self.assertEqual(ledger.summary()["spent_usd"], 0)


if __name__ == "__main__":
    unittest.main()
