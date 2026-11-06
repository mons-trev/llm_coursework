"""Persistent application-side spend accounting, shared across CLI invocations.

Prices: OpenAI Standard text rates checked 2026-11-05 (USD / 1M tokens).
An uncertain request keeps its entire reservation; automatic retries are disabled.
This ledger only covers calls made through this application, excluding tax.
"""
import fcntl
import json
import math
import os
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


RATES = {"gpt-4o-mini": (0.15, 0.075, 0.60),
         "gpt-5-mini": (0.25, 0.025, 2.00)}


class BudgetExceeded(RuntimeError):
    pass


def model_family(model):
    for family in RATES:
        if re.fullmatch(re.escape(family) + r"(?:-\d{4}-\d{2}-\d{2})?", model):
            return family
    raise ValueError(f"Unpriced model {model!r}; configure verified rates before using it")


def token_cost(model, input_tokens, output_tokens, cached_tokens=0):
    if min(input_tokens, output_tokens, cached_tokens) < 0 or cached_tokens > input_tokens:
        raise ValueError("invalid usage token counts")
    incoming, cached, outgoing = RATES[model_family(model)]
    return ((input_tokens - cached_tokens) * incoming + cached_tokens * cached
            + output_tokens * outgoing) / 1_000_000


def input_reservation_tokens(request):
    # Byte count is deliberately conservative, including tools and replayed history.
    # Extra headroom covers message framing; actual API usage settles the charge.
    content = {k: request[k] for k in ("instructions", "input", "tools") if k in request}
    size = len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    return size + 4096 + 64 * len(request.get("input", []))


class BudgetLedger:
    def __init__(self, path, limit_usd):
        if not math.isfinite(limit_usd) or limit_usd <= 0:
            raise ValueError("budget must be a finite positive number")
        self.path = Path(path)
        self.limit = limit_usd

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = (json.loads(self.path.read_text(encoding="utf-8"))
                    if self.path.exists() else {"spent_usd": 0.0, "calls": {}})
            try:
                yield data
            except BaseException:
                raise
            else:
                temp = self.path.with_name(self.path.name + f".{uuid4().hex}.tmp")
                try:
                    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    os.replace(temp, self.path)
                finally:
                    temp.unlink(missing_ok=True)

    def reserve(self, model, input_tokens, output_tokens):
        amount = token_cost(model, input_tokens, output_tokens)
        with self._locked() as data:
            if data["spent_usd"] + amount > self.limit:
                raise BudgetExceeded(
                    f"API budget: ${data['spent_usd']:.4f} accounted, "
                    f"next reservation ${amount:.4f}, limit ${self.limit:.2f}")
            key = uuid4().hex
            data["spent_usd"] += amount
            data["calls"][key] = {"model": model, "cost_usd": amount,
                                  "status": "reserved", "input_bound": input_tokens,
                                  "output_bound": output_tokens}
        return key

    def settle(self, key, input_tokens, output_tokens, cached_tokens=0):
        with self._locked() as data:
            record = data["calls"][key]
            if record["status"] != "reserved":
                raise ValueError("request already settled")
            actual = token_cost(record["model"], input_tokens, output_tokens, cached_tokens)
            data["spent_usd"] += actual - record["cost_usd"]
            record.update(cost_usd=actual, status="completed", input_tokens=input_tokens,
                          output_tokens=output_tokens, cached_tokens=cached_tokens)
        return actual

    def uncertain(self, key):
        with self._locked() as data:
            data["calls"][key]["status"] = "uncertain"

    def summary(self):
        with self._locked() as data:
            return {"spent_usd": data["spent_usd"], "limit_usd": self.limit,
                    "calls": len(data["calls"]),
                    "uncertain_calls": sum(r["status"] != "completed" for r in data["calls"].values())}
