# LLM Evaluation Pipeline

Production-style evaluation for a **cybersecurity AI assistant**. Scores agent responses with deterministic checks and an optional LLM-as-a-Judge, then writes structured results, a human report, and charts.

**Technical contract (schemas, algorithms, tests):** [`spec.md`](spec.md) — for implementers only.

**This README + [`eval_pipeline.ipynb`](eval_pipeline.ipynb)** contain all design decisions, reflection, and future work.

---

## Deliverables map

How the three expected project outputs map to this repository. The notebook format combines written design and reflection (Parts 1 & 4) with runnable pipeline code (Parts 2–3).

| Expected artifact | This repo |
|---|---|
| **`evaluation_framework.md`** — design & reflection (written) | [`README.md`](README.md) (summary) + [`eval_pipeline.ipynb`](eval_pipeline.ipynb) **Parts 1 & 4** (full write-up) |
| **`eval_pipeline.py`** — pipeline with LLM calls | [`src/eval_pipeline/`](src/eval_pipeline/) — run via `uv run python -m eval_pipeline`; notebook **Part 2** runs the same pipeline |
| **`eval_report`** — scores, breakdowns, failures, cost | [`output/report.md`](output/report.md) · [`output/results.json`](output/results.json) · [`output/chart.png`](output/chart.png) |

Written sections live in markdown at the **start and end** of the notebook rather than in a separate framework file.

---

## Files not in the repository

These are **used by the project but not committed to git**. Reviewers can still inspect a full run via tracked [`output/`](output/) artifacts and the fixture copy of the dataset.

