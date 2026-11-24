*This project has been created as part of the 42 curriculum by alaktaou, tessaadi.*

# Agent Smith

## Description

Agent Smith is a Python framework for autonomous coding agents. It combines a language model, executable Python actions, sandbox feedback, and tools exposed through the Model Context Protocol (MCP). The agent repeats a Thought → Code → Observation loop until it submits a solution or reaches a resource limit.

Two agents share the same orchestration framework:

- **MBPP:** generate a standalone Python function from a task description and test assertions.
- **SWE-bench:** explore a repository, modify its source, run tests, and return a unified Git patch.

The project records prompts, generated code, execution observations, token usage, request timings, and retries so that each run can be inspected. The team logins are `alaktaou` and `tessaadi`.

## Instructions

### Prerequisites

- Python 3.11 or newer for the host application, including its `BaseExceptionGroup` handling. The package metadata currently declares Python 3.10 or newer.
- `uv` for dependency installation and command execution.
- A running Docker daemon accessible to the current user. Both agents use the Python sandbox container; SWE-bench also uses a task-specific container.
- API credentials and an available model on the selected provider, or a local OpenAI-compatible endpoint.
- Network access for dependency installation, initial image builds/pulls, and hosted LLM calls. Generated-code containers have networking disabled.

### Installation

Run from the repository root:

```bash
uv sync
make build
```

`make build` builds `agent-sandbox:latest` from `sandbox/Dockerfile`. The runner also builds this image automatically if it is missing. There is no separate application compilation step.

### Model and API configuration

Create a `.env` file for the provider used by the run. For example:

```dotenv
MODEL_NAME=particle-ai/particle-1:free
PROVIDER_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY_1=replace_with_your_first_key
OPENROUTER_API_KEY_2=replace_with_your_second_key
```

The values above are placeholders for credentials. The `.env` file is ignored by Git. Use free quotas to follow the project's provider requirements; the application does not verify account billing settings.

Keys can be supplied through numbered variables or comma-separated values. The current key manager collects API-key variables into a shared pool, so supply only keys for the selected provider in a run's environment and configuration.

Tested configurations include:

| Provider | Model identifiers |
|---|---|
| OpenRouter | `particle-ai/particle-1:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `recursive/flint-v1.0:free` |
| Groq | `qwen/qwen3.8-27b`, `openai/gpt-oss-120b` |
| Google Gemini API | `gemini-3.5-flash-lite` |
| Cohere | `command-a-plus-05-2026` |
| Local compatible endpoint | `lfm3:latest` |

These are the identifiers in the recorded runs; availability and quotas depend on the endpoint. Model and provider selection can also be passed through `--model-name` and `--provider-url`, which override environment settings.

### Run the agents

Provide an input task matching the corresponding Pydantic schema in `schemas/task.py`.

```bash
uv run python -m agent_mbpp \
  --task-file /path/to/mbpp_task.json \
  --output /path/to/mbpp_solution.json \
  --env-file .env
```

```bash
uv run python -m agent_swebench \
  --task-file /path/to/swebench_task.json \
  --output /path/to/swebench_solution.json \
  --env-file .env
```

MBPP inputs contain the task ID, description, required function definition, optional imports, and assertions. SWE-bench inputs contain the instance ID, problem statement, Docker image, evaluation script, and optional hints/repository name.

Both commands start their bundled MCP server through stdio by default. `--mcp-stdio` selects a custom server command; `--mcp-server` connects to a Streamable HTTP server. Use one transport option at a time. An external SWE-bench server must be configured to access the appropriate task environment.

### Testing through the moulinette

When the moulinette is available, it provides task export, timed agent execution, and solution validation. Install its dependencies separately:

```bash
uv sync --project moulinette
```

The following example exports one SWE-bench task, launches the agent with a 900-second process timeout, and validates the result. Run it from the repository root:

```bash
mkdir -p /tmp/agent-smith-benchmark

uv run --project moulinette moulinette_eval dump swebench \
  --output /tmp/agent-smith-benchmark/task.json

uv run --project moulinette moulinette_eval run-agent 900 \
  "uv run python -m agent_swebench --task-file /tmp/agent-smith-benchmark/task.json --output /tmp/agent-smith-benchmark/solution.json --env-file .env"

uv run --project moulinette moulinette_eval validate swebench \
  /tmp/agent-smith-benchmark/task.json \
  /tmp/agent-smith-benchmark/solution.json
```

For MBPP, use `mbpp`, `agent_mbpp`, and a 120-second process timeout. Moulinette validation supplies the final correctness and resource-limit verdict; reaching the agent's submission function alone does not establish correctness.

### Interactive sandbox

```bash
uv run sandbox
uv run sandbox sandbox_template.json
uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py"
```

In interactive mode, `:tools` lists discovered capabilities and `exit` closes the session. Variables persist between successful execution steps.

The JSON configuration path is a positional argument of the interactive sandbox. The agent CLIs currently instantiate `SandboxConfig()` defaults rather than loading that JSON file. The template sets a five-second step timeout; the schema default used by the agents is 30 seconds.

## System Architecture

```text
┌─────────────┐   Prompt / Response   ┌──────────────────────────┐
│   LLM API   │ ◄───────────────────► │       Orchestrator       │
└─────────────┘                       └────────────┬─────────────┘
                                                   │ Raw LLM output
                                                   ▼
                                      ┌──────────────────────────┐
                                      │      Code Extractor      │
                                      └────────────┬─────────────┘
                                                   │ Normalized Python code
                                                   ▼
