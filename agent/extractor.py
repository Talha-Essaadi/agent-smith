import re
import json
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

#  For know the block type
PATTERNS = {
    "python": re.compile(
        r"```[ \t]*(?:python3?|py)[ \t]*\r?\n",
        re.IGNORECASE,
    ),
    "xml": re.compile(
        r"<(?:\w+:)?invoke\s+name\s*=",
        re.IGNORECASE,
    ),
    "json": re.compile(
        r"<tool_call>\s*\{",
        re.IGNORECASE,
    ),
    "react": re.compile(
        r"^[ \t]*Action[ \t]*:[ \t]*[A-Za-z_][\w.]*[ \t]*\r?\n"
        r"[ \t]*Action[ \t]+Input[ \t]*:",
        re.IGNORECASE | re.MULTILINE,
    ),
}

#  For the general code block
_GENERIC_BLOCK_RE = re.compile(r"```\s*\n(.*?)```", re.DOTALL)
#  For the python code block
_PYTHON_BLOCK_RE = re.compile(
    r"```(?:python3?|py)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE
)
#  For unclosed python code block
_UNCLOSED_PYTHON_RE = re.compile(
    r"```(?:python3?|py)\s*\n(.*)$", re.DOTALL | re.IGNORECASE
)
#  For the JSON block
_JSON_TOOL_CALL_RE = re.compile(
        r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL
)
#  For the XML block
_XML_INVOKE_RE = re.compile(
    r'<(?:\w+:)?invoke\s+name=["\']([^"\']+)["\']?\s*>(.*?)</(?:\w+:)?invoke>',
    re.DOTALL
)
_XML_PARAM_RE = re.compile(
    r'<parameter\s+name=["\'"]([^"\'"]+)["\'"]?\s*>(.*?)</parameter>',
    re.DOTALL
)
# For the ReAct block
_REACT_RE = re.compile(
    r"Action\s*:\s*([a-zA-Z_][a-zA-Z0-9_]*)"
    r"\s*\nAction\s+Input\s*:\s*(\{.*\})",
    re.DOTALL,
)

# Stop sequences that LLMs emit to signal end-of-generation.
_STOP_SEQUENCES: List[str] = [
    "<end_code>",
    "<|endoftext|>",
    "<|im_end|>",
]


class ExtractionResult(BaseModel):
    """Result of extracting executable Python code from raw LLM output."""
    code: str = ""
    is_valid: bool = False
    warning: Optional[str] = None
    error: Optional[str] = None


def _strip_stop_sequences(text: str) -> str:
    """Remove known LLM stop-sequences from *text*.

    Stop sequences are special tokens / tag strings that a model emits to
    signal the end of its generation turn (see Anthropic docs §Stop sequences,
    p. 27).  If they appear inside or immediately after a code / tool-call
    block they will break every downstream regex, so we strip them first.

    Only *trailing* occurrences are removed; a stop sequence that appears in
    the middle of a response (e.g. inside a string literal) is left alone.
    """
    stripped = text
    for seq in _STOP_SEQUENCES:
        tail = stripped.rstrip()
        if tail.endswith(seq):
            stripped = tail[: -len(seq)]

    return stripped


