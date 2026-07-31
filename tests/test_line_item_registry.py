"""Integrity of `config/line_items.yaml` itself (ADR-0022).

The registry is the one place where a silent failure is genuinely dangerous. A question whose `metric:`
is misspelled does not raise — it resolves to "no derivation for this metric", is classified as a
CAPABILITY gap, and then sits in every report forever as an unanswerable question that the pipeline could
in fact have answered. It would look exactly like honest humility. These tests make that typo loud.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.compute.models import BusinessModel
from firm.core.config import line_item_registry
from firm.core.pipeline.derive import derive_metrics, load_company_facts
from firm.core.pipeline.filing import walk_filing
from firm.core.pipeline.interrogate import AnswerStatus, interrogate
from tests.conftest import (
    AS_OF,
    clean_series,
    filing_for,
    seed_store,
    with_working_capital,
)

REGISTRY = line_item_registry()
QUESTIONS = [
    (item["id"], q)
    for item in REGISTRY["line_items"]
    for q in item["questions"]
]
VALID_UNITS = {"pct", "pp", "ratio", "inr_cr", "x", "days", "days_delta"}
VALID_SEVERITIES = {"high", "medium", "low"}
VALID_MODELS = {m.value for m in BusinessModel}


def test_the_registry_actually_loads_and_is_not_empty():
    assert REGISTRY["version"]
    assert len(REGISTRY["line_items"]) >= 8
    assert len(QUESTIONS) >= 25


@pytest.mark.parametrize(("line_item", "q"), QUESTIONS, ids=[f"{i}.{q['id']}" for i, q in QUESTIONS])
def test_every_question_is_well_formed(line_item, q):
    assert q["id"] and q["question"], f"{line_item}: a question needs an id and a question"
    assert q.get("severity", "medium") in VALID_SEVERITIES
    if "unit" in q:
        assert q["unit"] in VALID_UNITS, f"{q['id']}: unknown unit {q['unit']!r}"
    for key in ("models", "exclude_models"):
        for model in q.get(key) or ():
            assert model in VALID_MODELS, f"{q['id']}: {model!r} is not a BusinessModel"


@pytest.mark.parametrize(("line_item", "q"), QUESTIONS, ids=[f"{i}.{q['id']}" for i, q in QUESTIONS])
def test_a_question_that_can_go_unanswered_names_what_would_answer_it(line_item, q):
    """P4 enforces this per report; here it is enforced once, at the source, for every question.

    A question with no `metric` can ONLY ever be unanswered, so it must carry `needs`. A question with a
    `metric` may still fail (absent inputs, or an implausible value), so it needs them too unless its
    metric is one the screener always provides.
    """
    if "metric" not in q or "plausible" in q:
        assert q.get("needs"), f"{q['id']}: can be unanswered but names nothing that would answer it"


@pytest.mark.parametrize(("line_item", "q"), QUESTIONS, ids=[f"{i}.{q['id']}" for i, q in QUESTIONS])
def test_a_metric_question_has_a_template_to_render_it(line_item, q):
    if "metric" in q:
        assert "{v}" in q.get("template", ""), f"{q['id']}: a metric question must render its value"
    if "against" in q:
        assert "{a}" in q["template"], f"{q['id']}: an 'against' question must render the comparator"


@pytest.mark.parametrize(("line_item", "q"), QUESTIONS, ids=[f"{i}.{q['id']}" for i, q in QUESTIONS])
def test_band_thresholds_descend_so_the_first_match_is_the_tightest(line_item, q):
    """Bands are evaluated top-down, so an ascending `at_least` list would make later bands unreachable."""
    floors = [b["at_least"] for b in (q.get("bands") or ()) if "at_least" in b]
    assert floors == sorted(floors, reverse=True), f"{q['id']}: at_least bands must descend"
    bare = [b for b in (q.get("bands") or ()) if "at_least" not in b and "at_most" not in b]
    assert len(bare) <= 1, f"{q['id']}: more than one fallback band — the later ones are dead"
    if bare:
        assert q["bands"][-1] is bare[0], f"{q['id']}: the fallback band must be last or it shadows"


def test_every_referenced_metric_is_one_the_pipeline_could_actually_produce(store):
    """The typo guard, and the one test that would have caught a renamed derivation.

    A metric named here must either be derivable today or be a KNOWN gap listed below. Anything else is a
    misspelling that would masquerade as honest humility in every future report.

    "Derivable" means *by the pipeline*, not *by the screener*: a run walks an audited filing as well, and
    the Schedule III ageing metrics (ADR-0039) exist only on that path. Judging the registry against a
    screener-only fixture would have declared every filing-sourced question a typo.
    """
    seed_store(store, "FULLCO", with_working_capital(clean_series()))
    walk_filing(store, "FULLCO", filing_for("FULLCO"))
    derived = derive_metrics(load_company_facts(store, "FULLCO", AS_OF))
    derivable = set(derived.values) | set(derived.missing)

    # Metrics the registry asks for on purpose that no derivation exists for YET. Each one is a real
    # capability gap with a named owner in STATUS.md §3; shrinking this set is the work.
    #
    # EMPTIED 2026-07-31 (ADR-0038). It held `receivable_days`, `receivable_days_delta` and
    # `inventory_days` — all three derivable from balance-sheet rows the pipeline had been storing as
    # grade-A facts for ten years. The allowlist was not documenting a data gap; it was licensing the
    # report to answer "unavailable" to a question we could already answer. Keep it empty if you can:
    # adding an entry here is a decision to publish an excuse, so it needs a STATUS.md line saying why.
    known_capability_gaps: set[str] = set()
    referenced = {q["metric"] for _, q in QUESTIONS if "metric" in q}
    unknown = referenced - derivable - known_capability_gaps
    assert not unknown, (
        f"registry references metric(s) no derivation produces: {sorted(unknown)}. Either add the "
        f"derivation, or add it to known_capability_gaps with a STATUS.md entry."
    )


def test_a_fully_disclosed_company_answers_most_questions_it_can(store):
    """Guards against the registry drifting into a list of questions nothing can ever answer.

    On the richest fixture available, the derivable questions should mostly resolve — if this drops, the
    registry has grown aspiration faster than capability.
    """
    seed_store(store, "RICHCO", clean_series())
    derived = derive_metrics(load_company_facts(store, "RICHCO", AS_OF))
    result = interrogate(derived, ["MANUFACTURER"], REGISTRY)

    answered = [a for a in result.all_answers if a.status is AnswerStatus.ANSWERED]
    assert len(answered) >= 12, "the registry can no longer answer what the compute layer provides"
    # And every answered finding must actually contain a rendered number.
    assert all(any(ch.isdigit() for ch in a.finding) for a in answered)


def test_lender_scoping_suppresses_the_questions_adr_0002_forbids(store):
    """Inventory and receivable questions are invalid for a lender and must be suppressed, not answered."""
    seed_store(store, "LENDCO", clean_series())
    derived = derive_metrics(load_company_facts(store, "LENDCO", AS_OF))
    result = interrogate(derived, ["LENDER"], REGISTRY)

    suppressed = {a.question_id for a in result.all_answers
                  if a.status is AnswerStatus.NOT_APPLICABLE}
    assert {"wc_receivable_days", "wc_inventory_days", "revenue_volume_or_price"} <= suppressed
    assert all(a.reason for a in result.all_answers if a.status is AnswerStatus.NOT_APPLICABLE)


def test_statutory_tax_rate_is_config_not_prose():
    """The tax question compares against a real rate; it must come from config, not a hardcoded string."""
    assert REGISTRY["statutory"]["corporate_tax_rate"] == pytest.approx(0.2517)
