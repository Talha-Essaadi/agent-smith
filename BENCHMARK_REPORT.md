# Model Benchmark Report

## 1. Setup

This report compares eight models across four hosted providers and one local endpoint using 24 SWE-bench runs tested through the moulinette on 23–24 November 2026. Model identifiers, providers, results, and metrics come from the recorded benchmark runs.

Models are ordered by validated SWE-bench solve rate, with lower cumulative input-token use breaking ties among models that solved tasks. Models with no validated solves remain tied. The models received different three-task samples, so this ordering reflects the recorded runs rather than a comparison on identical tasks.

| Report label | Exact configured model ID | Provider / serving endpoint |
|---|---|---|
| Qwen | `qwen/qwen3.8-27b` | Groq |
| Particle | `particle-ai/particle-1:free` | OpenRouter |
| Gemini | `gemini-3.5-flash-lite` | Google Gemini API |
| Nemotron | `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter |
| LFM3 | `lfm3:latest` | Local OpenAI-compatible endpoint |
| GPT-OSS | `openai/gpt-oss-120b` | Groq |
| Command A+ | `command-a-plus-05-2026` | Cohere |
| Flint | `recursive/flint-v1.0:free` | OpenRouter |

Three SWE-bench tasks were selected per model through the moulinette. Across the recorded runs, the tasks cover framework behavior, mutable state, symbolic computation, and estimator APIs.

| Task | Behavior tested | Reason for inclusion in the coverage analysis |
|---|---|---|
| `django__django-11066` | Database alias propagation when saving content types | Database routing in a framework |
| `pydata__xarray-4629` | Copying attributes under `combine_attrs="override"` | Mutable state and unintended aliasing |
| `sympy__sympy-13480` | Incorrect variable reference in hyperbolic function handling | Localized symbolic-function debugging |
| `sympy__sympy-14711` | Vector addition involving scalar zero | Operator compatibility |
| `sympy__sympy-18189` | Propagating `permute` in recursive Diophantine solving | Recursive option propagation |
| `scikit-learn__scikit-learn-13439` | Pipeline construction and validation behavior | Estimator API behavior |

All main runs share the same saved SWE-bench system prompt. The agent uses a Thought → Code → Observation loop, MCP tools, and sandboxed execution in task-specific Docker environments. The configured task limits are 30 iterations, 300,000 cumulative input tokens, 10,000 cumulative output tokens, and 900 seconds.

Testing followed the moulinette workflow:

1. Select task identifiers with `moulinette_eval select swebench` and export each task with `moulinette_eval dump swebench`.
2. Launch the agent with the selected model and provider through `moulinette_eval run-agent`, enforcing a 900-second process timeout. The agent explores the repository, edits code, and produces a patch.
3. Evaluate the returned patch with `moulinette_eval validate swebench`, which evaluates correctness and recorded resource usage.
4. Collect the moulinette verdict alongside iteration counts, token totals, wall time, and per-step observations for comparison.

## 2. Results

Pass/Fail reflects the moulinette validation verdict, including correctness and resource limits, rather than whether the agent reached submission. Tokens and iterations are the recorded totals. Wall time includes generation, retry waits, tool execution, and fallback patch retrieval, excluding container startup and moulinette validation.

### Models ordered by recorded performance

| Rank | Model | Passed | Total input tokens | Total output tokens | Mean iterations | Mean wall time (s) |
|---:|---|---|---:|---:|---:|---:|
| 1 | Qwen | 3/3 | 31,690 | 732 | 3.33 | 69.41 |
| 2 | Particle | 3/3 | 81,927 | 1,625 | 5.67 | 63.53 |
| 3 | Gemini | 2/3 | 92,345 | 1,363 | 4.33 | 84.64 |
| 4 | Nemotron | 1/3 | 227,497 | 11,484 | 16.67 | 133.29 |
| 5 | LFM3 | 1/3 | 519,847 | 28,874 | 22.33 | 124.69 |
| 6 | GPT-OSS | 0/3 | 46,758 | 7,724 | 5.00 | 77.94 |
| 6 | Command A+ | 0/3 | 45,985 | 10,000 | 2.33 | 45.20 |
| 6 | Flint | 0/3 | 145,839 | 1,709 | 13.33 | 38.96 |

Qwen and Particle both passed 3/3. Qwen used fewer recorded tokens, but all three runs ended on rate limits and relied on fallback patch retrieval; Particle completed normal submission in every run. Gemini passed 2/3, with the remaining run failing before any usable response. Nemotron and LFM3 each passed 1/3; GPT-OSS, Command A+, and Flint passed none.

On shared xarray 4629, Particle passed with 21,902 input tokens in 52.36 seconds, compared with Gemini's 88,854 tokens in 97.52 seconds and LFM3's 172,827 tokens in 144.63 seconds. This shared-task comparison supports Particle's efficiency independently of the differing overall assignments.

### Per-model × task results

| Model | Task | Verdict | Iterations | Input tokens | Output tokens | Wall time (s) |
|---|---|---|---:|---:|---:|---:|
| Qwen | `django__django-11066` | Pass | 2 | 7,966 | 168 | 46.04 |
| Qwen | `sympy__sympy-13480` | Pass | 6 | 16,932 | 389 | 120.62 |
| Qwen | `sympy__sympy-18189` | Pass | 2 | 6,792 | 175 | 41.57 |
| Particle | `django__django-11066` | Pass | 6 | 30,436 | 692 | 29.64 |
| Particle | `pydata__xarray-4629` | Pass | 5 | 21,902 | 369 | 52.36 |
| Particle | `sympy__sympy-18189` | Pass | 6 | 29,589 | 564 | 108.58 |
| Gemini | `pydata__xarray-4629` | Pass | 12 | 88,854 | 955 | 97.52 |
| Gemini | `sympy__sympy-13480` | Fail | 0 | 0 | 0 | 117.41 |
| Gemini | `sympy__sympy-18189` | Pass | 1 | 3,491 | 408 | 39.00 |
| Nemotron | `pydata__xarray-4629` | Fail | 8 | 79,316 | 9,220 | 216.44 |
| Nemotron | `scikit-learn__scikit-learn-13439` | Fail | 30 | 96,253 | 1,046 | 74.25 |
| Nemotron | `sympy__sympy-13480` | Pass | 12 | 51,928 | 1,218 | 109.17 |
| LFM3 | `pydata__xarray-4629` | Pass | 20 | 172,827 | 8,874 | 144.63 |
| LFM3 | `scikit-learn__scikit-learn-13439` | Fail | 22 | 151,770 | 10,000 | 114.91 |
| LFM3 | `sympy__sympy-14711` | Fail | 25 | 195,250 | 10,000 | 114.54 |
| GPT-OSS | `scikit-learn__scikit-learn-13439` | Fail | 5 | 11,850 | 3,919 | 56.12 |
| GPT-OSS | `sympy__sympy-14711` | Fail | 4 | 12,069 | 2,406 | 69.46 |
| GPT-OSS | `sympy__sympy-18189` | Fail | 6 | 22,839 | 1,399 | 108.24 |
| Command A+ | `django__django-11066` | Fail | 0 | 0 | 0 | 43.30 |
| Command A+ | `scikit-learn__scikit-learn-13439` | Fail | 0 | 0 | 0 | 46.37 |
| Command A+ | `sympy__sympy-14711` | Fail | 7 | 45,985 | 10,000 | 45.95 |
| Flint | `django__django-11066` | Fail | 0 | 0 | 0 | 35.12 |
| Flint | `pydata__xarray-4629` | Fail | 30 | 112,650 | 752 | 31.13 |
| Flint | `sympy__sympy-18189` | Fail | 10 | 33,189 | 957 | 50.63 |

Qwen's passing patches were recovered after API failures despite `success=false`. Nemotron's xarray run reached `final_answer` with `success=true`, but failed validation because the solution did not look like a git patch. These cases explain why the results use moulinette verdicts.

## 3. Provider reliability

Mean response time is the step-weighted average of `request_time_ms`, which times the accepted HTTP request and excludes earlier failed attempts and backoff. Recorded retries are `sum(steps[].retries)`. Terminal six-attempt failures produce no step and are reported separately. “Response runs” counts runs with at least one usable response; “no terminal API failure” counts runs that avoided exhausting API attempts.

| Model / provider | Mean accepted response (s) | Recorded retries | Terminal six-attempt batches | Response runs | Runs with no terminal API failure |
|---|---:|---:|---:|---|---|
| Qwen / Groq | 1.10 | 20 | 3 | 3/3 | 0/3 |
| Particle / OpenRouter | 1.36 | 6 | 0 | 3/3 | 3/3 |
| Gemini / Google Gemini API | 2.70 | 6 | 1 | 2/3 | 2/3 |
| Nemotron / OpenRouter | 5.78 | 0 | 0 | 3/3 | 3/3 |
| LFM3 / Local OpenAI-compatible endpoint | 4.65 | 1 | 0 | 3/3 | 3/3 |
| GPT-OSS / Groq | 1.85 | 16 | 3 | 3/3 | 0/3 |
| Command A+ / Cohere | 5.50 | 1 | 2 | 1/3 | 1/3 |
| Flint / OpenRouter | 1.08 | 0 | 2 | 2/3 | 1/3 |

- **Qwen / Groq:** all three runs ended with HTTP 429 input-token-per-minute limits. Accepted requests were fast, but the configuration could not complete normal submission.
- **Particle / OpenRouter:** all three runs completed without terminal API failure; six retries were recorded.
- **Gemini / Google:** one run exhausted attempts with HTTP 503 high-demand errors; two runs obtained responses and passed.
- **Nemotron / OpenRouter:** no recorded retries or terminal API failures. Its failures arose from submission format and unproductive tool use.
- **LFM3 / local endpoint:** no terminal API failures, but 27/67 responses had extraction errors and two tasks exhausted the output budget.
- **GPT-OSS / Groq:** two terminal HTTP 429 failures and one HTTP 413 request-too-large failure against the recorded quota ceiling.
- **Command A+ / Cohere:** two runs exhausted attempts with HTTP 422 “No valid response generated”; the remaining run had seven extraction errors and exhausted its output budget.
- **Flint / OpenRouter:** two terminal failures reported the free-model daily quota. The remaining run reached 30 iterations without solving.

Successful-call retry reasons are not individually saved, so those retries cannot be separated reliably into rate limits, timeouts, and other errors. For Qwen, the three terminal batches represent 18 additional failed attempts beyond its 20 recorded retries. Zero recorded tokens in a zero-step run do not mean that no requests occurred.

## 4. Intermediary metrics

Two metrics were inspected manually: exploration efficiency and submission discipline. “First read/edit” refers to the first successful read/edit of the primary source file in the saved patch. “First green” is the first post-edit targeted test command with recorded exit code zero. The gap counts intervening iterations before `final_answer`; submission in the next iteration has gap zero. Runs without a saved patch have no final patched file to measure.

| Model | Task | First read | First edit | First green targeted command | `final_answer` step | Gap |
|---|---|---:|---:|---:|---:|---:|
| Qwen | Django 11066 | 1 | 2 | Not run | Not reached | N/A |
| Qwen | SymPy 13480 | 1 | 2 | 6 | Not reached | N/A |
| Qwen | SymPy 18189 | 1 | 2 | Not run | Not reached | N/A |
| Particle | Django 11066 | 1 | 2 | 3 | 6 | 2 |
| Particle | xarray 4629 | 2 | 3 | 3 | 5 | 1 |
| Particle | SymPy 18189 | 1 | 2 | 3 | 6 | 2 |
| Gemini | xarray 4629 | 3 | 5 | 9 | 12 | 2 |
| Gemini | SymPy 18189 | 1 | 1 | Not run | 1 | N/A |
| Nemotron | SymPy 13480 | 2 | 3 | 6 | 12 | 5 |
| LFM3 | xarray 4629 | 13 | 15 | 16 | 20 | 3 |

Particle reads the relevant source file within one or two steps and edits within two or three. LFM3 reads the correct xarray source file only at step 13 after malformed responses and incorrect path guesses, illustrating the cost of inefficient exploration.

Particle runs the evaluation script at step 4 in all three tasks, so part of the targeted-test gap is additional validation. Relative to those exit-zero evaluation calls, it has zero intervening steps on xarray and one on Django/SymPy. Nemotron repeats targeted testing after its step-10 evaluation call before submitting at step 12.

Gemini's xarray pre-edit tests already passed at step 4; the table uses the post-edit result at step 9. Its SymPy 18189 run submits without recorded testing. Qwen never reaches `final_answer`. The first green SymPy 13480 outputs for Qwen and Nemotron are truncated; Nemotron later records an explicit 45-passed summary at step 11. Exit-zero commands alone do not establish full task correctness; moulinette validation supplies that verdict.

## 5. Ablation study

The available before/after comparison uses **GPT-OSS on Groq, SymPy 14711**, with an earlier development trace from 22 November and the evaluation trace from 24 November.

The later prompt shortens three tool descriptions: it removes output-format examples from `read_file` and `search_code`, and the fallback-pytest detail from `run_tests`. The debugging workflow remains unchanged.

| Metric | Before | After |
|---|---:|---:|
| Recorded iterations | 7 | 4 |
| Input tokens | 21,791 | 12,069 |
| Output tokens | 3,359 | 2,406 |
| Agent-loop time | 105.37 s | 69.46 s |
| Recorded retries | 9 | 5 |
| Saved patch | Empty | Empty |
| Normal submission | Not reached | Not reached |
| Moulinette verdict | Not saved | Fail |
| Terminal failure | HTTP 429 | HTTP 413 |

Input-token use decreased by 44.6% and wall time by 33.9%, but neither run produced a patch. The later run stopped earlier during exploration with HTTP 413; the earlier run reached an unsuccessful edit attempt before HTTP 429 termination. Lower resource use therefore does not demonstrate improved solving efficiency.

This is an exploratory comparison, not a controlled ablation: provider conditions and other implementation changes were not held constant, and no moulinette verdict is saved for the earlier run. The available artifacts do not establish a controlled before/after improvement.

## 6. Conclusions

**Select Particle on OpenRouter as the SWE-bench primary.** It passed 3/3 assigned tasks, completed normal submission every time, and used substantially fewer tokens than Gemini and LFM3 on shared xarray 4629. Its reliable completion makes it preferable to the token-efficiency leader Qwen for the current pipeline.

**Select Gemini as the alternative provider configuration.** It passed 2/3 with low output-token use; its only failure was an HTTP 503 before coding began. Its independent provider quota offers an alternative when OpenRouter is unavailable.

**Retain Qwen for further testing after quota handling improves.** It produced three validated patches with the lowest cumulative input use among models with solves, but every run terminated on rate limits before normal submission.

**Disregard Nemotron and LFM3 as current defaults.** Both passed only 1/3; Nemotron submitted an invalid patch value on xarray and spent 30 iterations without useful visible feedback on sklearn, while LFM3 had frequent extraction errors and high token use.

**Disregard GPT-OSS, Command A+, and Flint in their current SWE-bench configurations.** Each passed 0/3. GPT-OSS was blocked by quota/request-size errors; Command A+ had endpoint and response-format failures; Flint combined daily-quota failures with pervasive extraction errors. These conclusions apply to the tested integrations and task samples.

