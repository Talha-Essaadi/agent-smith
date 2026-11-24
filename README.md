*This project has been created as part of the 42 curriculum by alaktaou, tessaadi.*

# Agent Smith

Autonomous reasoning, code generation, and sandboxed execution framework built to solve algorithmic programming challenges (MBPP) and real-world software engineering issues (SWE-bench).

---

## Description

**Agent Smith** is a code-based autonomous agent framework designed around a **Thought → Code → Observation** reasoning loop. Rather than relying solely on static text completion or rigid JSON tool-calling schemas, the agent writes executable Python code to inspect codebases, run search queries, modify files, execute tests, and iterate on solutions until a task is resolved.

### Key Goals & Features
* **Custom Agentic Orchestration:** Implements an autonomous **Thought → Code → Observation** loop from scratch without external agent orchestration frameworks (`langchain`, `smolagents`, `autogen`, etc.).
* **Multi-Format Code Extraction:** Normalizes diverse LLM output formats—including standard Python code blocks, XML `<invoke>` tags, Hermes `<tool_call>` JSON blocks, and ReAct `Action` / `Action Input` syntax—into executable Python code.
* **Docker-Isolated Execution Sandbox:** Runs LLM-generated Python code inside a hardened, persistent Docker container with non-root privileges, network isolation (`network_mode="none"`), capability dropping, read-only root filesystem, memory/process limits, import allowlisting, and restricted builtins/paths.
* **Model Context Protocol (MCP) Integration:** Connects dynamically to MCP servers over `stdio` or Streamable HTTP to discover tools, resources, and prompts, automatically generating a live tool manual for the LLM system prompt.
* **Multi-Key API Management & Telemetry:** Supports OpenAI-compatible endpoints across multiple providers with automatic API key rotation on rate limits (`HTTP 429`), exponential backoff retries, and granular per-step token/latency tracking (`StepMetrics` and `SolutionOutput`).

---

## System Architecture

Agent Smith separates LLM reasoning, code execution isolation, and target-environment interaction across distinct security domains:

```text
+-------------------------------------------------------------------+
|                        Host Orchestrator                          |
|  +---------------+      +------------------+      +------------+  |
|  |  LLM Client   | ---> |  Code Extractor  | ---> |  Sandbox   |  |
|  | (Key Manager) | <--- | (Format Norm.)   | <--- |  Manager   |  |
|  +---------------+      +------------------+      +-----+------+  |
+---------------------------------------------------------|---------+
                                                          | JSON IPC
                                                          v
+-------------------------------------------------------------------+
|                Hardened Python Sandbox Container                  |
|  - Non-root (1000:1000), network_mode="none", read-only rootfs    |
|  - Restricted __import__, open(), builtins, RLIMIT_AS (512 MB)    |
|  - Persistent namespace + final_answer() + MCP tool wrappers      |
+---------------------------------------------------------+---------+
                                                          | Tool Call
                                                          v
+-------------------------------------------------------------------+
|                   Host MCP Server (stdio / HTTP)                  |
+-------------------------------+-----------------------------------+
                                |
        +-----------------------+-----------------------+
        | (MBPP)                                        | (SWE-bench)
        v                                               v
+-----------------------+               +---------------------------+
| Host Test Subprocess  |               | SWE-bench Task Container  |
| (run_tests w/ timeout)|               | (/testbed repository)     |
+-----------------------+               +---------------------------+
```

### Repository Structure

```text
agent-smith/
├── agent_mbpp.py                # MBPP agent CLI entry point
├── agent_swebench.py            # SWE-bench agent CLI entry point
├── mcp_tools_mbpp.py            # MBPP MCP server
├── mcp_tools_swebench.py        # SWE-bench MCP server
├── agent/
│   ├── config.py               # Model settings and benchmark budgets
│   ├── orchestrator.py         # Thought → Code → Observation loop
│   ├── extractor.py            # Model-output parsing & normalization
│   ├── llm/
│   │   ├── client.py           # API requests, retries, response parsing
│   │   └── key_manager.py      # API-key loading and rotation
│   └── prompts/                # System prompt templates and builder
├── sandbox/
│   ├── cli.py                  # Interactive sandbox REPL CLI
│   ├── sandbox.py              # Sandbox interface and dynamic tool manual
│   ├── runner.py               # Docker execution and JSON IPC
│   ├── swebench_docker.py      # SWE-bench container lifecycle management
│   ├── mcp_client.py           # MCP transport/session handling
│   ├── mcp_manager.py          # MCP connections and capability discovery
│   ├── tool_registry.py        # Discovered-tool Python wrapper registration
│   ├── Dockerfile              # Hardened Python sandbox image
│   └── container/              # In-container runner, restrictions, IPC
├── swebench_tools/             # Filesystem, search, execution backends
├── schemas/                    # Pydantic task, output, and sandbox schemas
├── sandbox_template.json       # Example sandbox configuration
├── pyproject.toml              # Project dependencies (Python 3.10+, uv)
├── Makefile                    # Build and utility targets
└── BENCHMARK_REPORT.md         # Detailed cross-model evaluation report
```

