"""Every check a playbook can select must have an evaluator, or be declared missing (ADR-0051).

The failure this prevents is the one ADR-0050 found the hard way. All seven lender checks were selected
by `config/forensic_playbooks.yaml`, backed by unit-tested compute functions in `quality.py`, and cited
in `VALIDATION_TIER0.md` as validated — and not one had an evaluator in `checks.py`, so a lender's report
could only ever say UNAVAILABLE. Nothing failed, because every individual part looked finished.

These tests are behavioural rather than textual: they run the real evaluator over every model's real
playbook and read the outcomes, so they cannot be fooled by a refactor of the dispatch.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.compute.models import BusinessModel, build_playbook
from firm.core.config import (
    load_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.facts.store import FactStore
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import (
    NOT_IMPLEMENTED_PREFIX,
    UNIMPLEMENTED_CHECKS,
    evaluate_checks,
)

PLAYBOOKS = model_playbooks()
MODELS = [[], *[[m] for m in BusinessModel]]


def _evaluate(models):
    """Run the real evaluator over a real playbook with NO facts, so every check reaches its
    'inputs absent' path — which is exactly where a missing evaluator hides."""
    playbook = build_playbook(models, PLAYBOOKS)
    facts = D.load_company_facts(FactStore(":memory:"), "X", date(2026, 3, 31), start_year=2025)
    return playbook, evaluate_checks(
        playbook, D.derive_metrics(facts), facts, forensic=load_thresholds()["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds())


@pytest.mark.parametrize("models", MODELS, ids=lambda m: m[0].value if m else "UNIVERSAL")
def test_every_selectable_check_is_wired_or_declared(models):
    playbook, evaluation = _evaluate(models)
    for check in playbook.applies:
        record = evaluation.record(check)
        assert record is not None, f"{check} was selected but produced no record at all"
        if NOT_IMPLEMENTED_PREFIX in record.reason:
            assert check in UNIMPLEMENTED_CHECKS, (
                f"'{check}' is selected by a playbook and has no evaluator. Wire it, or declare it in "
                "UNIMPLEMENTED_CHECKS with what it needs — an undeclared gap is how the whole lender "
                "family stayed broken while looking finished (ADR-0050)."
            )


@pytest.mark.parametrize("models", MODELS, ids=lambda m: m[0].value if m else "UNIVERSAL")
def test_a_suppressed_check_is_reported_as_not_applicable(models):
    """Suppression must be VISIBLE — ADR-0002's whole point is that a check invalid for a model is
    excluded on the record, not silently absent."""
    playbook, evaluation = _evaluate(models)
    for check in playbook.suppressed:
        record = evaluation.record(check)
        assert record is not None and record.outcome.value == "NOT_APPLICABLE"
        assert record.reason.strip(), f"{check}: a suppression must say why"


def test_the_declared_gaps_are_real_and_specific():
    """A stale entry would mask a check that has since been wired, so the registry is checked both ways."""
    selectable = {c for entry in PLAYBOOKS.values()
                  for c in (*entry.get("applies", ()), *entry.get("suppress", ()))}
    for check, need in UNIMPLEMENTED_CHECKS.items():
        assert check in selectable, f"{check} is declared unimplemented but no playbook selects it"
        assert len(need) > 40, f"{check}: say what it actually needs, specifically enough to act on"

    wired = set()
    for models in MODELS:
        playbook, evaluation = _evaluate(models)
        for check in playbook.applies:
            record = evaluation.record(check)
            if record is not None and NOT_IMPLEMENTED_PREFIX not in record.reason:
                wired.add(check)
    assert not (wired & set(UNIMPLEMENTED_CHECKS)), (
        f"declared unimplemented but actually wired: {sorted(wired & set(UNIMPLEMENTED_CHECKS))} — "
        "remove the entry now that it is built"
    )


def test_the_lender_family_is_wired_which_is_why_this_file_exists():
    """The regression that motivated the whole test: before ADR-0050 every one of these was unwired."""
    _, evaluation = _evaluate([BusinessModel.LENDER])
    for check in ("provision_book_divergent", "reserve_suppression", "gnpa_drift",
                  "provision_coverage_low", "restructured_book_high", "gain_on_sale_reliant"):
        record = evaluation.record(check)
        assert NOT_IMPLEMENTED_PREFIX not in record.reason, f"{check} regressed to unwired"
        assert record.reason.strip(), f"{check}: an UNAVAILABLE must name what it needs"


def test_interest_income_backfills_from_the_store_for_the_cash_reality_test():
    """ADR-0055 addendum: the 'is the cash real' test's other half. Interest received (investing
    section) is filled from the SAME period as the cash balance it will be divided by."""
    from datetime import date

    from firm.core.facts.store import Document, FactStore
    from firm.core.pipeline import derive as D
    from firm.core.pipeline.checks import ExternalInputs, backfill_external_inputs

    store = FactStore(":memory:")
    pub = date(2018, 8, 31)
    store.add_document(Document(doc_id="AR", source_url="u", sha256="", published_at=pub,
                                fetched_at=pub, grade="A", extractor_version="llm-read@1.0.0+verified"))
    for metric, value in ((D.CASH, 43.23), (D.INTEREST_INCOME, 4.66)):
        store.add_fact(fact_id=f"AR:{metric}:FY18", doc_id="AR", ticker="T", metric=metric,
                       period="FY18", value=value, unit="INR_cr", locator="p.137")
    facts = D.load_company_facts(store, "T", date(2018, 12, 31))
    ext = backfill_external_inputs(ExternalInputs(), facts)
    assert ext.cash == 43.23 and ext.interest_income == 4.66
    assert f"AR:{D.INTEREST_INCOME}:FY18" in ext.fact_ids["cash_interest_inconsistent"]