┌────────────────────────────────────────────────────────────────┐
│                  Isolated Python Sandbox (Docker)              │
│  • Persistent namespace & final_answer()                       │
│  • Allowlisted imports, builtins & filesystem paths            │
│  • Memory & step-timeout enforcement, network disabled         │
│  • Dynamically generated MCP tool wrappers                     │
└──────────────────────────────┬─────────────────────────────────┘
                               │ JSON IPC (Host Bridge)
                               ▼
                    ┌─────────────────────┐
                    │     MCP Client      │
                    └──────────┬──────────┘
                               │ stdio / Streamable HTTP
                               ▼
                    ┌─────────────────────┐
                    │     MCP Server      │
                    └──────────┬──────────┘
                               │ docker exec (SWE-bench)
                               ▼
                    ┌─────────────────────┐
                    │  SWE-bench Repo     │
                    │  Docker Container   │
                    └─────────────────────┘
```

The orchestration and LLM requests run on the host. Generated Python actions execute inside a dedicated Docker sandbox. Its tool wrappers send requests through the host MCP manager. SWE-bench tools then operate inside a separate task container through `docker exec`.

### Repository layout

```text
agent-smith/
├── agent_mbpp.py                # MBPP agent CLI entry point
├── agent_swebench.py            # SWE-bench agent CLI entry point
├── mcp_tools_mbpp.py            # MBPP MCP server
├── mcp_tools_swebench.py        # SWE-bench MCP server
├── agent/
│   ├── config.py                # Model settings and benchmark budgets
│   ├── orchestrator.py          # Thought → Code → Observation loop
│   ├── extractor.py             # Multi-format model-output parser
│   ├── llm/
│   │   ├── client.py            # OpenAI-compatible client, retries, stop sequences
│   │   └── key_manager.py       # Multi-key loading and rotation
│   └── prompts/                 # System prompt templates and builder
├── sandbox/
│   ├── cli.py                   # Interactive sandbox REPL CLI
│   ├── sandbox.py               # Sandbox interface and dynamic tool manual builder
│   ├── runner.py                # Docker execution and JSON IPC
│   ├── swebench_docker.py       # SWE-bench container lifecycle and cleanup
│   ├── mcp_client.py            # MCP transport/session handling
│   ├── mcp_manager.py           # Connections and capability discovery
│   ├── tool_registry.py         # Discovered-tool registration
│   ├── Dockerfile               # Python sandbox image
│   └── container/               # In-container execution, restrictions, IPC, wrappers
├── swebench_tools/              # Filesystem, search, and execution backends
├── schemas/                     # Pydantic task, output, and sandbox schemas
├── sandbox_template.json        # Example sandbox configuration
├── pyproject.toml               # Project dependencies (managed via uv)
├── Makefile                     # Build and utility targets
└── BENCHMARK_REPORT.md          # Multi-model SWE-bench evaluation report
```

## Agent Loop and LLM Handling

Each iteration performs the following actions:

1. Check elapsed time and remaining token budgets.
2. Request a model response using the task, system prompt, and previous observations.
3. Extract executable Python or convert a structured tool call into Python.
4. Execute the action and collect output, errors, and submission status.
5. Record step metrics and return the actual observation to the model.

`final_answer(value)` terminates the loop. For MBPP, the value is standalone solution code; for SWE-bench, it is a patch. If submission is not reached, the orchestrator attempts to recover the current SWE-bench patch or the last valid MBPP code.

The extractor supports Python fences, XML `<invoke>`, JSON `<tool_call>`, and ReAct `Action` / `Action Input`. Untagged and unclosed Python fences are accepted with warnings. The API requests stop sequences including `<end_code>` and `Observation:`; ReAct extraction also discards generated observations. These measures reduce fabricated tool continuations. After HTTP 400, the client retries without the API stop parameter.

The API client rotates keys on HTTP 429 and removes keys on HTTP 401/402/403. Transient failures use exponential backoff capped at eight seconds, with six attempts per generation call by default. Provider switching is configured explicitly; automatic cross-provider fallback is not implemented.

| Per-task budget | MBPP | SWE-bench |
|---|---:|---:|
| Iterations | 10 | 30 |
| Cumulative input tokens | 6,000 | 300,000 |
| Cumulative output tokens | 1,500 | 10,000 |
| Configured task time | 120 s | 900 s |

The orchestrator estimates upcoming input usage before sending a request; that estimate does not guarantee that actual returned token usage stays within the cap. Use the moulinette's process wrapper for a hard task timeout. Token counts use provider usage fields when available and character-based estimates otherwise.

Outputs record the full system prompt, final solution, aggregate metrics, errors, and per-step model responses, executed code, observations, timings, and retries. Terminal failed API calls do not produce normal step records, so their attempts are not included in successful-step retry totals.

## Sandbox Design

The Python sandbox runs as UID/GID `1000:1000`, with no network, dropped capabilities, `no-new-privileges`, a read-only root filesystem, and writable tmpfs mounts for allowed directories. Docker limits memory and process count. The default memory limit is 512 MB, supplemented by `resource.RLIMIT_AS` inside the execution process.

Python restrictions replace import handling with an allowlist, reject relative imports, restrict selected builtins, and wrap file access. File paths are resolved before checking containment under allowed directories, normally `/testbed` and `/tmp/agent`. Selected introspection attributes are restricted through wrapped attribute-access functions. The execution path does not implement AST security validation; Docker is the main isolation boundary.

The runner destroys the Python sandbox on an execution timeout. External MCP work is excluded from the Python step timer and has separate timeouts. For SWE-bench, shell commands normally have a 120-second tool timeout and the evaluation script a 300-second tool timeout. The task container also has networking disabled.

SIGTERM cancels the SWE-bench task, allowing the CLI's `finally` block to close MCP sessions and force-remove the sandbox and task containers. SIGKILL cannot run Python cleanup handlers.

The MBPP MCP test tool currently executes code in a host Python subprocess with a ten-second timeout. It does not inherit the Docker sandbox's import, filesystem, or memory restrictions. This tool must be treated as a separate execution boundary.

## MCP Tool Implementation

Tools are discovered from connected MCP servers and registered by name. Python wrappers are built from their input schemas, while the prompt manual includes parameter signatures, descriptions, configured limits, and discovered resources/prompts. Duplicate tool names from different servers are namespaced.

| Tool | Implementation |
|---|---|
| `read_file` | Read a line range with one-based line numbers. |
| `edit_file` | Replace an exact, uniquely matching string; report syntax warnings for edited Python. |
| `list_files` | Recursively list files matching a glob, excluding Git metadata. |
| `search_code` | Search matching files using a regular expression, with literal fallback for invalid regex patterns. |
| `search_function_or_class_definition_in_code` | Find Python definitions through AST parsing. |
| `find_references` | Find matching names, attributes, and imports through AST parsing; this is a syntactic search rather than full symbol resolution. |
| `run_tests` | Run the supplied SWE-bench evaluation script; MBPP exposes a separate version accepting code and assertions. |
| `get_patch` | Return the unified Git diff with file-mode changes ignored. |
| `run_command` | Execute a shell command in the selected task working directory and return output and exit status. |

Filesystem tools validate paths against the repository root. SWE-bench has a Docker backend and a local backend selected by environment configuration. The bundled server exposes the nine tools above; extra framework capabilities include `final_answer`, MCP resource access, and MCP prompt access.

## Benchmark Results and Analysis

Eight models were compared through the moulinette across 24 recorded SWE-bench runs. The table follows the benchmark report's order: validated solve rate, then cumulative input-token use among models with solves. Each model received three tasks, but task assignments differ.

| Model | Passed | Mean iterations | Mean input tokens | Mean output tokens |
|---|---:|---:|---:|---:|
| Qwen | 3/3 | 3.33 | 10,563.3 | 244.0 |
| Particle | 3/3 | 5.67 | 27,309.0 | 541.7 |
| Gemini | 2/3 | 4.33 | 30,781.7 | 454.3 |
| Nemotron | 1/3 | 16.67 | 75,832.3 | 3,828.0 |
| LFM3 | 1/3 | 22.33 | 173,282.3 | 9,624.7 |
| GPT-OSS | 0/3 | 5.00 | 15,586.0 | 2,574.7 |
| Command A+ | 0/3 | 2.33 | 15,328.3 | 3,333.3 |
| Flint | 0/3 | 13.33 | 48,613.0 | 569.7 |

Particle is the recommended primary SWE-bench configuration because all three runs completed normal submission and passed validation. Qwen used fewer tokens but relied on recovered patches after rate-limit failures in every run. Gemini is the recommended alternative provider configuration; its unsuccessful run ended with HTTP 503 before obtaining a usable response.

On shared xarray 4629, Particle passed in five iterations using 21,902 input tokens, compared with Gemini's 12 iterations and 88,854 tokens and LFM3's 20 iterations and 172,827 tokens.

An exploratory GPT-OSS before/after comparison shortened three tool descriptions. Input use fell from 21,791 to 12,069 tokens and wall time from 105.37 to 69.46 seconds, but neither run produced a patch. Different API failures and uncontrolled conditions prevent claiming an improvement in solving ability.

`BENCHMARK_REPORT.md` contains per-task results, provider reliability, intermediary metrics, and the comparison's limitations. These small, differing task samples describe the recorded configurations rather than a general model ranking.

## Resources

- [Model Context Protocol documentation](https://modelcontextprotocol.io/docs/getting-started/intro) — protocol concepts and connecting applications to tools.
- [YouTube](www.youtube.com)

### AI usage

AI was used to understand project concepts, debug and refactor code, review the project specification, inspect implementation details and recorded benchmark results, calculate summary metrics, and write and revise documentation, including the README and benchmark report. Benchmark measurements came from recorded executions.
