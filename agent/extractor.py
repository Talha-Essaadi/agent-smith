import re
import html
import json
import keyword
from pydantic import BaseModel, model_validator
from typing import Optional, List, Dict, Any, Tuple

# Block-type detection patterns
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

# Generic (untagged) code block
_GENERIC_BLOCK_RE = re.compile(r"```\s*\n(.*?)```", re.DOTALL)
# Python code block
_PYTHON_BLOCK_RE = re.compile(
    r"```(?:python3?|py)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE
)
# Unclosed python code block
_UNCLOSED_PYTHON_RE = re.compile(
    r"```(?:python3?|py)\s*\n(.*)$", re.DOTALL | re.IGNORECASE
)
# JSON tool call block
_JSON_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{(?:(?!</tool_call>).)*?\})\s*(?:</tool_call>|\Z)",
    re.DOTALL | re.IGNORECASE,
)
# XML invoke block
_XML_INVOKE_RE = re.compile(
    r'<(?:\w+:)?invoke\s+name\s*=\s*["\']([^"\']+)["\']\s*'
    r'(?:/>|>(.*?)(?:</(?:\w+:)?invoke\s*>|(?=<(?:\w+:)?invoke\b)|\Z))',
    re.DOTALL | re.IGNORECASE,
)
_XML_PARAM_RE = re.compile(
    r'<(?:\w+:)?parameter\s+name\s*=\s*["\']([^"\']+)["\']\s*>(.*?)'
    r'(?:</(?:\w+:)?parameter\s*>|(?=<(?:\w+:)?parameter\b)|\Z)',
    re.DOTALL | re.IGNORECASE,
)
# ReAct block
_REACT_RE = re.compile(
    r"^[ \t]*Action[ \t]*:[ \t]*([A-Za-z_][\w.]*)[ \t]*\n"
    r"[ \t]*Action[ \t]+Input[ \t]*:\s*",
    re.IGNORECASE | re.MULTILINE,
)
_REACT_OBSERVATION_RE = re.compile(
    r"^[ \t]*Observation[ \t]*:", re.MULTILINE | re.IGNORECASE
)

# Stop sequences that LLMs emit to signal end-of-generation.
_STOP_SEQUENCES: List[str] = [
    "<end_code>",
    "<|endoftext|>",
    "<|im_end|>",
]

# Message text
_RETRY_HINT = (
    " Please provide executable Python code inside a"
    " ```python\n...\n``` block."
)

_UNCLOSED_WARNING = (
    "[NOTICE: Your ```python code block was unclosed / malformed (the"
    " closing ``` was missing or truncated; this can happen when the model"
    " hits a stop sequence or a max-token limit mid-block). The code was"
    " interpreted and executed anyway. To avoid this warning always close"
    " code blocks with a standalone ``` on its own line.]"
)

_GENERIC_WARNING = (
    "[NOTICE: A generic ``` code block without the 'python' language tag"
    " was interpreted as Python code. Please use ```python ... ```"
    " explicitly.]"
)

_MSG_EMPTY = "No valid code block was found in your response (response was empty)"

_MSG_UNKNOWN = (
    "No recognisable code block was found in your response. It did not"
    " contain a ```python``` block, an <invoke> XML block, a <tool_call>"
    " JSON block, or a ReAct Action/Action Input section"
)

_MSG_PYTHON = (
    "A ```python``` fence was detected but no valid code could be"
    " extracted from it"
)

_MSG_XML_UNPARSED = (
    "An <invoke> XML block was detected but it could not be parsed. Make"
    " sure every tool call follows the format:\n"
    '  <invoke name="tool_name">\n'
    '    <parameter name="arg">value</parameter>\n'
    "  </invoke>\n"
    "Check for unclosed tags or missing quotes around attribute values"
)

_MSG_JSON_UNPARSED = (
    "A <tool_call> block was detected but no complete JSON object could be"
    " found inside it (the closing </tool_call> tag or a closing brace may"
    " be missing, e.g. truncated by a stop sequence). Make sure the full"
    " block is present:\n"
    "  <tool_call>\n"
    '  {"name": "tool_name", "arguments": {"arg": "value"}}\n'
    "  </tool_call>"
)

_MSG_REACT_UNPARSED = (
    "A ReAct-style Action block was detected but could not be parsed. Make"
    " sure both lines are present and contiguous:\n"
    "  Action: tool_name\n"
    '  Action Input: {"arg": "value"}\n'
    "The Action Input value must be a valid JSON object"
)