---

## Agent Loop Explanation

The core decision-making loop (`agent/orchestrator.py`) executes iteratively until `final_answer()` is called or a hard budget (iterations, tokens, or wall-clock timeout) is reached:

1. **Prompt Construction:** Combines the task instructions with a dynamically generated sandbox manual listing all connected MCP tools, parameter types, defaults, and active sandbox constraints.
2. **LLM Generation & Key Rotation:** Sends the conversation history to the configured OpenAI-compatible provider (`agent/llm/client.py`). Stop sequences (`<end_code>`, `Observation:`) are passed to prevent the model from hallucinating execution outputs. If an `HTTP 429` rate limit occurs, `KeyManager` rotates to the next available API key; `HTTP 401/402/403` errors prune invalid keys from the pool, and transient errors retry with capped exponential backoff (up to 6 attempts).
3. **Code Extraction & Normalization:** `agent/extractor.py` parses the raw LLM response. It supports ` ```python ` / ` ```py ` / ` ```python3 ` blocks, untagged/unclosed code fences (with explicit warnings), XML `<invoke>` calls, Hermes `<tool_call>` JSON payloads, and ReAct `Action` / `Action Input` blocks. Non-Python tool formats are translated into valid Python function calls.
4. **Sandboxed Execution & Explicit Feedback:** Extracted code runs in the persistent sandbox container. If the model omits a code block, triggers a syntax/lint error, hits a timeout, or receives truncated output, explicit diagnostic feedback is injected into the next observation so the model can self-correct without guessing.
5. **Termination & Provenance Logging:** Calling `final_answer(result)` captures the solution string (function code for MBPP or unified `git diff` for SWE-bench) and writes a validated `SolutionOutput` JSON containing `system_prompt` and per-step `StepMetrics` (`llm_output`, `sandbox_input`, `sandbox_output`, token counts, latency, and retries).

---

## Sandbox Design

The sandbox (`sandbox/`) enforces strict isolation between LLM-generated control code and the host machine using a dedicated, hardened Docker container paired with Python-level runtime restrictions:

* **Container Hardening (`sandbox/Dockerfile`, `sandbox/runner.py`):**
  * Runs as unprivileged user `1000:1000` with `no-new-privileges` and all Linux capabilities dropped (`cap_drop=["ALL"]`).
  * Network access is completely disabled at the container level (`network_mode="none"`).
  * Uses a read-only root filesystem with bounded, writable `tmpfs` mounts and container-level memory/PID limits.
* **Python Runtime & Builtin Restrictions (`sandbox/container/`):**
  * **Import Allowlist:** Replaces `__import__` with an allowlist validator controlled by `SandboxConfig.authorized_imports` (supporting wildcard submodule rules such as `math.*` and `collections.*`) and blocks relative imports.
  * **Filesystem Restrictions:** Wraps `open()` to resolve canonical paths and permit access exclusively within `SandboxConfig.allowed_directories` (defaulting to `/testbed` and `/tmp/agent`), while blocking raw file-descriptor access.
  * **Restricted Builtins:** Removes or overrides high-risk builtins (`eval`, `exec`, `compile`, `input`, `globals`, `locals`, `vars`) and blocks selected introspection attributes.
  * **Memory & Execution Timeouts:** Enforces `max_memory_mb` (default `512 MB`) via both Docker memory limits and `resource.RLIMIT_AS`. Step execution time (`max_execution_time_seconds`, default `30s` in agent schemas, `5s` in `sandbox_template.json`) is enforced by the host runner, which terminates and destroys runaway containers on timeout while excluding external MCP tool wait times from the Python step budget.
* **Lifecycle & Signal Cleanup:** For SWE-bench tasks (`sandbox/swebench_docker.py`), the agent manages two separate containers (the hardened Python sandbox and the task-specific SWE-bench container). A `SIGTERM` handler cancels active tasks and ensures `finally` blocks close MCP sessions and force-remove both containers.

---

## Tool Implementation Details

Agent Smith uses the **Model Context Protocol (MCP)** (`sandbox/mcp_client.py`, `sandbox/mcp_manager.py`, `sandbox/tool_registry.py`) to decouple environment actions from the sandboxed Python interpreter. Both bundled servers run over `stdio` by default and also support Streamable HTTP (`--mcp-server <URL>`).

### SWE-bench Mandatory Tools (`mcp_tools_swebench.py` & `swebench_tools/`)
All SWE-bench tools target the repository path specified by the `TESTBED_PATH` environment variable (or active SWE-bench container `/testbed`):

* **File System Tools:**
  * `read_file(filepath, start_line, end_line)`: Reads file slices formatted with 1-indexed line numbers (`<line_number>: <line_content>`).
  * `edit_file(filepath, old_str, new_str)`: Performs exact string replacement in target files with validation feedback.
  * `list_files(directory, pattern)`: Lists repository files matching glob patterns.
* **Code Search Tools:**
  * `search_code(pattern, file_pattern)`: Executes codebase regex/grep searches returning `/path/to/file.py: <line> <content>`.
  * `search_function_or_class_definition_in_code(name)`: Locates function and class definitions across the codebase.
  * `find_references(name, filepath, line)`: Finds symbol usages across files.
* **Execution Tools:**
  * `run_tests()`: Runs the task's evaluation test script inside the container.
  * `get_patch()`: Generates a clean unified diff via `git -c core.fileMode=false diff`.
  * `run_command(command, workdir)`: Executes shell commands in the target working directory and returns `stdout`, `stderr`, and exit code.

### MBPP Tools (`mcp_tools_mbpp.py`)
* `run_tests(code, test_list)`: Executes candidate Python functions against benchmark assertion suites in a timeout-bounded subprocess (`10s`) and returns structured JSON pass/fail diagnostics.

### Built-in Sandbox Constructs
* `final_answer(answer)`: Injected directly into the sandbox namespace (not an MCP tool) to signal task completion and terminate the agent loop.
* **MCP Resources & Prompts:** Automatically discovered at session initialization and exposed in the dynamic tool manual.

---

## Instructions

### Prerequisites
* **Python 3.10**
* **[uv](https://github.com/astral-sh/uv)** package manager
* **Docker** daemon running (required for the isolated Python sandbox and SWE-bench task containers)

### Installation

1. Clone the repository and install dependencies using `uv`:
   ```bash
   git clone <repository-url> agent-smith
   cd agent-smith
   uv sync
   ```

2. Build the hardened sandbox Docker image:
   ```bash
   docker build -t agent-smith-sandbox -f sandbox/Dockerfile .
   ```
   *(Or use the provided `Makefile` targets if configured in your environment.)*

3. Configure environment variables in `.env` (never hardcode API keys in source files):
   ```env
   MODEL_NAME="particle-ai/particle-1:free"
   PROVIDER_URL="https://openrouter.ai/api/v1"
   OPENROUTER_API_KEY="your_key_1,your_key_2"
   ```

### Execution

#### 1. Interactive Sandbox REPL
Launch the standalone interactive sandbox with custom JSON limits or attached MCP servers:
```bash
# Default interactive sandbox
uv run sandbox

