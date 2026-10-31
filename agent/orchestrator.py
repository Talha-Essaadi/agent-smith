from typing import List, Dict, Optional
import time

from agent.config import AgentLimits
from agent.llm.client import LLMClient
from schemas import BaseSandbox, SolutionOutput, StepMetrics
from agent.extractor import CodeExtractor


class AgentOrchestrator:
    def __init__(self,
                 llm_client: LLMClient,
                 sandbox: BaseSandbox,
                 limits: AgentLimits) -> None:
        self.sandbox = sandbox
        self.llm_client = llm_client
        self.limits = limits
        self.extractor = CodeExtractor()

    def _estimate_input_tokens(self, messages: List[Dict[str, str]]) -> int:
        return sum(len(m.get("content", "")) for m in messages) // 3

    def _truncate_observation(self, text: str) -> str:
        if len(text) > self.limits.max_observation_chars:
            return (text[:self.limits.max_observation_chars] +
                    "\n\nThe observation was truncated due to size limits. "
                    "Use small slices.")
        return text

    def run(self, task_id: str, benchmark: str,
            system_prompt: str, user_prompt: str) -> SolutionOutput:

        st = time.perf_counter()
        steps: List[StepMetrics] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_requests = 0
        success = False
        solution = ""
        last_valid_code = ""
        error_msg: Optional[str] = None
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        for step_num in range(1, self.limits.max_iterations + 1):
            elapsed = time.perf_counter() - st
            if elapsed >= self.limits.timeout_seconds - 2.0:
                error_msg = "Timeout limit reached"
                break
            est_in = self._estimate_input_tokens(messages)
            if total_input_tokens + est_in > self.limits.max_input_tokens:
                error_msg = "Input token budget reached"
                break
            rem_out = self.limits.max_output_tokens - total_output_tokens
            if rem_out <= 20:
                error_msg = "Output token budget reached"
                break
            try:
                step_cap = 500 if benchmark.lower() == "mbpp" else 1500
                llm_resp = self.llm_client.generate(messages,
                                                    max_tokens=min(step_cap,
                                                                   rem_out))
            except Exception as e:
                error_msg = str(e)
                break

            total_input_tokens += llm_resp.input_tokens
            total_output_tokens += llm_resp.output_tokens
            total_requests += 1 + llm_resp.retries
            messages.append({"role": "assistant", "content": llm_resp.content})

            ext = self.extractor.extract(llm_resp.content)
            if not ext.is_valid:
                sandbox_input = ""
                sandbox_output = (ext.error
                                  or "[ERROR: No valid code block found.]")
                is_final = False
            else:
                sandbox_input = ext.code
                last_valid_code = ext.code
                exec_res = self.sandbox.execute(sandbox_input)
                obs = exec_res.to_observation_string()
                if ext.warning:
                    obs = f"{ext.warning}\n\n{obs}"
                obs = self._truncate_observation(obs)
                sandbox_output = obs
                is_final = exec_res.is_final_answer

            step = StepMetrics(
                step=step_num,
                input_tokens=llm_resp.input_tokens,
                output_tokens=llm_resp.output_tokens,
                request_time_ms=llm_resp.request_time_ms,
                api_url=llm_resp.api_url,
                model_name=llm_resp.model_name,
                llm_output=llm_resp.content,
                sandbox_input=sandbox_input,
                sandbox_output=sandbox_output,
                retries=llm_resp.retries
            )
            steps.append(step)

            if is_final:
                success = True
                solution = exec_res.final_answer_value or ""
                error_msg = None
                break
            else:
                messages.append(
                    {"role": "user",
                     "content": f"Observation:\n{sandbox_output}"})

        if not success and not solution:
            if benchmark == "mbpp" and last_valid_code:
                solution = last_valid_code
            if benchmark == "swebench":
                patch_res = self.sandbox.execute("print(get_patch())")
                if patch_res.stdout.strip():
                    solution = patch_res.stdout.strip()

        solution = SolutionOutput(
            task_id=task_id,
            benchmark=benchmark,
            success=success,
            solution=solution,
            system_prompt=system_prompt,
            iterations=len(steps),
            total_requests=total_requests,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_time_seconds=time.perf_counter() - st,
            steps=steps,
            error=error_msg
        )
        return solution