class CodeExtractor:
    def __init__(self) -> None:
        pass

    def extract(self, llm_output: str) -> ExtractionResult:
        if not llm_output or not llm_output.strip():
            return ExtractionResult(
                is_valid=False,
                error=(
                    "[ERROR: No valid code block was found in your response"
                    " (response was empty)."
                    " Please provide executable Python code inside a"
                    " ```python ... ``` block.]"
                ),
            )

        cleaned = _strip_stop_sequences(llm_output)
        block_type = self._detect_block_type(cleaned)

        if block_type == "python":
            result = self._code_block_extractor(cleaned)
        elif block_type == "xml":
            result = self._xml_extractor(cleaned)
        elif block_type == "json":
            result = self._json_extractor(cleaned)
        elif block_type == "react":
            result = self._react_extractor(cleaned)
        else:
            result = None

        if result is not None:
            return result

        if block_type == "unknown":
            result = self._generic_extractor(cleaned)
            if result:
                return result
            return ExtractionResult(
                is_valid=False,
                error=(
                    "[ERROR: No recognisable code block was found in your"
                    " response. The response did not contain a ```python```"
                    " block, an <invoke> XML block, a <tool_call> JSON block,"
                    " or a ReAct Action/Action Input section."
                    " Please provide executable Python code inside a"
                    " ```python\n...\n``` block.]"
                ),
            )

        # A recognised format marker was present but extraction still failed.
        _format_hints: Dict[str, str] = {
            "python": (
                "a ```python``` fence was detected but no valid code could be"
                " extracted from it"
            ),
            "xml": (
                "an <invoke> XML block was detected but it could not be"
                " parsed — check that every <invoke name=\"...\"> tag is"
                " properly closed with </invoke> and that parameter values"
                " are wrapped in <parameter name=\"...\">...</parameter>"
            ),
            "json": (
                "a <tool_call> JSON block was detected but it could not be"
                " parsed — check that the JSON object inside <tool_call>…"
                "</tool_call> is well-formed and contains \"name\" and"
                " \"arguments\" keys"
            ),
            "react": (
                "a ReAct Action/Action Input section was detected but the"
                " Action Input value could not be parsed as JSON — make sure"
                " the value on the Action Input line is a valid JSON object"
                " e.g. {\"arg\": \"value\"}"
            ),
        }
        hint = _format_hints.get(
            block_type,
            "the detected block was malformed"
        )
        return ExtractionResult(
            is_valid=False,
            error=(
                f"[ERROR: Could not extract executable code from your"
                f" response: {hint}."
                f" Please provide executable Python code inside a"
                f" ```python\n...\n``` block.]"
            ),
        )

    def _detect_block_type(self, llm_output: str) -> str:
        for output_type, pattern in PATTERNS.items():
            if pattern.search(llm_output):
                return output_type
        return "unknown"

    def _code_block_extractor(self,
                              llm_output: str) -> Optional[ExtractionResult]:
        py_blocks = _PYTHON_BLOCK_RE.findall(llm_output)
        if py_blocks:
            code = "\n\n".join(m.strip() for m in py_blocks if m.strip())
            if code:
                return ExtractionResult(
                    is_valid=True,
                    code=code,
                )

        unclosed_blocks = _UNCLOSED_PYTHON_RE.search(llm_output)
        if unclosed_blocks:
            code = unclosed_blocks.group(1).strip()
            code = re.sub(r"`+$", "", code).strip()
            if code:
                return ExtractionResult(
                    is_valid=True,
                    code=code,
                    warning=(
                        "[NOTICE: Your ```python code block was unclosed /"
                        " malformed (the closing ``` was missing or truncated"
                        " — this can happen when the model hits a stop"
                        " sequence or a max-token limit mid-block)."
                        " The code was interpreted and executed anyway."
                        " To avoid this warning always close code blocks"
                        " with a standalone ``` on its own line.]"
                    ),
                )
        return None

    def _xml_extractor(self, llm_output: str) -> Optional[ExtractionResult]:
        xml_blocks = _XML_INVOKE_RE.findall(llm_output)
        if xml_blocks:
            code = self._convert_xml(xml_blocks)
            if code:
                return ExtractionResult(
                    is_valid=True,
                    code=code,
                )

        return ExtractionResult(
            is_valid=False,
            error=(
                "[ERROR: An <invoke> XML block was detected in your response"
                " but it could not be parsed."
                " Make sure every tool call follows the format:\n"
                "  <invoke name=\"tool_name\">\n"
                "    <parameter name=\"arg\">value</parameter>\n"
                "  </invoke>\n"
                "Check for unclosed tags or missing quotes around attribute"
                " values.]"
            ),
        )

    def _json_extractor(self, llm_output: str) -> Optional[ExtractionResult]:
        json_blocks = _JSON_TOOL_CALL_RE.findall(llm_output)
        if json_blocks:
            try:
                code = self._convert_json(json_blocks)
            except (json.JSONDecodeError, KeyError) as exc:
                return ExtractionResult(
                    is_valid=False,
                    error=(
                        f"[ERROR: Malformed JSON inside <tool_call>: {exc}."
                        " The JSON object must be well-formed and contain"
                        " both a \"name\" (string) key and an \"arguments\""
                        " (object) key, e.g.:\n"
                        "  <tool_call>\n"
                        "  {\"name\": \"tool_name\","
                        " \"arguments\": {\"arg\": \"value\"}}\n"
                        "  </tool_call>]"
                    ),
                )
            if code:
                return ExtractionResult(
                    is_valid=True,
                    code=code,
                )

        return ExtractionResult(
            is_valid=False,
            error=(
                "[ERROR: A <tool_call> block was detected but could not be"
                " extracted — the closing </tool_call> tag may be missing"
                " (e.g. truncated by a stop sequence)."
                " Make sure the full block is present:\n"
                "  <tool_call>\n"
                "  {\"name\": \"tool_name\","
                " \"arguments\": {\"arg\": \"value\"}}\n"
                "  </tool_call>]"
            ),
        )

    def _react_extractor(self, llm_output: str) -> Optional[ExtractionResult]:
        react_blocks = _REACT_RE.findall(llm_output)
        if react_blocks:
            try:
                code = self._convert_react(react_blocks)
            except json.JSONDecodeError as exc:
                return ExtractionResult(
                    is_valid=False,
                    error=(
                        f"[ERROR: Malformed JSON in ReAct Action Input: {exc}."
                        " The value after 'Action Input:' must be a valid JSON"
                        " object, e.g.:\n"
                        "  Action: tool_name\n"
                        "  Action Input: {\"arg\": \"value\"}]"
                    ),
                )
            if code:
                return ExtractionResult(
                    is_valid=True,
                    code=code,
                )

        return ExtractionResult(
            is_valid=False,
            error=(
                "[ERROR: A ReAct-style Action block was detected but could"
                " not be parsed. Make sure both lines are present and"
                " contiguous:\n"
                "  Action: tool_name\n"
                "  Action Input: {\"arg\": \"value\"}\n"
                "The Action Input value must be a valid JSON object on the"
                " same line (or with no blank lines between the two).]"
            ),
        )

    def _generic_extractor(self,
                           llm_output: str) -> Optional[ExtractionResult]:
        gen_blocks = _GENERIC_BLOCK_RE.findall(llm_output)
        if gen_blocks:
            code = "\n\n".join(m.strip() for m in gen_blocks if m.strip())
            if code:
                return ExtractionResult(
                    is_valid=True,
                    code=code,
                    warning="[NOTICE: A generic ``` code block without "
                            "the 'python' language tag was interpreted"
                            " as Python code. Please use ```python ... ```"
                            " explicitly.]"
                )

        return None

    def _convert_xml(self, blocks: List[Any]) -> str:
        lines: List[str] = []
        for func_name, body in blocks:
            params = _XML_PARAM_RE.findall(body)
            kwargs: Dict[str, Any] = {}
            for k, v in params:
                val_str = v.strip()
                try:
                    kwargs[k] = json.loads(val_str)
                except Exception:
                    kwargs[k] = val_str
            lines.append(self._to_py(func_name, kwargs))
        return "\n".join(lines)

    def _convert_json(self, blocks: List[Any]) -> str:
        lines: List[str] = []
        for block in blocks:
            json_block = json.loads(block)
            func_name = json_block["name"]
            kwargs: Dict[str, Any] = json_block["arguments"]
            if kwargs is None:
                kwargs = {}
            lines.append(self._to_py(func_name, kwargs))
        return "\n".join(lines)

    def _convert_react(self, blocks: List[Any]) -> str:
        lines: List[str] = []
        for func_name, body in blocks:
            kwargs: Dict[str, Any] = json.loads(body)
            if kwargs is None:
                kwargs = {}
            lines.append(self._to_py(func_name, kwargs))
        return "\n".join(lines)

    def _to_py(self, func_name: str, kwargs: Dict[str, Any]) -> str:
        """Converts a tool name and dictionary of
         arguments into a valid Python call string."""
        args = ", ".join([f"{k}={repr(v)}" for k, v in kwargs.items()])
        func_call = f"{func_name}({args})"
        if func_name == "final_answer" and len(kwargs) == 1:
            return f"{func_name}({repr(list(kwargs.values())[0])})"
        return f"result = {func_call}\nprint(result)"