# With custom sandbox configuration
uv run sandbox sandbox_template.json

# Connected to MBPP MCP tools (stdio)
uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py" sandbox_template.json

# Connected to SWE-bench MCP tools (stdio) or HTTP MCP server
uv run sandbox --mcp-stdio "python mcp_tools_swebench.py" sandbox_template.json
uv run sandbox --mcp-server http://localhost:8000/mcp
```

#### 2. Running the MBPP Agent
```bash
uv run python -m agent_mbpp \
  --task-file /path/to/mbpp_task.json \
  --output /path/to/mbpp_solution.json \
  --model-name "particle-ai/particle-1:free" \
  --provider-url "https://openrouter.ai/api/v1"
```

#### 3. Running the SWE-bench Agent
```bash
uv run python -m agent_swebench \
  --task-file /path/to/swebench_task.json \
  --output /path/to/swebench_solution.json \
  --model-name "particle-ai/particle-1:free" \
  --provider-url "https://openrouter.ai/api/v1"
```

### 4. Setup
Create a `.env` file for the provider used by the run. For example:

```dotenv
MODEL_NAME=particle-ai/particle-1:free
PROVIDER_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY_1=replace_with_your_first_key
OPENROUTER_API_KEY_2=replace_with_your_second_key
```
---

## Benchmark Results and Analysis

We evaluated **8 models across 4 hosted providers and 1 local endpoint** over 24 SWE-bench runs using the moulinette evaluation harness (limits: 30 iterations, 300,000 cumulative input tokens, 10,000 cumulative output tokens, 900s timeout). Full per-task traces and methodology are documented in [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md).

### Summary Performance Table

*(Token and iteration figures represent averages per task across 3 assigned SWE-bench instances per model.)*

| Rank | Model | Provider | Passed | Mean Iterations | Mean Input Tokens | Mean Output Tokens | Mean Wall Time (s) |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | `qwen/qwen3.8-27b` | Groq | 3/3 | 3.33 | 10,563.3 | 244.0 | 69.41 |
| 2 | `particle-ai/particle-1:free` | OpenRouter | **3/3** | 5.67 | 27,309.0 | 541.7 | **63.53** |
| 3 | `gemini-3.5-flash-lite` | Google Gemini | 2/3 | 4.33 | 30,781.7 | 454.3 | 84.64 |
| 4 | `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter | 1/3 | 16.67 | 75,832.3 | 3,828.0 | 133.29 |
| 5 | `lfm3:latest` | Local Endpoint | 1/3 | 22.33 | 173,282.3 | 9,624.7 | 124.69 |
| 6 | `openai/gpt-oss-120b` | Groq | 0/3 | 5.00 | 15,586.0 | 2,574.7 | 77.94 |
| 6 | `command-a-plus-05-2026` | Cohere | 0/3 | 2.33 | 15,328.3 | 3,333.3 | 45.20 |
| 6 | `recursive/flint-v1.0:free` | OpenRouter | 0/3 | 13.33 | 48,613.0 | 569.7 | 38.96 |

