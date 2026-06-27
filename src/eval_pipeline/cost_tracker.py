from __future__ import annotations

from eval_pipeline.models import CostSummary, JudgeProvider


class CostTracker:
    def __init__(
        self,
        openai_input_cost_per_m: float = 0.15,
        openai_output_cost_per_m: float = 0.60,
        groq_input_cost_per_m: float = 0.0,
        groq_output_cost_per_m: float = 0.0,
    ) -> None:
        self.openai_input_cost_per_m = openai_input_cost_per_m
        self.openai_output_cost_per_m = openai_output_cost_per_m
        self.groq_input_cost_per_m = groq_input_cost_per_m
        self.groq_output_cost_per_m = groq_output_cost_per_m
        self._openai_in = 0
        self._openai_out = 0
        self._groq_in = 0
        self._groq_out = 0

    def add(self, provider: JudgeProvider, input_tokens: int, output_tokens: int) -> None:
        if provider == "openai":
            self._openai_in += input_tokens
            self._openai_out += output_tokens
        elif provider == "groq":
            self._groq_in += input_tokens
            self._groq_out += output_tokens

    def summary(self) -> CostSummary:
        openai_cost = (
            self._openai_in * self.openai_input_cost_per_m / 1_000_000
            + self._openai_out * self.openai_output_cost_per_m / 1_000_000
        )
        groq_cost = (
            self._groq_in * self.groq_input_cost_per_m / 1_000_000
            + self._groq_out * self.groq_output_cost_per_m / 1_000_000
        )
        return CostSummary(
            openai_input_tokens=self._openai_in,
            openai_output_tokens=self._openai_out,
            openai_cost_usd=round(openai_cost, 6),
            groq_input_tokens=self._groq_in,
            groq_output_tokens=self._groq_out,
            groq_cost_usd=round(groq_cost, 6),
            total_cost_usd=round(openai_cost + groq_cost, 6),
        )
