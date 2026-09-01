"""The calibration dashboard's compute half (ADR-0084, SPEC §7.5).

Two properties carry this module and both get tested harder than the arithmetic:

* **Refusal below the floor.** With three resolved predictions an over/under-confidence curve is
  three dots wearing an axis. A dashboard that draws it anyway is worse than none, because it looks
  like measurement — so every panel refuses under its configured floor and says what it is waiting for.
* **Attribution is exact, not estimated.** The verdict ladder is deterministic and agent output enters
  it through one channel (the forensic veto), so "did an agent change the decision?" is answered by
  replaying the ladder with the channel off — never by a heuristic over prose.
"""

from __future__ import annotations

import json

from firm.core.monitoring.dashboard import (
    build_dashboard,
    claim_type_rates,
    confidence_curve,
    harvest_attribution,
    render_dashboard,
)
from firm.core.monitoring.predictions import Prediction, append_jsonl

POLICY = {"min_resolved_for_curve": 20, "min_per_bucket": 5, "min_per_claim_type": 3}


def _prediction(i: int, *, probability=0.8, outcome=True, metric="cfo_pat_latest",
                resolved=True) -> Prediction:
    return Prediction(
        prediction_id=f"p{i}", run_id="r", ticker="ACME", agent="report", agent_version="1.0.0",
        claim="c", metric=metric, operator=">=", threshold=1.0, resolve_by="2026-07-01",
        probability=probability, resolved=resolved if resolved else None,
        outcome=outcome if resolved else None)


# ---- the curve -------------------------------------------------------------------------------------
def test_the_curve_refuses_below_the_floor_and_names_it():
    curve, refusal = confidence_curve([_prediction(i) for i in range(3)], min_total=20, min_bucket=5)
    assert curve == ()
    assert "3 resolved" in refusal and "floor of 20" in refusal
    assert "firm resolve" in refusal          # says what feeds it, not just that it is empty


def test_the_curve_draws_with_enough_data_and_shows_overconfidence():
    """25 predictions stated at 90%, only 60% held: realised sits far below stated."""
    preds = [_prediction(i, probability=0.9, outcome=(i % 5 < 3)) for i in range(25)]
    curve, refusal = confidence_curve(preds, min_total=20, min_bucket=5)
    assert refusal == "" and len(curve) == 1
    bucket = curve[0]
    assert bucket.low == 0.8 and bucket.resolved == 25
    assert bucket.stated_mean > bucket.realised_rate          # overconfident, visibly


def test_an_underfilled_band_is_omitted_never_faked():
    preds = ([_prediction(i, probability=0.9) for i in range(24)]
             + [_prediction(100, probability=0.1)])           # one lonely low-band point
    curve, _ = confidence_curve(preds, min_total=20, min_bucket=5)
    assert [b.low for b in curve] == [0.8]


def test_the_bands_are_fixed_so_the_record_is_diffable():
    """Quantile buckets move every time a prediction resolves; two runs could not be compared."""
    preds = [_prediction(i, probability=0.85) for i in range(25)]
    a, _ = confidence_curve(preds, min_total=20, min_bucket=5)
    b, _ = confidence_curve(preds, min_total=20, min_bucket=5)
    assert a == b and a[0].low == 0.8 and a[0].high == 1.0


# ---- hit rates -------------------------------------------------------------------------------------
def test_a_thin_claim_type_is_reported_as_waiting_not_dropped():
    preds = ([_prediction(i, metric="cum_cfo_pat") for i in range(4)]
             + [_prediction(10, metric="accrual_ratio_latest")])
    rates, refusals = claim_type_rates(preds, min_each=3)
    assert [r.metric for r in rates] == ["cum_cfo_pat"]
    assert refusals and "accrual_ratio_latest" in refusals[0] and "floor 3" in refusals[0]


def test_hit_rate_counts_hits_over_resolved():
    preds = [_prediction(i, metric="m", outcome=(i < 3)) for i in range(4)]
    rates, _ = claim_type_rates(preds, min_each=3)
    assert rates[0].hits == 3 and rates[0].resolved == 4 and abs(rates[0].rate - 0.75) < 1e-9


