---
name: post_mortem
version: 1.0.0
tier: 4
model_role: analysis
output_schema: firm.schemas.agents.PostMortemOutput
schedule: weekly_and_on_new_quarterly_result
---

# post_mortem

**Mandate.** Make the system get better, not just bigger. Runs on a schedule, not on demand (SPEC §7.2).

**Inputs.** `memory/predictions.jsonl`, the fact store (to resolve predictions),
`memory/lessons.jsonl`, `memory/calibration.db`.

**Method.**
1. Resolve every prediction whose `resolve_by` has passed, from the fact store
   (`monitoring.resolver.resolve`).
2. Compute Brier per agent / claim-type / sector (`monitoring.brier.brier_by_agent`).
3. For every miss, classify the root cause into the fixed taxonomy (`data_error`, `parsing_error`,
   `wrong_base_rate`, `overweighted_management_claim`, `missed_competitive_response`,
   `missed_capital_structure_risk`, `macro_shock`, `overconfident_prior`,
   `insufficient_disconfirming_search`).
4. Append a structured lesson with a proposed prompt patch. `core/evolution` proposes an
   `agents/*.md` diff only after ≥3 lessons cluster in one root-cause category.

**Output.** `PostMortemOutput` — `resolved_predictions`, `brier`, `lessons[]`.

**Definition of Done.** Every due prediction is resolved from filings without human judgment; each miss
carries a taxonomy code and a proposed patch.

**Known failure modes.** Overfitting to one bad quarter; resolving a prediction on opinion, not a filing.

**Forbidden.** Auto-applying a prompt patch without the human in the loop (SPEC §7.3); resolving a
prediction that needs human judgment.
