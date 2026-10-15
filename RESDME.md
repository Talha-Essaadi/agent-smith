# Architecture:
```sh
   student/
     agent_core/       # loop, extraction, prompts, manual generator
     llm/              # provider abstraction, key rotation, usage tracking
     sandbox/          # config, executor, restrictions, MCP client bridge
     models/           # Pydantic models (task input, StepMetrics, SolutionOutput)
     agent_mbpp/       # __main__.py CLI
     agent_swebench/   # __main__.py CLI
   mcp_tools_mbpp.py        # root of repo
   mcp_tools_swebench.py    # root of repo
   sandbox_template.json
   BENCHMARK_REPORT.md, README.md


        agent-smith/
        ├── src/agent_smith/
        │   ├── llm/                 # Student 1
        │   ├── agents/              # Student 1
        │   ├── orchestrator.py      # Student 1
        │   ├── sandbox/             # Student 2
        │   ├── mcp/                 # Student 2
        │   ├── config.py            # Shared
        │   └── models.py            # Shared contract
        ├── mcp_tools_mbpp.py        # Student 2
        ├── mcp_tools_swebench.py    # Student 2
        ├── tests/                   # Both
        ├── BENCHMARK_REPORT.md      # Both
        └── README.md                # Both



agent-smith/
├── pyproject.toml
├── uv.lock
├── README.md
├── BENCHMARK_REPORT.md
├── sandbox_template.json
├── mcp_tools_mbpp.py             # Student 2
├── mcp_tools_swebench.py         # Student 2
│
├── src/
│   └── agent_smith/
│       ├── __init__.py
│       ├── config.py             # Shared configuration
│       ├── models.py             # Shared data contracts
│       │
│       ├── llm/                  # Student 1
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── providers.py
│       │   └── usage.py
│       │
│       ├── agents/               # Student 1
│       │   ├── __init__.py
│       │   ├── agent.py
│       │   ├── prompts.py
│       │   └── extraction.py
│       │
│       ├── orchestrator.py       # Student 1
│       │
│       ├── sandbox/              # Student 2
│       │   ├── __init__.py
│       │   ├── executor.py
│       │   ├── config.py
│       │   └── result.py
│       │
│       ├── mcp/                  # Student 2
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── discovery.py
│       │   └── errors.py
│       │
│       ├── agent_mbpp/           # Shared integration
│       │   ├── __init__.py
│       │   └── __main__.py
│       │
│       └── agent_swebench/       # Shared integration
│           ├── __init__.py
│           └── __main__.py
│
└── tests/
    ├── test_sandbox.py
    ├── test_mcp_tools.py
    ├── test_agent_loop.py
    └── test_integration.py



mkdir -p agent-smith/src/agent_smith/{llm,agents,sandbox,mcp,agent_mbpp,agent_swebench} \
         agent-smith/tests

cd agent-smith

# Root files
touch pyproject.toml uv.lock README.md BENCHMARK_REPORT.md \
      sandbox_template.json mcp_tools_mbpp.py mcp_tools_swebench.py

# Main package
touch src/agent_smith/__init__.py \
      src/agent_smith/config.py \
      src/agent_smith/models.py \
      src/agent_smith/orchestrator.py

# LLM module — Student 1
touch src/agent_smith/llm/__init__.py \
      src/agent_smith/llm/client.py \
      src/agent_smith/llm/providers.py \
      src/agent_smith/llm/usage.py

# Agents module — Student 1
touch src/agent_smith/agents/__init__.py \
      src/agent_smith/agents/agent.py \
      src/agent_smith/agents/prompts.py \
      src/agent_smith/agents/extraction.py

# Sandbox module — Student 2
touch src/agent_smith/sandbox/__init__.py \
      src/agent_smith/sandbox/executor.py \
      src/agent_smith/sandbox/config.py \
      src/agent_smith/sandbox/result.py

# MCP module — Student 2
touch src/agent_smith/mcp/__init__.py \
      src/agent_smith/mcp/client.py \
      src/agent_smith/mcp/discovery.py \
      src/agent_smith/mcp/errors.py

# Benchmark entry points
touch src/agent_smith/agent_mbpp/__init__.py \
      src/agent_smith/agent_mbpp/__main__.py \
      src/agent_smith/agent_swebench/__init__.py \
      src/agent_smith/agent_swebench/__main__.py

# Tests
touch tests/test_sandbox.py \
      tests/test_mcp_tools.py \
      tests/test_agent_loop.py \
      tests/test_integration.py

# Display the resulting architecture
find . -type f | sort

```

```sh
                 Agent Smith
                      │
       ┌──────────────┼──────────────┐
       ↓              ↓              ↓
    LLM APIs      Agent loops      MCP
       │              │              │
       ↓              ↓              ↓
 Providers        Planning       Tool calling
 Token rotation   Iteration      Dynamic tools
       │              │              │
       └──────────────┼──────────────┘
                      ↓
                   Sandbox
                      │
              ┌───────┼────────┐
              ↓       ↓        ↓
           Security  Docker  Execution
                      │
                      ↓
                 SWE-bench
                      │
                      ↓
                 Benchmarking
```

# Steps:

```sh
STEP 1
Basic LLM API client
        ↓
STEP 2
Simple Thought → Code → Observation loop
        ↓
STEP 3
Code extraction
        ↓
STEP 4
Sandbox
        ↓
STEP 5
MCP server/client
        ↓
STEP 6
MBPP agent
        ↓
STEP 7
Metrics + SolutionOutput
        ↓
STEP 8
SWE-bench agent
        ↓
STEP 9
Multiple providers
        ↓
STEP 10
Benchmark 5 models
        ↓
STEP 11
Security testing
        ↓
STEP 12
README + benchmark report
```