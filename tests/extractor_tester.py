import sys
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from agent.extractor import CodeExtractor, ExtractionResult


@pytest.fixture
def extractor() -> CodeExtractor:
    return CodeExtractor()


# =====================================================================
# 1. PYTHON CODE BLOCKS & STOP SEQUENCES
# =====================================================================

def test_standard_python_and_py_blocks(extractor: CodeExtractor):
    """Extracts standard ```python and ```py blocks and concatenates multiple blocks."""
    raw = (
        "Thought: Define helper first, then call it.\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n"
        "Now call it:\n"
        "```py\n"
        "print(add(2, 3))\n"
        "```"
    )
    res = extractor.extract(raw)
    assert res.is_valid is True
    assert res.warning is None
    assert res.error is None
    assert "def add(a, b):" in res.code
    assert "print(add(2, 3))" in res.code


def test_python3_tag_and_case_insensitivity(extractor: CodeExtractor):
    """PATTERNS['python'] allows ```python3 and ```Python; extractor must extract both."""
    raw_py3 = "Thought: test\n```python3\nx = 10\nprint(x)\n```"
    res = extractor.extract(raw_py3)
    assert res.is_valid is True, f"Failed on ```python3 with error: {res.error}"
    assert res.code == "x = 10\nprint(x)"


def test_trailing_stop_sequences_stripped(extractor: CodeExtractor):
    """Trailing <end_code> or <|im_end|> should be cleanly stripped before extraction."""
    raw = "```python\nprint('hello')\n```\n<end_code>   "
    res = extractor.extract(raw)
    assert res.is_valid is True
    assert res.code == "print('hello')"
    assert "<end_code>" not in res.code


def test_stop_sequence_inside_string_literal_preserved(extractor: CodeExtractor):
    """A stop sequence inside the code itself (not trailing) must not corrupt the code."""
    raw = "```python\nx = '<end_code>'\nprint(x)\n```\n<end_code>"
    res = extractor.extract(raw)
    assert res.is_valid is True
    assert "x = '<end_code>'" in res.code


# =====================================================================
# 2. MALFORMED & MISSING CODE FEEDBACK (SPEC PAGE 12 RED BOX)
# =====================================================================

def test_unclosed_python_block_executes_with_warning(extractor: CodeExtractor):
    """Unclosed ```python block must set is_valid=True, extract code, and populate warning."""
    raw = (
        "Thought: Reading file lines.\n"
        "```python\n"
        "content = read_file('/testbed/app.py', 1, 50)\n"
        "print(content)``"
    )
    res = extractor.extract(raw)
    assert res.is_valid is True
    assert "read_file('/testbed/app.py', 1, 50)" in res.code
    assert not res.code.endswith("`")
    assert res.warning is not None
    assert "unclosed" in res.warning.lower() or "malformed" in res.warning.lower()


def test_empty_input_and_whitespace_only(extractor: CodeExtractor):
    """Empty or whitespace-only LLM response returns is_valid=False and explicit error."""
    for empty_input in ["", "   \n\t  "]:
        res = extractor.extract(empty_input)
        assert res.is_valid is False
        assert res.code == ""
        assert res.error is not None
        assert "ERROR" in res.error


def test_empty_python_fence_returns_error(extractor: CodeExtractor):
    """An empty ```python\n\n``` block should not be considered valid executable code."""
    raw = "Thought: Wait...\n```python\n   \n```"
    res = extractor.extract(raw)
    assert res.is_valid is False
    assert res.code == ""
    assert res.error is not None


def test_thought_only_no_code_block(extractor: CodeExtractor):
    """Response with only reasoning text and no code returns explicit feedback error."""
    raw = "Thought: I should check the tests first before editing any files."
    res = extractor.extract(raw)
    assert res.is_valid is False
    assert res.code == ""
    assert res.error is not None
    assert "No recognisable code block" in res.error


# =====================================================================
# 3. XML (<invoke>) TOOL CALLS & EDGE CASES
# =====================================================================

def test_xml_single_and_multiple_invokes_with_type_coercion(extractor: CodeExtractor):
    """Extracts <invoke> calls, converts integer/boolean params via json.loads, and executes."""
    raw = (
        "Thought: Let's read two files.\n"
        '<invoke name="read_file">\n'
        '<parameter name="filepath">/testbed/main.py</parameter>\n'
        '<parameter name="start_line">1</parameter>\n'
        '<parameter name="end_line">30</parameter>\n'
        "</invoke>\n"
        '<invoke name="list_files">\n'
        '<parameter name="directory">/testbed</parameter>\n'
        '<parameter name="pattern">*.py</parameter>\n'
        "</invoke>"
    )
    res = extractor.extract(raw)
    assert res.is_valid is True, f"XML extraction failed: {res.error}"

    calls = []
    ns = {
        "read_file": lambda **kw: calls.append(("read_file", kw)) or "file_content",
        "list_files": lambda **kw: calls.append(("list_files", kw)) or "file_list",
    }
    exec(res.code, ns)
    assert len(calls) == 2
    assert calls[0] == ("read_file", {"filepath": "/testbed/main.py", "start_line": 1, "end_line": 30})
    assert calls[1] == ("list_files", {"directory": "/testbed", "pattern": "*.py"})


