"""Only successful, currently verified plans become the revision baseline."""
from dataclasses import dataclass, field


@dataclass
class Session:
    user_turns: list[str] = field(default_factory=list)
    accepted_plan: dict | None = None
    accepted_at_turn: int | None = None
    planner_history: list = field(default_factory=list)
    results: list = field(default_factory=list)

    @property
    def has_current_plan(self):
        return self.accepted_at_turn == len(self.user_turns) and self.accepted_plan is not None
