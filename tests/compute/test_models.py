"""Tests for business-model detection + playbook selection (ADR-0017).

Uses the REAL config (`config/forensic_playbooks.yaml`) so the thresholds under test are the shipped
thresholds, and real company shapes so adaptation is proven, not asserted.
"""

import pytest

from firm.core.compute.models import (
    BusinessModel,
    StatementShape,
    build_playbook,
    detect_models,
)
from firm.core.config import model_detection_thresholds, model_playbooks

T = model_detection_thresholds()
PB = model_playbooks()


# ---- detection ----------------------------------------------------------------------------------
def test_detects_lender_from_loan_book():
    # CreditAccess-like NBFC-MFI: loan book dominates the balance sheet
    shape = StatementShape(loan_book_to_assets=0.87, interest_income_to_revenue=0.92)
    assert detect_models(shape, T) == [BusinessModel.LENDER]


def test_detects_bank_only_when_deposit_funded():
    lender = StatementShape(loan_book_to_assets=0.70, deposits_to_liabilities=0.10)
    assert detect_models(lender, T) == [BusinessModel.LENDER]
    bank = StatementShape(loan_book_to_assets=0.70, deposits_to_liabilities=0.65)
    assert detect_models(bank, T) == [BusinessModel.LENDER, BusinessModel.BANK]


def test_detects_lender_by_interest_income_even_with_small_book():
    # the Carvana lesson: calls itself a dealer, earns like a lender
    shape = StatementShape(loan_book_to_assets=0.05, interest_income_to_revenue=0.60)
    assert BusinessModel.LENDER in detect_models(shape, T)


def test_detects_manufacturer():
    # Alkyl-Amines-like: inventory + heavy plant
    shape = StatementShape(inventory_to_assets=0.12, ppe_to_assets=0.53, gross_margin=0.35)
    assert detect_models(shape, T) == [BusinessModel.MANUFACTURER]


def test_detects_trader_signature():
    # high turnover on near-zero margin -> gross-vs-net / circular-trading signature
    shape = StatementShape(gross_margin=0.02, revenue_to_assets=4.0)
    assert detect_models(shape, T) == [BusinessModel.TRADER]


def test_undisclosed_gross_margin_never_reads_as_zero():
    # gross_margin=None means 'not disclosed' -> must NOT be classified a trader
    shape = StatementShape(gross_margin=None, revenue_to_assets=4.0)
    assert BusinessModel.TRADER not in detect_models(shape, T)


def test_detects_epc_and_services_and_real_estate():
    epc = StatementShape(contract_assets_to_assets=0.22)
    assert BusinessModel.EPC_INFRA in detect_models(epc, T)

    it = StatementShape(employee_cost_to_revenue=0.55, inventory_to_assets=0.0, ppe_to_assets=0.10)
    assert BusinessModel.SERVICES_IT in detect_models(it, T)

    re_co = StatementShape(inventory_to_assets=0.55, customer_advances_to_liabilities=0.30)
    assert BusinessModel.REAL_ESTATE in detect_models(re_co, T)


def test_conglomerate_gets_multiple_tags():
    # auto manufacturer with a captive NBFC -> BOTH playbooks, never a forced single label
    shape = StatementShape(
        loan_book_to_assets=0.35, inventory_to_assets=0.10, ppe_to_assets=0.30, gross_margin=0.25,
    )
    tags = detect_models(shape, T)
    assert BusinessModel.LENDER in tags and BusinessModel.MANUFACTURER in tags


def test_no_match_returns_empty_so_caller_falls_back_to_universal():
    assert detect_models(StatementShape(), T) == []


# ---- playbook resolution ------------------------------------------------------------------------
def test_universal_playbook_is_the_floor_for_unclassified():
    pb = build_playbook([], PB)
    assert pb.models == ()
    assert pb.runs("cumulative_cfo_pat") and pb.runs("disclosure_gap")
    assert not pb.runs("gnpa_drift")               # lender-only check must not run


def test_lender_playbook_suppresses_invalid_checks():
    pb = build_playbook([BusinessModel.LENDER], PB)
    assert pb.runs("gain_on_sale_reliant") and pb.runs("provision_book_divergent")
    # ADR-0002/0012: these are invalid for a lender and must be suppressed
    for invalid in ("beneish_manipulator", "receivables_divergent", "inventory_divergent",
                    "high_accruals", "ageing_cwip"):
        assert not pb.runs(invalid), invalid
    assert pb.runs("cumulative_cfo_pat")           # universal floor still applies


