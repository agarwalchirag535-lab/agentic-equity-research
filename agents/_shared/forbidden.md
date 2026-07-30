# Forbidden — anti-patterns that fail a run

- **Inventing or computing a number.** Any figure not carrying a `fact_id` from `core/compute/` is a
  hard fail (Law 1).
- **Vague quantifiers.** "Strong", "healthy", "significant", "robust", "meaningful" without a number.
- **Unsourced claims.** Every factual assertion needs a citation token → `fact_id` (Law 2).
- **Look-ahead.** Referencing anything with `published_at > as_of`. The query layer prevents this; an
  agent that works around it fails the run (Law 3).
- **Free-prose hand-offs.** Agents read each other's JSON, never each other's prose (Law 4).
- **Reading raw HTML/PDF.** Agents read gold fact tables only (Law 7).
- **Emitting "buy" / a target price as advice.** Output is a thesis with assumptions, probabilities, and
  kill criteria — never a recommendation to transact (SPEC §1).
- **Empty `open_questions` / no disconfirming search.** Treated as a quality failure, not a strength.
- **Treating a management claim as fact.** It is grade-C data about management until an audited filing
  confirms it.
- **Building a thesis pillar on grade-D evidence alone.**
