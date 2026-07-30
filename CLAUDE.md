# CLAUDE.md — Repo Constitution

**Current state, remaining work, owner directives, and gotchas: [`docs/STATUS.md`](docs/STATUS.md) —
read it at the start of any new session before planning work.**

This file is loaded into context on every session. It is the short, enforceable version of
[`docs/SPEC.md`](docs/SPEC.md) (the full constitution) and [`docs/PLAN.md`](docs/PLAN.md) (the
build plan + corrections). When in doubt, SPEC wins; when SPEC and PLAN disagree, a `docs/DECISIONS.md`
ADR resolves it.

## What this project is
A **firm of specialised agents** that produces auditable investment research on Indian
micro/small/mid-caps (₹300cr–₹30,000cr). It answers ONE question: *can this business plausibly
compound into a 5–10x over 5–8 years, self-funded, under honest management?* It **rejects** anything
that can't prove it, with a full evidence chain. It is **not** a screener with a chatbot, and it
**never** places orders or emits "buy this."

## The 7 laws (violating any is a build failure)
1. **Deterministic compute / LLM narration separation.** No financial number is ever produced by an
   LLM. All math lives in `src/firm/core/compute/` as pure Python with unit tests. LLMs receive
   computed numbers and write *reasoning*, never numbers.
2. **Provenance or it doesn't exist.** Every fact carries `(doc_id, page/para, published_at,
   extractor_version)`. Every number in every report maps to a `fact_id`, checked by a validator.
3. **Point-in-time discipline.** Filter by `published_at <= as_of` **at the query layer**
   (`core/facts/`), never at the agent layer. Look-ahead bias = worthless system.
4. **Structured output contracts.** Every agent returns a Pydantic object (see `schemas/`). Prose
   lives in a `narrative` field. Schema violation → retry ×2 → hard fail with logged artifact.
5. **Idempotent, resumable, cached.** A run is a DAG keyed by
   `hash(agent_version, prompt_version, input_fact_ids, as_of)`. Crash at stage 7 resumes at stage 7.
6. **Portability.** Prompts are markdown in `agents/` (zero prompts in `.py`). All model access goes
   through `core/llm/provider.py`. State is SQLite + Parquet + JSONL + Markdown only. Entry point is
   the `firm` CLI, never a notebook. Everything git-tracked.
7. **Agents never see raw HTML.** Scrapers → bronze, parsers → silver, agents read gold only.

## House analytical standards (all agents inherit — see `agents/_shared/`)
Numbers over adjectives · state the base rate first · say "I don't know" (every output has a
non-empty-suspicious `open_questions`) · separate observation / inference / speculation into distinct
fields · numeric confidence justified by evidence count + grade · disconfirming search is mandatory ·
a management claim is data about *management*, not about the *business* · cite the evidence grade.

## Conventions
- Python lives under `src/firm/`. `python -m firm ...` and the `firm` console script both work.
- **Every hardcoded number lives in `config/thresholds.yaml`.** Nowhere else. No magic numbers in code.
- The compute layer depends on nothing but stdlib + numpy/pydantic — it must be testable offline.
- Tests mirror the tree under `tests/`. `make cov` enforces 100% coverage on `core/compute`.
- Commit prompts, configs, and schemas so changes are diffable. Agent `.md` files carry semver.

## What NOT to do
- Do NOT let an LLM output a computed number. Do NOT skip phases (see `docs/SPEC.md` §11).
- Do NOT build Phase 3 before Phase 1's acceptance test passes.
- Do NOT put India-specific logic outside `src/firm/adapters/india/`. The core is market-agnostic.
- Do NOT make Benford's Law a load-bearing forensic signal (see DECISIONS ADR-0003).
- Do NOT run Beneish/Piotroski on banks/NBFCs/insurers (see DECISIONS ADR-0002).
- Do NOT connect to any broker execution API. Ever. Research artifacts only.

## Build order (do not proceed until acceptance test passes AND the human confirms)
Phase 0 skeleton+contracts → 1 compute → 2 three agents → 3 full roster+orchestrator →
4 judgment tier → 5 memory loop → 6 evaluation. Current phase: **0 → 1** (see PLAN.md).
