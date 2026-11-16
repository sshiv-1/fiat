from dataclasses import dataclass
import json
from fiat.provider_errors import RequestBudgetExceededError

@dataclass(frozen=True)
class ContextTier:
    name: str
    token_budget: int
    max_files: int
    max_snippets: int
    include_dependencies: bool

DEGRADATION_TIERS: tuple[ContextTier, ...] = (
    ContextTier("tier_0_default", token_budget=3000, max_files=8, max_snippets=10, include_dependencies=True),
    ContextTier("tier_1_compact", token_budget=1500, max_files=5, max_snippets=6, include_dependencies=False),
    ContextTier("tier_2_minimal", token_budget=600, max_files=3, max_snippets=3, include_dependencies=False),
    ContextTier("tier_3_zero_repo", token_budget=0, max_files=0, max_snippets=0, include_dependencies=False),
)

class RequestBudgetEstimator:
    def __init__(self, model_context_window: int = 128000, provider_request_cap: int = 12000, output_reserve: int = 2048, safety_margin: int = 512):
        self.model_context_window = model_context_window
        self.provider_request_cap = provider_request_cap
        self.output_reserve = output_reserve
        self.safety_margin = safety_margin

    @property
    def effective_input_cap(self) -> int:
        return min(self.model_context_window, self.provider_request_cap)

    def estimate_tokens(self, value: object) -> int:
        if value is None or value == "" or value == [] or value == {}:
            return 0
        if isinstance(value, str):
            text = value
        elif hasattr(value, "model_dump_json"):
            text = value.model_dump_json()
        else:
            try:
                text = json.dumps(value, default=str)
            except Exception:
                text = str(value)
        return len(text) // 4 + 1

    def estimate_request_breakdown(self, system_prompt: str = "", user_prompt: str = "", revision_payload: object = None, serialized_plan: object = None, tool_schemas: object = None, repo_context: object = None) -> dict[str, int]:
        t_sys = self.estimate_tokens(system_prompt)
        t_user = self.estimate_tokens(user_prompt)
        t_rev = self.estimate_tokens(revision_payload)
        t_plan = self.estimate_tokens(serialized_plan)
        t_tools = self.estimate_tokens(tool_schemas)
        t_repo = self.estimate_tokens(repo_context)

        fixed_overhead = t_sys + t_user + t_rev + t_plan + t_tools
        available_for_repo = self.effective_input_cap - fixed_overhead - self.output_reserve - self.safety_margin
        total_estimated = fixed_overhead + t_repo + self.output_reserve

        return {
            "system_prompt": t_sys,
            "user_prompt": t_user,
            "revision_payload": t_rev,
            "serialized_plan": t_plan,
            "tool_schemas": t_tools,
            "repo_context": t_repo,
            "fixed_overhead": fixed_overhead,
            "output_reserve": self.output_reserve,
            "safety_margin": self.safety_margin,
            "effective_input_cap": self.effective_input_cap,
            "available_for_repo": available_for_repo,
            "total_estimated": total_estimated,
        }

    def select_initial_tier(self, breakdown: dict[str, int]) -> ContextTier:
        avail = breakdown["available_for_repo"]
        if avail < 0:
            raise RequestBudgetExceededError(
                "Request fixed overhead exceeds available request budget",
                estimated_tokens=breakdown["fixed_overhead"] + breakdown["output_reserve"],
                budget_limit=breakdown["effective_input_cap"],
                breakdown=breakdown
            )
        for tier in DEGRADATION_TIERS:
            if tier.token_budget <= avail:
                if tier.name == "tier_0_default" and avail < 3000:
                    return ContextTier("tier_0_clamped", token_budget=avail, max_files=8, max_snippets=10, include_dependencies=True)
                return tier
        return DEGRADATION_TIERS[-1]
