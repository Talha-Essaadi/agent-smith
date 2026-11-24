import time
from typing import List, Dict, Any, Optional

import httpx
from pydantic import BaseModel

from .key_manager import KeyManager


class LLMResponse(BaseModel):
    content: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    retries: int
    api_url: str
    model_name: str


class LLMClient:
    def __init__(
        self,
        model_name: str,
        provider_url: str | None = None,
        env_file: str | None = None,
        max_retries: int = 5,
        timeout_seconds: float = 60.0
    ) -> None:

        self.key_manager = KeyManager(
            env_file=env_file,
            provider_url=provider_url
        )
        self.api_key = self.key_manager.get_key()
        self.api_url = provider_url.rstrip("/")

        self.model_name = model_name
        self.max_retries = max_retries
        self.timeout = timeout_seconds

    def _set_request_args(
        self,
        max_tokens: int,
        messages: List[Dict[str, str]],
        stop_sequences: Optional[List[str]] = None
    ) -> Dict[str, Any]:

        url = (
            self.api_url
            if self.api_url.endswith("/chat/completions")
            else f"{self.api_url}/chat/completions"
        )
        header = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        stop_seqs = ["<end_code>", "\nObservation:", "Observation:"] + (
            stop_sequences if stop_sequences is not None else []
        )

        body = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "stop": stop_seqs
        }

        return {
            "url": url,
            "headers": header,
            "json": body,
            "timeout": self.timeout
        }

    def _parse_response_to_llmresponse(
        self,
        messages: List[Dict[str, str]],
        response: Dict[str, Any],
        retries: int,
        request_time: float
    ) -> LLMResponse:

        message = response["choices"][0].get("message", {})
        raw_content = message.get("content") or ""
        reasoning = (
            message.get("reasoning_content")
            or message.get("reasoning")
            or ""
        )

        if message.get("reasoning_content") or message.get("reasoning"):
            reasoning = (message.get("reasoning_content")
                         if message.get("reasoning_content")
                         else message.get("reasoning"))

        content = raw_content if raw_content.strip() else reasoning

        usage = response.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        if input_tokens == 0:
            input_tokens = sum(len(m.get("content", ""))
                               for m in messages) // 4
        if output_tokens == 0:
            combined_len = len(raw_content) + len(reasoning)
            output_tokens = max(1, combined_len // 4)

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_time,
            retries=retries,
            api_url=self.api_url,
            model_name=self.model_name,
        )

    def generate(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        stop_sequences: Optional[List[str]] = None
    ) -> LLMResponse:

        last_error = "Unknown error"
        args = self._set_request_args(max_tokens, messages, stop_sequences)
        for attempt in range(self.max_retries + 1):
            args["headers"]["Authorization"] = f"Bearer {self.api_key}"
            backoff = min(2 ** attempt, 8)

            try:
                st = time.perf_counter()
                r = httpx.post(**args)
                et = time.perf_counter()
            except (httpx.TimeoutException, httpx.RequestError) as e:
                last_error = str(e)
                time.sleep(backoff)
                continue

            response_code = r.status_code
            response_time = (et - st) * 1000.0

            if response_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    last_error = (
                        f"Invalid JSON in 200 response:"
                        f" {r.text[:200]}"
                    )
                    time.sleep(backoff)
                    continue

                if "error" in data and isinstance(data["error"], dict):
                    err_code = data["error"].get("code")
                    if isinstance(err_code, int):
                        response_code = err_code
                    else:
                        last_error = (
                            f"API error payload: "
                            f"{str(data['error'])[:200]}"
                        )
                        time.sleep(backoff)
                        continue
                else:
                    choices = data.get("choices")
                    if not choices:
                        last_error = (
                            f"Empty choices in 200 response: "
                            f"{r.text[:200]}"
                        )
                        time.sleep(backoff)
                        continue
                    parsed = self._parse_response_to_llmresponse(
                        messages, data, attempt, response_time
                    )

                    if not parsed.content.strip():
                        finish_reason = choices[0].get("finish_reason")
                        last_error = (
                            f"Empty LLM response; "
                            f"finish_reason={finish_reason!r}"
                        )
                        time.sleep(backoff)
                        continue

                    return parsed

            if response_code == 429:
                self.api_key = self.key_manager.get_key(response_code)
                last_error = f"HTTP {response_code}: {r.text[:200]}"
                time.sleep(backoff)
                continue

            if response_code in (401, 402, 403):
                self.api_key = self.key_manager.get_key(response_code)
                last_error = f"HTTP {response_code}: {r.text[:200]}"
                continue

            if response_code == 400:
                if "stop" in args["json"]:
                    args["json"].pop("stop")
                    last_error = f"HTTP {response_code}: {r.text[:200]}"
                    continue
                raise RuntimeError(f"LLM API Error {response_code}: {r.text}")

            if response_code in (500, 502, 503, 504):
                last_error = f"HTTP {response_code}: {r.text[:200]}"
                time.sleep(backoff)
                continue

            last_error = f"HTTP {response_code}: {r.text[:200]}"
            time.sleep(backoff)

        raise RuntimeError(
            f"LLM API failed after {self.max_retries + 1}"
            f" attempts: {last_error}")
