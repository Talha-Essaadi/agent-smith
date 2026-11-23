import asyncio
from typing import List, Dict, Optional
import time
import sys

from agent.config import AgentLimits
from agent.llm.client import LLMClient
from schemas import BaseSandbox, SolutionOutput, StepMetrics
from agent.extractor import CodeExtractor


DIM = "\033[2m"
RESET = "\033[0m"


def _agent_process(
    task_id: str,
    step_num: int,
    max_iterations: int,
    total_input_tokens: int,
    max_input_tokens: int,
    total_output_tokens: int,
    max_output_tokens: int,
    st: float,
    timeout_seconds: float,
    total_requests: int,
    total_retries: int,
    request_time_ms: float,
    state: str,
) -> None:
    status = (
        f"Task {task_id} · step {step_num}/{max_iterations} · "
        f"state={state} · in={total_input_tokens}/{max_input_tokens} · "
        f"out={total_output_tokens}/{max_output_tokens} · "
        f"time={time.perf_counter() - st:.1f}/{timeout_seconds:g}s · "
        f"requests={total_requests} · retries={total_retries}"
    )
    l = len(status) + 2
    print(
        f"\r\033[2K{RESET}{DIM} {status} {RESET}{CYAN}",
        end="\r", file=sys.stderr, flush=True,
    )


class AgentOrchestrator:
    def __init__(
        self,
        llm_client: LLMClient,
        sandbox: BaseSandbox,
        limits: AgentLimits
    ) -> None:
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

    async def run(
        self,
        task_id: str,
        benchmark: str,
        system_prompt: str,
        user_prompt: str
    ) -> SolutionOutput:

        st = time.perf_counter()
        steps: List[StepMetrics] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_requests = 0
        total_retries = 0
        request_time_ms = 0.0
        step_num = 0
        pending = None
        success = False
        code_solution = ""
        last_valid_code = ""
        error_msg: Optional[str] = None
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
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
                    pending = asyncio.ensure_future(asyncio.to_thread(
                        self.llm_client.generate,
                        messages,
                        min(step_cap, rem_out),
                    ))
                    while True:
                        _agent_process(
                            task_id,
                            step_num,
                            self.limits.max_iterations,
                            total_input_tokens,
                            self.limits.max_input_tokens,
                            total_output_tokens,
                            self.limits.max_output_tokens,
                            st,
                            self.limits.timeout_seconds,
                            total_requests,
                            total_retries,
                            request_time_ms,
                            state="processing",
                        )
                        done, _ = await asyncio.wait({pending}, timeout=1.0)
                        if done:
                            break
                    llm_resp = pending.result()
                    pending = None
                except Exception as e:
                    error_msg = str(e)
                    break

                total_input_tokens += llm_resp.input_tokens
                total_output_tokens += llm_resp.output_tokens
                total_requests += 1 + llm_resp.retries
                total_retries += llm_resp.retries
                request_time_ms = llm_resp.request_time_ms
                messages.append({"role": "assistant", "content": llm_resp.content})

                ext = self.extractor.extract(llm_resp.content)
                exec_res = None
                if not ext.is_valid:
                    sandbox_input = ""
                    sandbox_output = ""
                    feedback = (
                        ext.error or "[ERROR: No valid code block found.]"
                    )
                    is_final = False
                else:
                    sandbox_input = ext.code
                    last_valid_code = ext.code
                    _agent_process(
                        task_id,
                        step_num,
                        self.limits.max_iterations,
                        total_input_tokens,
                        self.limits.max_input_tokens,
                        total_output_tokens,
                        self.limits.max_output_tokens,
                        st,
                        self.limits.timeout_seconds,
                        total_requests,
                        total_retries,
                        request_time_ms,
                        state="processing",
                    )
                    exec_res = await self.sandbox.execute(sandbox_input)
                    obs = exec_res.to_observation_string()
                    if ext.warning:
                        obs = f"{ext.warning}\n\n{obs}"
                    obs = self._truncate_observation(obs)
                    sandbox_output = obs
                    feedback = obs
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
                    extraction_error=ext.error,
                    retries=llm_resp.retries
                )
                steps.append(step)

                if is_final and exec_res is not None:
                    success = True
                    code_solution = exec_res.final_answer_value or ""
                    error_msg = None
                    break

                messages.append({
                    "role": "user",
                    "content": f"Observation:\n{feedback}"
                })
        except asyncio.CancelledError:
            error_msg = "Agent terminated by signal"
        finally:
            if pending is not None and not pending.done():
                pending.cancel()

        if not success and not code_solution:
            if benchmark == "mbpp" and last_valid_code:
                code_solution = last_valid_code
            if benchmark == "swebench":
                try:
                    patch_res = await self.sandbox.execute("print(get_patch())")
                    if patch_res.stdout.strip():
                        code_solution = patch_res.stdout.strip()
                except Exception:
                    pass

        state = "success" if success else "failed"
        _agent_process(
            task_id,
            step_num,
            self.limits.max_iterations,
            total_input_tokens,
            self.limits.max_input_tokens,
            total_output_tokens,
            self.limits.max_output_tokens,
            st,
            self.limits.timeout_seconds,
            total_requests,
            total_retries,
            request_time_ms,
            state=state,
        )
        print(file=sys.stderr, flush=True)
        if error_msg:
            print(f"Task {task_id}: {error_msg}", file=sys.stderr, flush=True)

        return SolutionOutput(
            task_id=task_id,
            benchmark=benchmark,
            success=success,
            solution=code_solution,
            system_prompt=system_prompt,
            iterations=len(steps),
            total_requests=total_requests,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_time_seconds=time.perf_counter() - st,
            steps=steps,
            error=error_msg,
        )
