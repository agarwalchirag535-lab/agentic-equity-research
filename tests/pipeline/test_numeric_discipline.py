"""Law 1 across the WHOLE roster: no agent authors a number, whatever schema it returns (ADR-0036).

THE BUG THIS PINS DOWN
`_numeric_discipline` iterated a seven-entry dict of field names. Read as an allow-list that was correct;
read as the enforcement of Law 1 it was a hole, because a numeric field absent from the dict was not
refused — it was never examined. Three agents had every numeric field in the dict, so the hole was invisible
until the roster grew to eight and thirteen unexamined numeric fields arrived with it.

The check is now derived from the schema and fails closed, so these tests are about the *mechanism* rather
than about today's field list: a schema that grows a numeric field must break something here.
"""

from __future__ import annotations

import pytest

from firm.core.config import numeric_field_policy
from firm.core.pipeline import derive as D
from firm.core.pipeline.deep_dive import _numeric_discipline, authored_numbers
from firm.schemas.agents import AGENT_OUTPUTS, OwnershipFlowsOutput, UnitEconomicsOutput
from tests.conftest import AS_OF, clean_series, seed_store

_IDENTITY = {"agent": "x", "agent_version": "1.0.0", "ticker": "ACME", "as_of": AS_OF,
             "disconfirming_search": "looked"}


def _derived(store):
    seed_store(store, "ACME", clean_series())
    return D.derive_metrics(D.load_company_facts(store, "ACME", AS_OF))


def _numeric_keys(model, seen=None) -> set[str]:
    """`Model.field` for every numeric leaf reachable from a schema, nested models included.

    Recursion is the point: `ScenarioLine.return_multiple` is a target price wearing a nested model, and a
    scan that only walked an agent's top-level fields would never see it.
    """
    from pydantic import BaseModel

    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)

    keys: set[str] = set()
    for field_name, info in model.model_fields.items():
        annotation = info.annotation
        for candidate in (annotation, *getattr(annotation, "__args__", ())):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                keys |= _numeric_keys(candidate, seen)
        text = str(annotation)
        if ("int" in text or "float" in text) and "bool" not in text:
            keys.add(f"{model.__name__}.{field_name}")
    return keys


def test_every_numeric_field_in_every_agent_schema_is_classified():
    """The fail-closed contract, stated as a test rather than as a comment.

    Adding `payback_years` to a schema and forgetting `config/numeric_fields.yaml` used to mean the field
    was silently unchecked. Now it means this test fails, which is the whole point of the redesign: the
    decision is forced at the moment the field is created, by the person who knows where it comes from.
    """
    policy = numeric_field_policy()
    classified = set(policy["computed"]) | set(policy["judgment"])

    reachable: set[str] = set()
    for schema in AGENT_OUTPUTS.values():
        reachable |= _numeric_keys(schema)
    assert len(reachable) >= 20, "the schema scan found almost nothing — it has stopped scanning"

    unclassified = sorted(reachable - classified)
    assert not unclassified, (
        "numeric fields with no entry in config/numeric_fields.yaml — each is a number an LLM could "
        f"author unchecked: {unclassified}"
    )


def test_an_unclassified_number_is_refused_rather_than_ignored(store):
    """The regression itself: a number in a field nobody thought about must fail, not pass."""
    derived = _derived(store)
    policy = {"computed": {}, "judgment": frozenset()}
    output = OwnershipFlowsOutput(**_IDENTITY, smart_money_score=0.82)

    problems = _numeric_discipline(output, derived, policy)
    assert len(problems) == 1
    assert "smart_money_score" in problems[0]
    assert "not classified" in problems[0]


@pytest.mark.parametrize(
    "field, value",
    [("smart_money_score", 0.82), ("days_to_exit_at_20pct_adv", 41.0)],
)
def test_the_ownership_agent_cannot_invent_its_headline_numbers(store, field, value):
    """Both `OwnershipFlowsOutput` numbers were unexamined under the old dict — neither is derivable."""
    derived = _derived(store)
    output = OwnershipFlowsOutput(**_IDENTITY, **{field: value})
    problems = _numeric_discipline(output, derived)
    assert problems and field in problems[0]


def test_the_unit_economics_schema_no_longer_orders_a_law_1_violation():
    """`units_today` was a REQUIRED int: the contract itself demanded a number no source produces."""
    fields = UnitEconomicsOutput.model_fields
    assert not fields["units_today"].is_required()
    assert not fields["units_plausible_in_7y"].is_required()


def test_a_judgment_number_is_allowed_and_a_financial_one_beside_it_is_not(store):
    """Confidence is the agent's opinion on a scale; a scenario's return multiple is a financial claim.

    They sit in the same schema tree, so the classifier has to separate them by key rather than by type —
    banning both would delete the calibration record Phase 6 scores, and allowing both would let a target
    price in through a nested model.
    """
    from firm.schemas._base import Claim, Confidence, Grade
    from firm.schemas.agents import ScenarioLine, ValuationModelerOutput

    derived = _derived(store)
    claim = Claim(
        text="Cash conversion holds [fact:derived:cum_cfo_pat].", kind="inference",
        confidence=Confidence(value=0.7, evidence_count=3, lowest_grade_relied_on=Grade.B,
                              rationale="two filings agree"),
    )
    assert _numeric_discipline(
        ValuationModelerOutput(**_IDENTITY, inferences=[claim]), derived) == []

    with_scenario = ValuationModelerOutput(
        **_IDENTITY, inferences=[claim],
        scenarios=[ScenarioLine(name="base", probability=0.6, return_multiple=3.2)],
    )
    problems = _numeric_discipline(with_scenario, derived)
    assert len(problems) == 1, problems
    assert "return_multiple" in problems[0] and "probability" not in problems[0]


def test_numbers_are_collected_from_nested_models_with_their_owning_class(store):
    """`authored_numbers` keys by `Model.field` so two agents may reuse a field name without colliding."""
    from firm.schemas.agents import MacroStrategistOutput, SectorScore

    output = MacroStrategistOutput(
        **_IDENTITY, cycle_position="mid",
        sector_scores=[SectorScore(sector="chemicals", tailwind_score=-0.3, horizon_years=5,
                                   falsifier="China capacity restarts")],
    )
    keys = {key for _, key, _ in authored_numbers(output)}
    assert keys == {"SectorScore.tailwind_score", "SectorScore.horizon_years"}
    # both are declared judgment, so a well-formed macro answer passes
    assert _numeric_discipline(output, _derived(store)) == []


def test_a_boolean_is_not_read_as_the_number_one(store):
    """`bool` subclasses `int` in Python, so `veto=True` would arrive as an un-sourced figure `1.0`."""
    from firm.schemas.agents import ForensicAccountantOutput

    output = ForensicAccountantOutput(**_IDENTITY, verdict="HARD_FAIL", flags=["cash"], veto=True)
    assert authored_numbers(output) == []
    assert _numeric_discipline(output, _derived(store)) == []
