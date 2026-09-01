"""The sweep: discovery over the deterministic layer, with nobody silently dropped (ADR-0085).

Three disciplines meet here and each gets its test:

* **Gates decide attention in a sweep — and only Gates A and B decide it.** Gate D (the return
  target) failing is a finding, not an exclusion reason; the first live run cited it as one and the
  render was fixed. Misattributing an exclusion teaches the reader the wrong lesson about a company.
* **Routed, never dropped** (ADR-0008). `route_by_history` was written in Phase 0 for exactly this
  and had no caller until now.
* **The register discipline** (ADR-0061): every company that entered the sweep appears in the output —
  survivors, routed, excluded-with-reason, or not-yet-ingested. A sweep that loses rows is a funnel
  with a hole in it.
"""

from __future__ import annotations

from datetime import date

from firm.core.screen.sweep import render_sweep, sweep_company
from tests.conftest import AS_OF, seed_store
from tests.pipeline.test_valuation_wiring import seed_price, valuable_series


def _row(store, ticker="ACME", series=None, price=1500.0, as_of=AS_OF):
    seed_store(store, ticker, series if series is not None else valuable_series())
    if price is not None:
        seed_price(store, ticker, price, date(2026, 7, 28))
    return sweep_company(store, ticker, as_of)


# ---- one company through the layer -----------------------------------------------------------------
def test_a_priced_clean_company_gets_the_full_deterministic_read(store):
    row = _row(store)
    assert row.empty_reason == ""
    assert row.checks_applicable > 0 and row.checks_ran > 0
    assert row.market_cap_cr is not None
    assert {g.gate.value for g in row.gates} == {"A", "B", "C", "D", "E"}
    assert row.route.pipeline.value == "MAIN"


def test_no_agent_output_is_anywhere_in_a_sweep_row(store):
    """The sweep is affordable because it is deterministic; a row carries nothing an LLM wrote."""
    row = _row(store)
    assert not hasattr(row, "narrative")
    gate_e = next(g for g in row.gates if g.gate.value == "E")
    assert gate_e.passed is None                     # red_team never ran — E cannot be evaluated
    assert "red_team" in gate_e.reason


def test_an_uningested_company_is_a_row_with_a_reason_not_an_error(store):
    row = sweep_company(store, "GHOST", AS_OF)
    assert row.empty_reason and "ingest" in row.empty_reason
    assert row.survives_funnel is False


# ---- who survives ----------------------------------------------------------------------------------
def test_survival_is_gate_a_and_b_only(store):
    row = _row(store)
    by = {g.gate.value: g for g in row.gates}
    expected = bool(by["A"].passed) and bool(by["B"].passed)
    assert row.survives_funnel is expected


def test_an_unpriced_company_does_not_survive_but_is_not_dropped(store):
    """UNAVAILABLE is not PASS at funnel level either: spending the expensive tier on a company whose
    liquidity could not be established is how a funnel stops being one."""
    row = _row(store, price=None)
    by = {g.gate.value: g for g in row.gates}
    assert by["A"].passed is None
    assert row.survives_funnel is False


# ---- the rendered funnel ---------------------------------------------------------------------------
def test_every_company_that_entered_appears_in_the_output(store):
    rows = [_row(store, "GOODCO"), _row(store, "DARKCO", price=None),
            sweep_company(store, "GHOST", AS_OF)]
    page = render_sweep(rows, AS_OF)
    for name in ("GOODCO", "DARKCO", "GHOST"):
        assert name in page, f"{name} vanished from the sweep — the funnel has a hole"


def test_exclusion_reasons_cite_only_the_gates_that_decide(store):
    """Gate D failing is a finding about the return target, not why attention was withheld. The first
    live run cited it as an exclusion reason and taught the wrong lesson about the company."""
    row = _row(store, "DARKCO", price=None)          # excluded because Gate A is unavailable
    page = render_sweep([row], AS_OF)
    excluded = page[page.index("## Excluded"):]
    assert "Gate A" in excluded
    assert "Gate D" not in excluded and "Gate C" not in excluded and "Gate E" not in excluded


def test_the_page_states_that_report_eligibility_is_not_decided_here(store):
    """ADR-0064 at the sweep's front door: the funnel ranks attention, never eligibility."""
    page = render_sweep([_row(store)], AS_OF)
    assert "never decides report eligibility" in page
    assert "deep-dived by name" in page


def test_no_llm_ran_is_stated_on_the_page(store):
    assert "no agent ran and no LLM was called" in render_sweep([_row(store)], AS_OF)