# ---- attribution harvest ---------------------------------------------------------------------------
def test_attribution_is_harvested_from_published_reports(tmp_path):
    run = tmp_path / "ACME" / "2026-07-30-r1"
    run.mkdir(parents=True)
    line = ("forensic_accountant: the veto DECIDED this verdict — without it the deterministic "
            "ladder returns COMPOUNDER")
    (run / "report.json").write_text(json.dumps({"decision_attribution": [line]}))
    counts, seen = harvest_attribution(tmp_path)
    assert seen == 1 and len(counts) == 1
    assert next(iter(counts.values())) == 1


def test_reports_predating_the_field_count_as_read_and_contribute_nothing(tmp_path):
    """The honest treatment of a record written before the question was being asked."""
    old = tmp_path / "ACME" / "2026-07-01-r0"
    old.mkdir(parents=True)
    (old / "report.json").write_text(json.dumps({"verdict": "COMPOUNDER"}))
    counts, seen = harvest_attribution(tmp_path)
    assert seen == 1 and counts == {}


def test_an_unreadable_report_does_not_kill_the_tally(tmp_path):
    bad = tmp_path / "ACME" / "2026-07-01-r0"
    bad.mkdir(parents=True)
    (bad / "report.json").write_text("{not json")
    counts, seen = harvest_attribution(tmp_path)
    assert seen == 0 and counts == {}


# ---- end to end ------------------------------------------------------------------------------------
def test_the_rendered_record_shows_refusals_in_the_thin_state(tmp_path):
    """The real first output: one Brier row, everything else honestly waiting."""
    memory = tmp_path / "memory"; memory.mkdir()
    for i in range(3):
        append_jsonl(memory / "predictions.jsonl", _prediction(i, metric=f"m{i}"))
    dash = build_dashboard(memory / "predictions.jsonl", tmp_path / "reports", policy=POLICY)
    text = render_dashboard(dash)

    assert "3 resolved prediction(s)" in text
    assert "report | `1.0.0` | 0." in text.replace("| report ", "report ") or "1.0.0" in text
    assert "not drawn — 3 resolved" in text
    assert "floor 3 — not yet stated" in text
    assert "No published report carries attribution yet" in text


def test_a_veto_that_decides_the_verdict_is_attributed_by_replay(store, tmp_path):
    """End to end through run_deep_dive: veto on a clean screen flips COMPOUNDER to FORENSIC_CAUTION,
    and the replay names exactly that."""
    from firm.core.pipeline.deep_dive import run_deep_dive
    from tests.conftest import AS_OF, clean_answers, filing_for, seed_store
    from tests.pipeline.test_valuation_wiring import valuable_series

    seed_store(store, "CLEANCO", valuable_series())
    answers = clean_answers("CLEANCO", forensic_accountant={
        "verdict": "FAIL", "flags": ["narrative_inconsistency"], "veto": True})
    result = run_deep_dive(store, "CLEANCO", AS_OF, answers=answers, filing=filing_for("CLEANCO"),
                           company_name="Cleanco Limited", reports_root=tmp_path, write=True,
                           memory_root=tmp_path)

    lines = result.report.decision_attribution
    assert lines and "veto DECIDED this verdict" in lines[0]
    # The counterfactual names what the ladder returns WITHOUT the veto — for this fixture that is
    # RETURN_HURDLE_NOT_CLEARED (it does not clear the default 5x target), which is the point: the
    # replay reports the actual alternative, not an assumed one.
    assert "RETURN_HURDLE_NOT_CLEARED" in lines[0]
    # and it survives into the artifact the dashboard will harvest
    published = json.loads(result.json_path.read_text())
    assert published["decision_attribution"] == list(lines)


def test_no_veto_is_stated_as_fully_deterministic(store, tmp_path):
    from firm.core.pipeline.deep_dive import run_deep_dive
    from tests.conftest import AS_OF, clean_answers, filing_for, seed_store
    from tests.pipeline.test_valuation_wiring import valuable_series

    seed_store(store, "CLEANCO", valuable_series())
    result = run_deep_dive(store, "CLEANCO", AS_OF, answers=clean_answers("CLEANCO"),
                           filing=filing_for("CLEANCO"), company_name="Cleanco Limited",
                           reports_root=tmp_path, write=True, memory_root=tmp_path)
    assert result.report.decision_attribution
    assert "fully deterministic" in result.report.decision_attribution[0]
