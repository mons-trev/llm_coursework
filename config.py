"""Settings for the two explicitly supported, priced model families."""
import os
from dataclasses import dataclass

from budget import model_family


@dataclass(frozen=True)
class Settings:
    planner_model: str = "gpt-4o-mini"
    verifier_model: str = "gpt-4o-mini"
    max_rounds: int = 3
    max_agent_calls: int = 6
    max_turn_calls: int = 24
    max_output_tokens: int = 6000
    budget_usd: float = 15.0
    ledger_path: str = ".usage/ledger.json"
    reasoning_effort: str = "low"

    @classmethod
    def from_env(cls):
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return cls(planner_model=os.getenv("PLANNER_MODEL", model),
                   verifier_model=os.getenv("VERIFIER_MODEL", model),
                   budget_usd=float(os.getenv("API_BUDGET_USD", "15")),
                   ledger_path=os.getenv("API_LEDGER_PATH", ".usage/ledger.json"))

    def __post_init__(self):
        families = {model_family(self.planner_model), model_family(self.verifier_model)}
        if min(self.max_rounds, self.max_agent_calls, self.max_turn_calls,
               self.max_output_tokens) < 1:
            raise ValueError("round, call and token limits must be positive")
        if "gpt-4o-mini" in families and self.max_output_tokens > 16384:
            raise ValueError("gpt-4o-mini output limit is 16384 tokens")
        if self.max_output_tokens > 128000:
            raise ValueError("gpt-5-mini output limit is 128000 tokens")
        if self.reasoning_effort not in {"minimal", "low", "medium", "high"}:
            raise ValueError("invalid GPT-5 mini reasoning effort")