def test_manufacturer_playbook_runs_the_stock_flow_checks():
    pb = build_playbook([BusinessModel.MANUFACTURER], PB)
    assert pb.runs("receivables_divergent") and pb.runs("inventory_divergent")
    assert pb.runs("beneish_manipulator") and pb.runs("ageing_cwip")
    assert not pb.runs("gnpa_drift")


def test_suppression_wins_across_unioned_models():
    # A conglomerate that is BOTH manufacturer (wants Beneish) and lender (suppresses it):
    # suppression must win, so an invalid model never fires on the lending arm.
    pb = build_playbook([BusinessModel.MANUFACTURER, BusinessModel.LENDER], PB)
    assert not pb.runs("beneish_manipulator")
    assert "beneish_manipulator" in pb.suppressed
    assert pb.runs("gain_on_sale_reliant")         # lender checks still active


def test_priority_notes_are_unioned_in_order():
    pb = build_playbook([BusinessModel.MANUFACTURER], PB)
    # universal notes first, then model-specific, no duplicates
    assert pb.priority_notes[0] == "related_party"
    assert "ppe_cwip" in pb.priority_notes and "inventory" in pb.priority_notes
    assert len(pb.priority_notes) == len(set(pb.priority_notes))


def test_unknown_model_key_in_config_is_ignored_gracefully():
    pb = build_playbook([BusinessModel.TRADER], {"UNIVERSAL": {"applies": ["cfo_pat"]}})
    assert pb.runs("cfo_pat") and pb.applies == ("cfo_pat",)


def test_trader_playbook_runs_revenue_inflation():
    pb = build_playbook([BusinessModel.TRADER], PB)
    assert pb.runs("revenue_inflation")


@pytest.mark.parametrize("model", list(BusinessModel))
def test_every_model_has_a_config_playbook(model):
    # guards against a model enum being added without its playbook (silent no-op adaptation)
    assert model.value in PB, f"missing playbook for {model.value}"


def test_every_playbook_check_is_a_real_forensic_signal():
    """A playbook naming a check that no signal implements would silently never fire — the worst kind
    of bug in a fraud detector (the report would claim a check ran when nothing was evaluated)."""
    from firm.core.compute.quality import ForensicMetrics

    signals = set(ForensicMetrics.__dataclass_fields__)
    # metric-valued fields carry values, not booleans; the boolean flags are the check names.
    value_fields = {"cfo_pat", "cumulative_cfo_pat", "accrual_ratio", "beneish_m"}
    # screen flag names that differ from their metric field name
    aliases = {
        "cumulative_cfo_pat": "cumulative_cfo_pat_low",
        "cfo_pat": "cfo_pat_low",
        "accrual_ratio": "high_accruals",
        "beneish_m": "beneish_manipulator",
        "cash_interest_inconsistent": "cash_interest_inconsistent",
    }
    # Checks that RUN and are published but can never raise a screen flag, so they correctly have no
    # `ForensicMetrics` field. Listing them here is the point: the invariant this test protects is "no
    # check is silently unimplemented", and a check that is deliberately non-accusatory has to say so
    # somewhere. `ageing_reconciliation` compares a Schedule III schedule against the statement line it
    # ages; a mismatch is far likelier to be our column reader than the filing, so it reports
    # UNAVAILABLE naming an extraction fault and never a finding against the company (ADR-0039).
    non_flagging = {"ageing_reconciliation"}
    known = (signals - value_fields) | set(aliases.values()) | value_fields | non_flagging

    referenced: set[str] = set()
    for entry in PB.values():
        referenced |= set(entry.get("applies", ()))
        referenced |= set(entry.get("suppress", ()))

    unknown = referenced - known
    assert unknown == set(), f"playbooks reference non-existent checks: {sorted(unknown)}"

    # ...and a non-flagging check must still have a real evaluator, or it lands in the catch-all branch
    # of `evaluate_checks` and publishes "no evaluator wired" while looking like a configured check.
    from pathlib import Path

    evaluator = Path("src/firm/core/pipeline/checks.py").read_text()
    for check in non_flagging:
        assert f'check == "{check}"' in evaluator, f"{check} is in a playbook with no evaluator branch"