class ExtractionResult(BaseModel):
    """Result of extracting executable Python code from raw LLM output.

    Invariants (enforced on construction):
      * ``is_valid=True``  -> ``code`` is non-empty.
      * ``is_valid=False`` -> ``error`` is set.
    """
    code: str = ""
    is_valid: bool = False
    warning: Optional[str] = None
    error: Optional[str] = None

    @model_validator(mode="after")
    def _check_invariants(self) -> "ExtractionResult":
        if self.is_valid and not self.code:
            raise ValueError("a valid result must contain code")
        if not self.is_valid and not self.error:
            raise ValueError("an invalid result must contain an error")
        return self


def _strip_stop_sequences(text: str) -> str:
    """Truncate *text* at the first known LLM stop sequence.

    Stop sequences are special tokens / tag strings that a model emits to
    signal the end of its generation turn. Everything from the first
    occurrence of any of them onward is discarded, since text after the
    stop marker is not part of the intended response and would otherwise
    break the downstream regexes.
    """
    for seq in _STOP_SEQUENCES:
        idx = text.find(seq)
        if idx != -1:
            text = text[:idx]
    return text


class CodeExtractor:
    """Turns raw LLM output into executable Python code.

    Every ``_*_extractor`` method returns an ``ExtractionResult`` (never
    ``None``), so ``extract`` is pure dispatch.
    """

    def extract(self, llm_output: str) -> ExtractionResult:
        if not llm_output or not llm_output.strip():
            return self._fail(_MSG_EMPTY)

        cleaned = _strip_stop_sequences(llm_output)
        if not cleaned.strip():
            return self._fail(_MSG_EMPTY)

        extractors = {
            "python": self._py_block_extractor,
            "xml": self._xml_extractor,
            "json": self._json_extractor,
            "react": self._react_extractor,
            "unknown": self._generic_extractor,
        }
        return extractors[self._detect_block_type(cleaned)](cleaned)

    @staticmethod
    def _ok(code: str, warning: Optional[str] = None) -> ExtractionResult:
        return ExtractionResult(is_valid=True, code=code, warning=warning)

    @staticmethod
    def _fail(msg: str) -> ExtractionResult:
        return ExtractionResult(
            is_valid=False,
            error=f"[ERROR: {msg}.{_RETRY_HINT}]",
        )

    @staticmethod
    def _detect_block_type(llm_output: str) -> str:
        """Return the format whose marker appears earliest in the text."""
        best, best_pos = "unknown", None
        for output_type, pattern in PATTERNS.items():
            m = pattern.search(llm_output)
            if m and (best_pos is None or m.start() < best_pos):
                best, best_pos = output_type, m.start()
        return best

    def _py_block_extractor(self, llm_output: str) -> ExtractionResult:
        py_blocks = _PYTHON_BLOCK_RE.findall(llm_output)
        code = "\n\n".join(b.strip() for b in py_blocks if b.strip())
        if code:
            return self._ok(code)

        unclosed = _UNCLOSED_PYTHON_RE.search(llm_output)
        if unclosed:
            code = re.sub(r"`+$", "", unclosed.group(1).strip()).strip()
            if code:
                return self._ok(code, warning=_UNCLOSED_WARNING)

        return self._fail(_MSG_PYTHON)

    def _xml_extractor(self, llm_output: str) -> ExtractionResult:
        blocks = _XML_INVOKE_RE.findall(llm_output)
        if not blocks:
            return self._fail(_MSG_XML_UNPARSED)

        try:
            code = self._convert_xml(blocks)
        except ValueError as exc:
            return self._fail(
                f"Invalid tool call inside <invoke> XML block: {exc}."
                " Ensure the 'name' attribute in <invoke name=\"tool_name\">"
                " is a valid Python identifier and not a reserved keyword"
            )

        return self._ok(code) if code else self._fail(_MSG_XML_UNPARSED)

    def _json_extractor(self, llm_output: str) -> ExtractionResult:
        blocks = _JSON_TOOL_CALL_RE.findall(llm_output)
        if not blocks:
            return self._fail(_MSG_JSON_UNPARSED)

        try:
            code = self._convert_json(blocks)
        except (ValueError, KeyError, TypeError) as exc:
            # json.JSONDecodeError is a subclass of ValueError.
            return self._fail(
                f"Malformed JSON inside <tool_call>: {exc!r}. The JSON"
                " object must be well-formed and contain a \"name\" (string)"
                " key and an \"arguments\" (object) key, e.g.:\n"
                "  <tool_call>\n"
                '  {"name": "tool_name", "arguments": {"arg": "value"}}\n'
                "  </tool_call>"
            )

        return self._ok(code) if code else self._fail(_MSG_JSON_UNPARSED)

    def _react_extractor(self, llm_output: str) -> ExtractionResult:
        # Anything after the first "Observation:" is hallucinated tool output.
        text = _REACT_OBSERVATION_RE.split(llm_output, maxsplit=1)[0]

        blocks: List[Tuple[str, Any]] = []
        try:
            decoder = json.JSONDecoder()
            for m in _REACT_RE.finditer(text):
                value, _ = decoder.raw_decode(text, m.end())
                blocks.append((m.group(1), value))
            code = self._convert_react(blocks) if blocks else ""
        except (ValueError, TypeError) as exc:
            return self._fail(
                f"Invalid ReAct Action / Action Input: {exc}."
                " The Action Input value must be a valid JSON object, e.g."
                ' {"arg": "value"}'
            )

        return self._ok(code) if code else self._fail(_MSG_REACT_UNPARSED)

    def _generic_extractor(self, llm_output: str) -> ExtractionResult:
        gen_blocks = _GENERIC_BLOCK_RE.findall(llm_output)
        code = "\n\n".join(b.strip() for b in gen_blocks if b.strip())
        if code:
            return self._ok(code, warning=_GENERIC_WARNING)
        return self._fail(_MSG_UNKNOWN)

    # ------------------------------------------------------------------
    # Converters (raise ValueError / KeyError / TypeError on bad input)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_kwargs(kwargs: Any) -> Dict[str, Any]:
        """Coerce a parsed 'arguments' value into a dict of kwargs."""
        if isinstance(kwargs, str):
            kwargs = json.loads(kwargs)
        if kwargs is None:
            return {}
        if not isinstance(kwargs, dict):
            raise ValueError("arguments must be a JSON object")
        return kwargs

    def _convert_xml(self, blocks: List[Any]) -> str:
        lines: List[str] = []
        for func_name, body in blocks:
            kwargs: Dict[str, Any] = {}
            for k, v in _XML_PARAM_RE.findall(body):
                val_str = v[1:] if v.startswith("\n") else v
                val_str = val_str[:-1] if val_str.endswith("\n") else val_str
                val_str = html.unescape(val_str)
                kwargs[k] = val_str
                try:
                    parsed = json.loads(val_str.strip())
                    if parsed is not None and not isinstance(parsed, str):
                        kwargs[k] = parsed
                except ValueError:
                    pass
            lines.append(self._to_py(func_name, kwargs))
        return "\n".join(lines)

    def _convert_json(self, blocks: List[str]) -> str:
        lines: List[str] = []
        for block in blocks:
            data = json.loads(block)
            func_name = data["name"]
            raw_kwargs = data.get("arguments", data.get("parameters"))
            lines.append(
                self._to_py(func_name, self._normalize_kwargs(raw_kwargs))
            )
        return "\n".join(lines)

    def _convert_react(self, blocks: List[Tuple[str, Any]]) -> str:
        return "\n".join(
            self._to_py(func_name, self._normalize_kwargs(kwargs))
            for func_name, kwargs in blocks
        )

    @staticmethod
    def _to_py(func_name: str, kwargs: Dict[str, Any]) -> str:
        """Convert a tool name and dict of arguments into a Python call."""
        if (not isinstance(func_name, str)
                or not re.fullmatch(r"[A-Za-z_]\w*", func_name)
                or keyword.iskeyword(func_name)):
            raise ValueError(f"{func_name!r} is not a valid tool name")

        good = {k: v for k, v in kwargs.items()
                if (isinstance(k, str) and k.isidentifier()
                    and not keyword.iskeyword(k))}
        bad = {k: v for k, v in kwargs.items() if k not in good}

        args = ", ".join(f"{k}={v!r}" for k, v in good.items())
        if bad:
            args += (", " if args else "") + f"**{bad!r}"

        if func_name == "final_answer" and len(kwargs) == 1:
            return f"{func_name}({list(kwargs.values())[0]!r})"
        return f"result = {func_name}({args})\nprint(result)"