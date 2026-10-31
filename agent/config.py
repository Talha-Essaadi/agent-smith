from pydantic import BaseModel


class AgentLimits(BaseModel):
    max_iterations: int
    max_input_tokens: int
    max_output_tokens: int
    timeout_seconds: float
    max_observation_chars: int


MBPP_LIMITS = AgentLimits(
    max_iterations=10,
    max_input_tokens=6000,
    max_output_tokens=1500,
    timeout_seconds=120.0,
    max_observation_chars=1500,
)


SWE_LIMITS = AgentLimits(
    max_iterations=30,
    max_input_tokens=300000,
    max_output_tokens=10000,
    timeout_seconds=900.0,
    max_observation_chars=8000,
)


class AgentConfig(BaseModel):
    def get_limits(self, benchmark: str,
                   max_iterations_override: int | None = None) -> AgentLimits:
        if benchmark.strip().lower() == "mbpp":
            if max_iterations_override is not None:
                MBPP_LIMITS.model_copy(
                    update={"max_iterations": max_iterations_override})
            return MBPP_LIMITS
        elif benchmark.strip().lower() == "swebench":
            if max_iterations_override is not None:
                SWE_LIMITS.model_copy(
                    update={"max_iterations": max_iterations_override})
            return SWE_LIMITS
        else:
            raise ValueError(
                f"Unknown eval_type: {benchmark}, use 'MBPP' or 'SWEBENCH'"
            )