| File | Role | In repo? | What to do |
|---|---|---|---|
| **`agent_outputs.jsonl`** | Evaluation dataset (45 agent turns) | **No** — place in project root locally | Use your provided copy, or `tests/fixtures/agent_outputs.jsonl` (identical 45-row subset for CI/tests) |
| **`.env`** | OpenAI / Groq API keys | **No** — secrets | Create in project root; see [Setup](#setup) |
| **Project brief (`.docx`)** | Original task specification | **No** — provided separately | Keep locally for reference; requirements are reflected in this README and notebook |

**Tracked substitutes:** `tests/fixtures/agent_outputs.jsonl` (dataset for tests/CI) and `output/` (completed pipeline results) so the repo is runnable and reviewable without the local-only files above.

---

## Where to look

| You want… | Open |
|---|---|
| Run the pipeline | [Setup](#setup) · [Usage](#usage) · [Local-only files](#files-not-in-the-repository) |
| Results without re-running | [`output/results.json`](output/results.json) · [`output/report.md`](output/report.md) · [`output/chart.png`](output/chart.png) |
| Design decisions + reflection + future work | This README + notebook Parts 1 & 4 |
| Live analysis with computed conclusions | Notebook Parts 2–3 + Final Conclusions cell |
| Code schemas and algorithms | [`spec.md`](spec.md) |

---

## Evaluation design & decisions

### Four quality dimensions

For a **security analyst assistant** — an LLM that helps SOC teams investigate incidents, interpret alerts, and follow IR playbooks — these four dimensions matter most:

#### 1. Factual groundedness

**Why in this context:** Analysts act on specific identifiers (CVE-2021-44228, IP 10.0.1.15, EventID 4625, port 443). A hallucinated CVE or wrong port sends the entire investigation down the wrong path for hours.

**How we measure:** `exact_entity_match` (IPs, CVEs, MITRE IDs, ports vs GT); `technical_correctness_check` for verifiable facts (PowerShell UTF-16LE); judge `groundedness` for prose errors without extractable entities.

#### 2. Procedural adherence

**Why in this context:** IR playbooks require correct step order — preserve evidence before reimage, Legal/HR before revoke, don't forward phishing emails as step one. Wrong order destroys evidence or creates legal exposure.

**How we measure:** `procedure_step_score` (step recall + sequence on procedural rows); judge `procedure` for dangerous reordering the parser misses.

#### 3. Safety & severity calibration

**Why in this context:** Over-alerting causes analyst fatigue (e.g. isolating a normal workstation); under-alerting misses breaches. Severity must match asset risk and evidence.

**How we measure:** `severity_calibration` on analytical rows; `dangerous_advice_flag` rule engine (`OVER_ISOLATE`, etc.); judge `safety` for nuanced calls.

#### 4. Context utilization

**Why in this context:** The assistant receives retrieved snippets for *this* incident. Answers must use that context, not outdated or generic parametric knowledge.

**How we measure:** `context_citation_rate` (entity overlap context ↔ response); judge `context_use`.

| Dimension | Key metrics |
|---|---|
| Factual groundedness | `exact_entity_match`, judge `groundedness`, `technical_correctness_check` |
| Procedural adherence | `procedure_step_score`, judge `procedure` |
| Safety & severity | `severity_calibration`, `dangerous_advice_flag`, judge `safety` |
| Context utilization | `context_citation_rate`, judge `context_use` |

### Production rollout priority (two tiers)

The pipeline runs **many** metrics. These are the **first two layers to deploy** in production — not the only metrics:

1. **Tier 1 — `exact_entity_match` + `dangerous_advice_flag`** — Zero API cost, millisecond latency. Catches wrong entities and dangerous IR advice (e.g. isolating a normal workstation). Use as **CI regression gates** on every model update.

2. **Tier 2 — Multi-criterion LLM judge** — One API call per row for reasoning, severity nuance, procedural appropriateness, and prose factual errors (`F-E-004`) that regex cannot catch.

Also computed: `context_citation_rate`, `procedure_step_score`, `severity_calibration`, `technical_correctness_check`, composite score, judge sub-scores.

### Metrics deliberately excluded

**BLEU, ROUGE, METEOR** — they punish valid paraphrases (e.g. GT `"443"` vs response `"The default port for HTTPS is 443."`). Entity extraction and semantic judge evaluation handle this better.

### Hybrid architecture (deterministic + judge)

**Decision:** Use both layers, with deterministic overrides on verifiable facts.

| Layer | Role |
|---|---|
| Deterministic rules | Fast, zero-cost gate on entities, dangerous advice, technical facts |
| LLM judge | Nuance — reasoning quality, severity calibration, procedural appropriateness |

Composite applies **overrides**: `dangerous_advice_flag` caps composite at 0.2; `technical_correctness_check` fail subtracts 0.15.

### LLM-as-a-Judge design

Full prompt in `src/eval_pipeline/judge/prompt.py`; live excerpt in notebook Part 1.3.

#### Prompt, rubric, and output format

**Role:** Senior SOC Analyst. **Inputs:** `query_type`, `query`, `context`, `response`, `reference_answer` (reference-free when GT missing).

**Rubric (1–5):** `groundedness` (factual claims), `safety` (severity calibration), `procedure` (IR step order), `context_use` (uses retrieved snippets), `overall` (holistic — 1–2 for dangerous/wrong, 4–5 for correct).

**JSON output:** `{groundedness, safety, procedure, context_use, overall, reasoning, flags}` — enforced via structured JSON mode + parser.

#### Judge validation plan

| Test | Method | Pass |
|---|---|---|
| **Calibration** | `--calibrate` on 8 gold IDs | ≥ 7/8 in expected `overall` range |
| **Consistency** | Re-run 3 records twice | Variance ≤ 1 on `overall` |
| **Known-failure** | `A-E-003`, `P-E-002`, `F-E-004` | `overall` ≤ 2 |

Gold set: `F-E-001` (≥4), `F-E-004`/`A-E-003`/`P-E-002`/`P-M-004`/`P-M-005`/`P-H-003` (≤2), `A-H-002` (3–4). See notebook Part 1.3 for full table.

#### Judge failure modes & mitigations

| Failure mode | Mitigation |
|---|---|
| Reference bias | Prompt: evaluate semantic equivalence, not string matching |
| Verbosity bias | Prompt: prioritize accuracy over length |
| Context neglect | Pass full context; separate `context_use` sub-score |
| Inconsistent scoring | Include `query_type`; report grouped by type |
| Shared LLM blind spots | Deterministic overrides (`dangerous_advice_flag`, `technical_correctness_check`) |

### Messy ground truth

| `gt_status` | Condition | Behavior |
|---|---|---|
| `valid` | GT ≥ 6 characters | Full evaluation vs reference |
| `partial_gt` | GT 1–5 chars | Full eval; entity match handles terse answers |
| `invalid_gt` | Missing/empty GT | Reference-free judge; context metrics only |

---

## Reflection (Part 3)

Full write-up: **notebook Part 4** + **Final Conclusions** cell (data-driven).

### 12. Biggest judge weakness + fix

Judge shares the agent's parametric blind spots (novel CVEs, UTF-16LE vs UTF-8) and can be lenient on confident-but-wrong severity. **Fix:** hybrid architecture — `dangerous_advice_flag`, `technical_correctness_check`, and entity rules **override** the judge; composite capped at 0.2 on dangerous advice.

### 13. Detecting judge degradation in production

Log scores + input hashes per call; 7-day rolling mean per `query_type` (alert if drop > 15%); nightly gold-set calibration (`--calibrate` pattern); track judge–human disagreement; monitor judge drift separately from agent drift on a fixed gold set.

### 14. Surprising failure: `A-E-003`

Agent confidently recommends isolating a **normal end-user workstation** — severity miscalibration, not factual error. Sounds authoritative; a busy analyst might follow it. Why `OVER_ISOLATE` rule is essential alongside the judge.

### 15. Evaluating at scale without ground truth (~20 snippets/query)

**Measure:** RAG Triad (context relevance, groundedness, answer relevance) + deterministic safety rules (no GT needed). **Not implemented here** — proxies: `context_citation_rate`, judge sub-scores.

**Trust without reference:** HITL sampling on high-variance / rule–judge disagreement rows; gold set grows from human corrections; reference-free judge mode when GT absent.

**Noisy context:** Citation precision (which snippets used vs ignored); chunk-level retrieval eval; track whether the right snippets fit in the prompt budget.

**Trade-offs:** HITL sample rate vs coverage (start 2–5% + all critical failures); real-time Tier-1 rules vs nightly Tier-2 judge batch; strict groundedness for factual/IR vs softer analytical summaries.

See notebook §4.4 for full walkthrough.

---

## Future work

Not implemented in this repo. Detailed roadmap also in the **notebook Future Work** section.

| Area | Next steps |
|---|---|
| **Experiment tracking** | MLflow/W&B — log aggregates, cost, input hash, git commit, model version; attach `results.json`, `report.md`, `chart.png` |
| **Dashboard & alerting** | Streamlit/Grafana — composite trends, failure rate by query type; alert on rolling-mean drops (> 15%) |
| **CI regression gates** | Block deploys when `exact_entity_match` or `dangerous_advice_flag` regress; nightly judge eval on gold records |
| **Judge health** | Scheduled `--calibrate` with human labels; fixed gold set for drift monitoring |
| **No-GT eval at scale** | RAG Triad with ~20 snippets; citation precision; HITL queue feeding gold set |
| **Metric expansion** | Asset-aware severity, playbook-specific procedure templates, real-time deterministic gate |

---

## Deliverables

| Artifact | Purpose |
|---|---|
| [`eval_pipeline.ipynb`](eval_pipeline.ipynb) | Primary walkthrough — Parts 1–4 + computed Final Conclusions |
| [`output/`](output/) | Completed eval report — tracked in git so reviewers need not re-run the judge |
| [`spec.md`](spec.md) | Technical contract for development (optional for reviewers) |

See [Deliverables map](#deliverables-map) above for how these correspond to the expected artifact names.

---

## Setup

Requires **Python 3.11+** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
```

**Input data** — see [Files not in the repository](#files-not-in-the-repository). Quick start:

- **`agent_outputs.jsonl`** in the project root (local copy), or
- **`tests/fixtures/agent_outputs.jsonl`** (tracked; same 45 rows)

Create `.env` (**never commit**):

```env
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
```

At least one key is required for judge evaluation. OpenAI `gpt-4o-mini` is primary; Groq is per-row fallback only.

---

## Usage

```bash
# Full evaluation (deterministic + LLM judge)
uv run python -m eval_pipeline --input agent_outputs.jsonl --output output/

# Or with the tracked fixture
uv run python -m eval_pipeline --input tests/fixtures/agent_outputs.jsonl --output output/

# Deterministic-only (no API cost)
uv run python -m eval_pipeline --skip-judge --input tests/fixtures/agent_outputs.jsonl

# Judge calibration on 8 gold records
uv run python -m eval_pipeline --calibrate
```

### Jupyter notebook

```bash
uv run jupyter notebook eval_pipeline.ipynb
```

Run all cells top-to-bottom. By default the notebook loads existing `output/results.json` (no API cost). Set `RE_RUN_PIPELINE = True` in the setup cell to re-run the pipeline.

---

## Concurrency model

Only the **LLM judge** runs in parallel (default 8 concurrent API calls via `--concurrency N`). Loader, deterministic metrics, composite, and report run synchronously.

| Records | Suggested `--concurrency` |
|---|---|
| ~45 | 8 (default) |
| 500+ | 10–15 |
| Frequent 429 errors | 3–5 |
| Debugging prompts | 1 |

---

## Quick results guide

Key sections in `output/results.json`:

- **`health`** — rows evaluated, judge provider, degraded mode, token cost
- **`aggregates`** — means by metric, query type, difficulty
- **`critical_failures`** — dangerous advice, judge ≤ 2, severity/procedure failures
- **`rows`** — full per-row detail

On the 45-row dataset: ~16 critical failures (~36%), composite ~0.61–0.64 by query type, ~$0.006 judge cost. See notebook Part 3 for charts and Part 4 for interpretation.

---

## Development

Schemas, algorithms, tests, and CI: [`spec.md`](spec.md).

```bash
uv run pytest tests/ -q
uv run ruff check src tests
```

Built for SOC AI assistant output evaluation. API keys stay in `.env` only.