def test_xml_malformed_unclosed_invoke_returns_error(extractor: CodeExtractor):
    """An <invoke> tag missing its closing </invoke> tag returns a descriptive XML error."""
    raw = (
        '<invoke name="read_file">\n'
        '<parameter name="filepath">/testbed/main.py</parameter>\n'
    )
    res = extractor.extract(raw)
    assert res.is_valid is False
    assert res.error is not None
    assert "<invoke>" in res.error


# =====================================================================
# 4. JSON (<tool_call>) TOOL CALLS & EDGE CASES
# =====================================================================

def test_json_tool_call_standard_and_multiple(extractor: CodeExtractor):
    """Valid <tool_call> blocks (even ending with </tool_call>) must extract and run cleanly."""
    raw = (
        "Thought: Search for the function definition.\n"
        "<tool_call>\n"
        '{"name": "search_code", "arguments": {"pattern": "def solve", "file_pattern": "*.py"}}\n'
        "</tool_call>"
    )
    res = extractor.extract(raw)
    assert res.is_valid is True, f"JSON extraction failed: {res.error}"

    captured = {}
    exec(res.code, {"search_code": lambda **kw: captured.update(kw) or "match"})
    assert captured == {"pattern": "def solve", "file_pattern": "*.py"}


def test_json_multiple_distinct_tool_calls(extractor: CodeExtractor):
    """Ensures each block in multiple <tool_call> tags is parsed individually (not just blocks[0])."""
    raw = (
        '<tool_call>{"name": "read_file", "arguments": {"filepath": "a.py", "start_line": 1, "end_line": 5}}</tool_call>\n'
        '<tool_call>{"name": "read_file", "arguments": {"filepath": "b.py", "start_line": 10, "end_line": 20}}</tool_call>'
    )
    res = extractor.extract(raw)
    assert res.is_valid is True, f"Multiple JSON tool calls failed: {res.error}"
    assert "filepath='a.py'" in res.code
    assert "filepath='b.py'" in res.code


def test_json_malformed_syntax_or_missing_keys_handled_gracefully(extractor: CodeExtractor):
    """Broken JSON or missing 'arguments' key inside <tool_call> must not raise unhandled exception."""
    broken_syntax = '<tool_call>{"name": "run_tests", "arguments": {bad_json}}</tool_call>'
    res1 = extractor.extract(broken_syntax)
    assert res1.is_valid is False
    assert res1.error is not None
    assert "Malformed JSON" in res1.error

    missing_key = '<tool_call>{"name": "run_tests"}</tool_call>'
    res2 = extractor.extract(missing_key)
    assert res2.is_valid is False
    assert res2.error is not None


def test_json_unclosed_tool_call_tag(extractor: CodeExtractor):
    """<tool_call>{"name": ...} without closing </tool_call> returns clear error (or extracts gracefully)."""
    raw = '<tool_call>\n{"name": "run_tests", "arguments": {}}'
    res = extractor.extract(raw)
    assert res.is_valid is False
    assert res.error is not None


# =====================================================================
# 5. REACT (Action / Action Input) & FINAL_ANSWER EDGE CASES
# =====================================================================

def test_react_valid_extraction(extractor: CodeExtractor):
    """Extracts ReAct Action + Action Input and converts to Python call with print(result)."""
    raw = (
        "Thought: Let's run a command in /testbed.\n"
        "Action: run_command\n"
        'Action Input: {"command": "git status", "workdir": "/testbed"}'
    )
    res = extractor.extract(raw)
    assert res.is_valid is True, f"ReAct extraction failed: {res.error}"
    assert "result = run_command(" in res.code
    assert "print(result)" in res.code


def test_react_malformed_json_input_handled_gracefully(extractor: CodeExtractor):
    """Invalid JSON after Action Input: returns is_valid=False with descriptive error instead of crashing."""
    raw = (
        "Thought: Run tests.\n"
        "Action: run_tests\n"
        "Action Input: {invalid_json: true}"
    )
    res = extractor.extract(raw)
    assert res.is_valid is False
    assert res.error is not None
    assert "Malformed JSON in ReAct" in res.error


def test_final_answer_does_not_wrap_in_print(extractor: CodeExtractor):
    """final_answer() should be called directly without 'result = ... print(result)'."""
    raw = (
        '<invoke name="final_answer">\n'
        '<parameter name="answer">def solve(x): return x * 2</parameter>\n'
        "</invoke>"
    )
    res = extractor.extract(raw)
    assert res.is_valid is True, f"final_answer XML failed: {res.error}"
    assert res.code.startswith("final_answer(")
    assert "print(" not in res.code