### Key Findings & Ablation Analysis
* **Primary Model Selection (`Particle` on OpenRouter):** Although `Qwen` achieved the lowest average token count, all three of its runs hit Groq `HTTP 429` TPM limits and required fallback patch recovery. `Particle` passed **3/3 tasks** with clean `final_answer()` submissions, low latency (`1.36s` mean response), and strong exploration efficiency (reading the target file by step 1–2 and editing by step 2–3). On shared task `pydata__xarray-4629`, `Particle` solved the issue in `21,902` input tokens (`52.36s`) vs. `88,854` for Gemini (`97.52s`) and `172,827` for LFM3 (`144.63s`).
* **Secondary / Fallback Configuration (`Gemini 3.5 Flash Lite`):** Passed 2/3 tasks with compact token usage; its sole failure was a transient pre-loop `HTTP 503` error, making it an effective independent-quota backup.
* **Failure Modes in Lower-Ranked Models:** `LFM3` suffered frequent code-extraction errors (27/67 steps) and exhausted output budgets; `Nemotron` exhibited poor submission discipline and returned malformed patch strings; `Command A+` and `Flint` hit endpoint/quota errors (`HTTP 422` / daily free-tier limits).
* **Prompt Ablation Study (`GPT-OSS` on `sympy__sympy-14711`):** Removing verbose output-format examples from `read_file`, `search_code`, and `run_tests` tool descriptions reduced input tokens by **44.6%** (`21,791 → 12,069`), iterations (`7 → 4`), and wall time (`105.37s → 69.46s`), though external provider quota/payload limits (`HTTP 429` / `HTTP 413`) prevented task completion in both runs.

---

## Resources

### Technical References
* **ReAct & Code-Act Paradigms:**
  * Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (ICLR 2023) — [arxiv.org/abs/2210.03629](https://arxiv.org/abs/2210.03629)
  * Wang et al., *Executable Code Actions Elicit Better LLM Agents (CodeAct)* (ICML 2024) — [arxiv.org/abs/2402.01030](https://arxiv.org/abs/2402.01030)
* **Model Context Protocol (MCP):**
  * Anthropic / Linux Foundation MCP Specification & Python SDK — [modelcontextprotocol.io](https://modelcontextprotocol.io/)
* **Benchmarks:**
  * Jimenez et al., *SWE-bench: Can Language Models Resolve Real-World GitHub Issues?* — [swebench.com](https://www.swebench.com/)
  * Austin et al., *Program Synthesis with Large Language Models (MBPP)* — [arxiv.org/abs/2108.07732](https://arxiv.org/abs/2108.07732)
* **Python Security & Container Isolation:**
  * Python `resource` and `builtins` documentation — [docs.python.org/3.10](https://docs.python.org/3.10/)
  * Docker Engine Security & Runtime Privilege Constraints — [docs.docker.com/engine/security](https://docs.docker.com/engine/security/)

### AI Usage Disclosure
In accordance with 42 curriculum guidelines, AI tools were used responsibly as a collaborative engineering assistant during this project:
* **Specification & Trace Inspection:** Used to cross-check implementation details against project requirements and inspect recorded `SolutionOutput` execution traces.
* **Benchmark Data Analysis & Documentation:** Used to aggregate step-level metrics from recorded benchmark runs, verify statistical calculations, and draft/revise `BENCHMARK_REPORT.md` and `README.md`.
* All architectural decisions, security mechanisms, benchmark executions, and final code reviews were performed and verified directly by the team (`alaktaou`, `tessaadi`).