"""Revision baselines are actual returned plans; approval remains a separate fact."""
import copy
from dataclasses import dataclass, field


@dataclass
class Session:
    user_turns: list[str] = field(default_factory=list)
    accepted_plan: dict | None = None
    accepted_at_turn: int | None = None
    planner_history: list = field(default_factory=list)
    results: list = field(default_factory=list)
    last_returned_plan: dict | None = None
    returned_at_turn: int | None = None
    mode: str | None = None

    def __post_init__(self):
        # Legacy session files could only have been produced by planner_verifier.
        if self.mode is None and (self.user_turns or self.accepted_plan or self.results):
            self.mode = "planner_verifier"
        if self.last_returned_plan is None and self.accepted_plan is not None:
            self.last_returned_plan = copy.deepcopy(self.accepted_plan)
            self.returned_at_turn = self.accepted_at_turn

    def ensure_mode(self, mode):
        if self.mode is not None and self.mode != mode:
            raise ValueError(f"session mode {self.mode} cannot be used with {mode}; start a new session")
        self.mode = mode

    @property
    def has_current_plan(self):
        return self.returned_at_turn == len(self.user_turns) and self.last_returned_plan is not None
