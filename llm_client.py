"""OpenAI Responses transport. No SDK or API key is needed for offline tests."""
import os
import re
import time

from budget import BudgetExceeded, input_reservation_tokens, model_family, token_cost


class OpenAIClient:
    def __init__(self, ledger, settings, sdk_client=None):
        self.ledger, self.settings = ledger, settings
        model_family(settings.planner_model)
        model_family(settings.verifier_model)
        if sdk_client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is not set. Export it locally before live execution.")
            from openai import OpenAI
            sdk_client = OpenAI(max_retries=0, timeout=45.0)
        self.sdk = sdk_client
        self.usage = []
        self.call_context = {}

    def create(self, *, model, instructions, messages, tools):
        # The API's JSON-mode guard inspects input messages, not just instructions.
        input_messages = [{"role": "developer", "content":
                           "최종 응답은 Markdown 없이 JSON 객체 하나만 반환하세요. "
                           "답변 전에 지시에 따라 제공된 함수를 사용하세요."}, *messages]
        request = dict(model=model, instructions=instructions, input=input_messages, tools=tools,
                       max_output_tokens=self.settings.max_output_tokens,
                       parallel_tool_calls=False, store=False,
                       text={"format": {"type": "json_object"}})
        if model_family(model) == "gpt-5-mini":
            request["reasoning"] = {"effort": self.settings.reasoning_effort}
            request["include"] = ["reasoning.encrypted_content"]
        else:
            request["temperature"] = 0
        input_bound = input_reservation_tokens(request)
        context = dict(self.call_context)
        try:
            key = self.ledger.reserve(model, input_bound, request["max_output_tokens"])
        except BudgetExceeded:
            self.usage.append({**context, "model": model, "status": "budget_exceeded",
                               "api_called": False, "cost_usd": 0.0, "latency_seconds": 0.0})
            raise
        start = time.monotonic()
        try:
            response = self.sdk.responses.create(**request)
            if response.usage is None:
                raise RuntimeError("API response has no usage; cannot settle spend")
            details = response.usage.input_tokens_details
            cached = getattr(details, "cached_tokens", 0) if details else 0
            cost = self.ledger.settle(key, response.usage.input_tokens,
                                      response.usage.output_tokens, cached)
        except Exception as exc:
            self.ledger.uncertain(key)
            self.usage.append({**context, "model": model, "status": "api_error",
                "api_called": True, "cost_usd": token_cost(model, input_bound, request["max_output_tokens"]),
                "cost_is_reservation": True, "input_tokens": None, "output_tokens": None,
                "latency_seconds": time.monotonic() - start})
            # Never dump requests, headers or error bodies that might contain secrets.
            body = getattr(exc, "body", None)
            detail = ""
            if isinstance(body, dict):
                error = body.get("error", body)
                if isinstance(error, dict):
                    message = str(error.get("message", ""))
                    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", message)
                    detail = ": " + message[:600]
            raise RuntimeError(f"OpenAI request failed ({type(exc).__name__}); "
                               "its maximum cost reservation was retained" + detail) from None
        self.usage.append({**context, "model": model, "api_called": True,
                           "input_tokens": response.usage.input_tokens,
                           "cached_tokens": cached, "output_tokens": response.usage.output_tokens,
                           "cost_usd": cost, "latency_seconds": time.monotonic() - start,
                           "status": response.status})
        return response
