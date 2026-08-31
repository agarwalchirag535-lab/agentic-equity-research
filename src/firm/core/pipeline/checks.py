"""Evaluate the resolved playbook check-by-check into auditable `CheckRecord`s (Phase 2, ADR-0021).

The bug this module exists to prevent: `ForensicMetrics` carries booleans that default to `False`, so
"the check ran and the company is clean" and "the check never ran because the input was not disclosed"
were the same value. In a fraud detector that is the worst possible ambiguity — and the published
Verified-Clean Checklist (ADR-0016) would be asserting a pass that never happened.

So every check named by the playbook is evaluated **explicitly** into exactly one of four outcomes:

* `PASS` — ran, with the value and the threshold it was compared against in `detail`;
* `FLAG` — ran and fired, with the same numbers shown;
* `UNAVAILABLE` — the inputs are not disclosed, with the missing input metrics named in `reason`
  (owner directive 2: missing data is a signal, and it is *this* record that makes it visible);
* `NOT_APPLICABLE` — suppressed by the business-model playbook, with the reason naming the models
  (ADR-0002/0017 — Beneish on a bank must be visibly excluded, not quietly skipped).

The boolean `ForensicMetrics` handed to `quality.forensic_screen` is then built **only from checks that
actually ran**, so the Gate-B verdict cannot rest on an absent input. Deterministic, offline, and every
threshold is passed in from config (Law 1, CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from firm.core.compute import quality
from firm.core.compute.models import Playbook
from firm.core.pipeline import derive as D
from firm.core.pipeline.derive import CompanyFacts, DerivedSet
from firm.schemas.report import CheckOutcome, CheckRecord

#: playbook check name -> the `ForensicMetrics` field that carries it into `forensic_screen`.
#: Four checks are value-carrying (the screen compares them to a threshold itself); the rest are
#: booleans this module decides. Mirrors the guard in tests/compute/test_models.py.
CHECK_TO_FIELD: Mapping[str, str] = {
    "cumulative_cfo_pat": "cumulative_cfo_pat",
    "cfo_pat": "cfo_pat",
    "high_accruals": "accrual_ratio",
    "beneish_manipulator": "beneish_m",
}

#: What a lender check needs that the FACE of the statements does not carry. Named individually so a
#: report distinguishes "we cannot read this yet" from "the company did not disclose it" — the two are
#: different findings and only one of them is about the company.
_LENDER_NOTE_INPUTS: Mapping[str, str] = {
    "gnpa_drift": "gross NPA ratio for two consecutive years (asset-quality note / RBI disclosures, not "
                  "the face of the statements)",
    "provision_coverage_low": "impairment allowance and gross NPA amount (asset-quality note)",
    "restructured_book_high": "restructured advances and gross advances (asset-quality note)",
    "gain_on_sale_reliant": "gain on derecognition / assignment income broken out (revenue note) — a "
                            "lender that does not sell loans has none, which is a different answer",
    "held_for_sale_no_reserve": "loans classified held-for-sale and their reserve treatment "
                                "(classification note)",
}

#: The name `forensic_screen` gives a fired check, where it differs from the playbook name.
CHECK_TO_FLAG: Mapping[str, str] = {
    "cumulative_cfo_pat": "cumulative_cfo_pat_low",
    "cfo_pat": "cfo_pat_low",
}


@dataclass(frozen=True)
class ExternalInputs:
    """Facts that live in the annual report rather than in a summary financials feed.

    Everything here is optional and defaults to "not supplied", which produces `UNAVAILABLE` rather than
    a pass. That is deliberate: a screener-only run must not be able to claim it checked the notes.
    `notes_*` come from the notes-walker (`adapters/india/notes.py`); the rest from the AR tables.
    """

    receivables: tuple[float, float] | None = None      # (current, prior)
    inventory: tuple[float, float] | None = None
    revenue: tuple[float, float] | None = None
    cash: float | None = None
    interest_income: float | None = None
    promoter_loans: tuple[float, float] | None = None   # (loans to promoters/KMP, total advances)
    #: From the Ind AS 24 note body (ADR-0027), used when the Schedule III row is absent. Tri-state on
    #: purpose: False means the note WAS read and disclosed no lending or guarantees to promoters — a real
    #: governance finding — while None means it could not be read and nothing may be concluded.
    promoter_lending_disclosed: bool | None = None
    related_party_categories: tuple[str, ...] = ()
    kmp_remuneration_cr: float | None = None
    gross_margin: float | None = None
    disclosure_gaps: tuple[str, ...] = ()
    disclosure_scanned: bool = False
    source_locators: Mapping[str, str] | None = None    # check name -> "AR p.12 l.4"
    fact_ids: Mapping[str, tuple[str, ...]] | None = None

    def locator(self, check: str) -> str:
        return (self.source_locators or {}).get(check, "")

    def ids(self, check: str) -> tuple[str, ...]:
        return (self.fact_ids or {}).get(check, ())


@dataclass(frozen=True)
class CheckEvaluation:
    """The checklist records plus the screen inputs derived from them, kept together on purpose.

    `metrics` is built only from records that ran — so the Gate-B verdict and the published checklist can
    never disagree about what was evaluated.
    """

    records: tuple[CheckRecord, ...]
    metrics: quality.ForensicMetrics
    expected: tuple[str, ...]

    def record(self, name: str) -> CheckRecord | None:
        return next((r for r in self.records if r.name == name), None)

    def outcome(self, name: str) -> CheckOutcome | None:
        r = self.record(name)
        return None if r is None else r.outcome

    @property
    def unavailable_share(self) -> float:
        """Share of *applicable* checks whose inputs were not disclosed. Drives the honest verdict."""
        applicable = [r for r in self.records if r.name in self.expected]
        if not applicable:
            return 1.0
        return sum(r.outcome is CheckOutcome.UNAVAILABLE for r in applicable) / len(applicable)


class _Recorder:
    def __init__(self, playbook: Playbook, grades: Mapping[str, str] | None = None) -> None:
        self.playbook = playbook
        self.records: list[CheckRecord] = []
        self.fired: set[str] = set()
        self.values: dict[str, float] = {}
        #: fact_id -> grade, so a record can report the provenance SPAN of what it consumed.
        self.grades = dict(grades or {})

    def _grade_note(self, fact_ids: Sequence[str]) -> str:
        """"(grades: A)" or "(grades: A+B — mixed provenance)" for the facts a check consumed.

        MIXED-GRADE ARITHMETIC (ADR-0028). `cash_debt_paradox` divides cash read from the audited filing
        (grade A) by total assets from the screener snapshot (grade B). The ratio is then reported as though
        it were one measurement, and Law 2's provenance chain silently launders the weaker source: a reader
        sees a filing-backed check and cannot tell that half its denominator came from an aggregator.
        Surfacing beats refusing here — refusing would disable the cash checks entirely until the AR yields
        a total-assets row, which trades a visible weakness for an invisible gap — but it must be VISIBLE,
        and a derived ratio must never look better-sourced than its worst input (the rule ADR-0021 already
        applies to `Derivation.citation`).
        """
        seen = sorted({self.grades[f] for f in fact_ids if f in self.grades})
        if not seen:
            return ""
        if len(seen) == 1:
            return f" (grade {seen[0]})"
        return f" (grades {'+'.join(seen)} — mixed provenance, weakest is {seen[-1]})"

    def unavailable(self, check: str, missing: Sequence[str]) -> None:
        self.records.append(CheckRecord(
            name=check, outcome=CheckOutcome.UNAVAILABLE,
            reason="inputs not disclosed in the sources read as-of this run: " + ", ".join(missing),
        ))

    def ran(self, check: str, flagged: bool, detail: str, fact_ids: Sequence[str]) -> None:
        detail = f"{detail}{self._grade_note(fact_ids)}"
        self.records.append(CheckRecord(
            name=check,
            outcome=CheckOutcome.FLAG if flagged else CheckOutcome.PASS,
            detail=detail,
            # Order-preserving dedupe: the same fact legitimately feeds several terms of one formula, but
            # a reader should see each source once.
            fact_ids=list(dict.fromkeys(fact_ids)),
        ))
        if flagged:
            self.fired.add(check)

    def value_check(self, check: str, value: float, detail: str, fact_ids: Sequence[str],
                    flagged: bool) -> None:
        """A check whose *value* also travels to `forensic_screen` (it owns the comparison)."""
        self.values[check] = value
        self.ran(check, flagged, detail, fact_ids)


def _consecutive_pair(facts: CompanyFacts, metric: str):
    """(current, prior) facts for the two most recent CONSECUTIVE years carrying the metric, or None.
    Non-adjacent years are refused: a 'growth' spanning a gap is not the year-on-year divergence the
    stock-flow checks are calibrated for."""
    usable = [p for p in facts.periods if facts.fact(metric, p) is not None]
    if len(usable) < 2 or int(usable[-1][2:]) - int(usable[-2][2:]) != 1:
        return None
    return facts.fact(metric, usable[-1]), facts.fact(metric, usable[-2])


def backfill_external_inputs(ext: ExternalInputs, facts: CompanyFacts) -> ExternalInputs:
    """Fill store-resolvable inputs the filing walk did not supply.

    Found on PC Jeweller (ADR-0046): the verified reading landed five years of audited receivables,
    inventory, revenue and cash in the fact store, and the stock-flow checks still reported UNAVAILABLE —
    they were written to read only the walked filing's rows. A check must not go hungry while its inputs
    sit resolved and point-in-time-filtered in the store. Walk-supplied values always win (they carry
    page locators); only a None field is ever filled, and the facts used are added to the check's
    citation ids so the record still names its evidence.
    """
    updates: dict[str, Any] = {}
    ids: dict[str, tuple[str, ...]] = dict(ext.fact_ids or {})
    got: dict[str, tuple] = {}
    for field_name, metric in (("receivables", D.RECEIVABLES), ("inventory", D.INVENTORY),
                               ("revenue", D.SALES)):
        if getattr(ext, field_name) is None and (pair := _consecutive_pair(facts, metric)) is not None:
            got[field_name] = pair
            updates[field_name] = (pair[0].value, pair[1].value)
    cash_periods = [p for p in facts.periods if facts.fact(D.CASH, p) is not None]
    if ext.cash is None and cash_periods:
        cash_fact = facts.fact(D.CASH, cash_periods[-1])
        updates["cash"] = cash_fact.value
        got["cash"] = (cash_fact,)
    for check, needed in (("receivables_divergent", ("receivables", "revenue")),
                          ("inventory_divergent", ("inventory", "revenue")),
                          ("revenue_inflation", ("revenue",)),
                          ("cash_debt_paradox", ("cash",)),
                          ("cash_interest_inconsistent", ("cash",))):
        new_ids = tuple(f.fact_id for n in needed for f in got.get(n, ()))
        if new_ids:
            ids[check] = tuple(dict.fromkeys((*ids.get(check, ()), *new_ids)))
    if not updates:
        return ext
    return replace(ext, fact_ids=ids, **updates)


def evaluate_checks(
    playbook: Playbook,
    derived: DerivedSet,
    facts: CompanyFacts,
    *,
    forensic: Mapping[str, Any],
    universal: Mapping[str, float],
    model_specific: Mapping[str, float],
    external: ExternalInputs | None = None,
    check_inputs: Mapping[str, float] | None = None,
    lender: Mapping[str, float] | None = None,
) -> CheckEvaluation:
    """Evaluate every check the playbook selects, and mark every suppressed check NOT_APPLICABLE.

    `forensic` / `universal` / `model_specific` / `check_inputs` are the config threshold blocks
    (`config/thresholds.yaml`). `check_inputs` carries the ADR-0025 plausibility preconditions: a check whose
    inputs are degenerate reports UNAVAILABLE rather than accusing the company.
    Checks the playbook does not name at all are simply not in the report — that is what a playbook is
    for; the *suppressed* ones are recorded, because a suppression is a decision worth publishing.
    """
    if check_inputs is None:
        from firm.core.config import check_input_thresholds

        check_inputs = check_input_thresholds()
    if lender is None:
        from firm.core.config import originate_to_sell_thresholds

        lender = originate_to_sell_thresholds()
    ext = backfill_external_inputs(external or ExternalInputs(), facts)
    # Grades of every fact in scope, so each record can report the provenance span it rests on (ADR-0028).
    grades = {
        fact.fact_id: fact.grade
        for metric in facts.series for fact in facts.series[metric].values()
    }
    grades.update({f"derived:{name}": d.citation.grade.value for name, d in derived.values.items()})
    r = _Recorder(playbook, grades)

    def missing_for(*metrics: str) -> tuple[str, ...]:
        return tuple(m for metric in metrics for m in derived.missing.get(metric, (metric,)))

    for check in playbook.applies:
        # ---- cash-reality: earnings converting to cash ------------------------------------------
        if check == "cumulative_cfo_pat":
            d = derived.get("cum_cfo_pat")
            if d is None:
                r.unavailable(check, missing_for("cum_cfo_pat"))
            else:
                floor = forensic["cumulative_cfo_pat_min"]
                r.value_check(check, d.value,
                              f"ΣCFO/ΣPAT {d.value:.2f} vs floor {floor:.2f} ({d.formula})",
                              d.fact_ids, flagged=d.value < floor)

        elif check == "cfo_pat":
            d = derived.get("cfo_pat_latest")
            if d is None:
                r.unavailable(check, missing_for("cfo_pat_latest"))
            else:
                floor = forensic["cfo_pat_min"]
                r.value_check(check, d.value,
                              f"CFO/PAT {d.value:.2f} vs floor {floor:.2f} ({d.formula})",
                              d.fact_ids, flagged=d.value < floor)

        elif check == "high_accruals":
            d = derived.get("accrual_ratio_latest")
            if d is None:
                r.unavailable(check, missing_for("accrual_ratio_latest"))
            else:
                limit = forensic["sloan_accrual_flag"]
                r.value_check(check, d.value,
                              f"accruals {d.value:+.3f} vs limit ±{limit:.2f} ({d.formula})",
                              d.fact_ids, flagged=abs(d.value) > limit)

        elif check == "beneish_manipulator":
            # Needs the 8-index input set (COGS, receivables, current assets, ...) — a summary feed
            # cannot supply it, and a partial M-score is worse than none (ADR-0003 caution).
            r.unavailable(check, ("Beneish 8-index inputs (COGS, receivables, current assets, PPE, SGA)",))

        elif check == "cash_interest_inconsistent":
            # PREFER THE DERIVED YIELD. `cash_yield_latest` (ADR-0037) divides the interest income the
            # cash-flow statement reconciles out by the AVERAGE of the opening and closing cash AND other
            # bank balances. Both refinements matter: interest accrues across the year rather than on the
            # closing snapshot, and a company that holds most of its money in term deposits reports them
            # under "Other Bank Balances", so measuring the yield against cash alone overstates it — here
            # by more than double (16.7% against a true 7.8%), which is the difference between a check
            # that would wave through a fabricated balance and one that would not.
            yield_on_cash = derived.get("cash_yield_latest")
            if yield_on_cash is not None:
                floor = forensic["cash_yield_floor_ratio"] * forensic["risk_free_rate"]
                r.ran(check, yield_on_cash.value < floor,
                      f"implied yield on cash and bank balances {yield_on_cash.value:.2%} vs floor "
                      f"{floor:.2%} ({yield_on_cash.formula})", yield_on_cash.fact_ids)
            elif ext.cash is None or ext.interest_income is None:
                absent = [name for name, present in (
                    (D.CASH, ext.cash is not None),
                    ("interest income earned on cash (not broken out of other income)",
                     ext.interest_income is not None),
                ) if not present]
                r.unavailable(check, absent)
            else:
                implied, flagged = quality.cash_interest_consistency(
                    ext.interest_income, ext.cash,
                    forensic["risk_free_rate"], forensic["cash_yield_floor_ratio"])
                r.ran(check, flagged,
                      f"implied yield on cash {implied:.2%} vs floor "
                      f"{forensic['cash_yield_floor_ratio'] * forensic['risk_free_rate']:.2%} "
                      f"({ext.locator(check) or 'AR'})", ext.ids(check))

        elif check == "cash_debt_paradox":
            # The average-balance rate is the better denominator (see `cost_of_debt_average`); the
            # closing-balance one stays as a fallback for a run with no filing behind it.
            cod = derived.get("cost_of_debt_average") or derived.get("cost_of_debt_latest")
            assets = facts.fact(D.TOTAL_ASSETS, derived.last_period or "")
            debt = facts.fact(D.BORROWINGS, derived.last_period or "")
            if ext.cash is None or cod is None or assets is None or debt is None:
                absent: list[str] = []
                if ext.cash is None:
                    absent.append(D.CASH)
                if cod is None:
                    absent.extend(missing_for("cost_of_debt_latest"))
                if assets is None:
                    absent.append(f"{D.TOTAL_ASSETS} {derived.last_period}")
                if debt is None:
                    absent.append(f"{D.BORROWINGS} {derived.last_period}")
                r.unavailable(check, absent)
            elif (impossible := ext.cash / assets.value) > check_inputs["max_cash_to_assets"]:
                # Arithmetically impossible, so this is a unit or extraction fault in OUR pipeline, not a
                # finding about the company. It is reported as unavailable and named as a fault rather than
                # flagged — this exact ratio read 496.6% when a lakh cash figure met a crore asset base.
                r.unavailable(check, [
                    f"cash/assets computes to {impossible:.1%}, which is impossible — the inputs are on "
                    f"different scales or a row was misread, so this check cannot run"
                ])
            elif (debt_share := debt.value / assets.value) < check_inputs["min_debt_to_assets"]:
                # Immaterial borrowings make the implied cost of debt an artefact of rounding: ALKYLAMINE's
                # Rs 1cr of debt against Rs 1cr of interest produced "100%". A paradox check needs real debt
                # for the paradox to exist at all.
                r.unavailable(check, [
                    f"borrowings are {debt_share:.2%} of assets (floor "
                    f"{check_inputs['min_debt_to_assets']:.0%}), so the implied cost of debt "
                    f"({cod.value:.0%}) is an artefact of rounding rather than a rate the company pays"
                ])
            else:
                flagged = quality.cash_debt_paradox(
                    ext.cash, assets.value, debt.value, cod.value,
                    forensic["large_cash_to_assets"], forensic["high_cost_debt_rate"])
                r.ran(check, flagged,
                      f"cash/assets {ext.cash / assets.value:.1%} at cost of debt {cod.value:.1%} "
                      f"(paradox above {forensic['large_cash_to_assets']:.0%} and "
                      f"{forensic['high_cost_debt_rate']:.0%})",
                      (*ext.ids(check), assets.fact_id, debt.fact_id))

        elif check == "ageing_cwip":
            share = derived.get("cwip_share_latest")
            if share is None:
                r.unavailable(check, missing_for("cwip_share_latest"))
            else:
                years, used = D.cwip_persistence_years(facts, forensic["ageing_cwip_to_assets"])
                assets = facts.fact(D.TOTAL_ASSETS, derived.last_period or "")
                flagged = quality.ageing_cwip_flag(
                    share.value * assets.value, assets.value, years,
                    forensic["ageing_cwip_to_assets"], forensic["ageing_cwip_years"])
                r.ran(check, flagged,
                      f"CWIP {share.value:.1%} of assets, large for {years:.0f}y "
                      f"(flags above {forensic['ageing_cwip_to_assets']:.0%} for "
                      f"{forensic['ageing_cwip_years']}y)",
                      (*share.fact_ids, *(f.fact_id for f in used)))

        # ---- universal SPEC §5 tells -------------------------------------------------------------
        elif check == "other_income_heavy":
            d = derived.get("other_income_share")
            if d is None:
                r.unavailable(check, missing_for("other_income_share"))
            else:
                limit = universal["other_income_pbt_max"]
                other_income, pbt = d.inputs[0].value, d.inputs[1].value
                share, flagged = quality.other_income_share(other_income, pbt, limit)
                r.ran(check, flagged,
                      f"other income {share:.1%} of PBT vs limit {limit:.0%} ({d.formula})",
                      d.fact_ids)

        elif check in ("receivables_divergent", "inventory_divergent"):
            stock = ext.receivables if check == "receivables_divergent" else ext.inventory
            gap_key = ("receivables_flow_gap" if check == "receivables_divergent"
                       else "inventory_flow_gap")
            label = "receivables" if check == "receivables_divergent" else "inventory"
            if stock is None or ext.revenue is None:
                r.unavailable(check, (f"{label} (current, prior)", "revenue (current, prior)"))
            else:
                sg, fg, flagged = quality.stock_flow_divergence(
                    stock[0], stock[1], ext.revenue[0], ext.revenue[1], universal[gap_key])
                r.ran(check, flagged,
                      f"{label} {sg:+.1%} vs revenue {fg:+.1%}, gap {sg - fg:+.1%} vs limit "
                      f"{universal[gap_key]:.0%} ({ext.locator(check) or 'AR'})", ext.ids(check))

        elif check == "revenue_inflation":
            rev_cagr = derived.get("revenue_cagr")
            if ext.gross_margin is None or ext.revenue is None:
                r.unavailable(check, ("gross margin (COGS not broken out)",
                                      *(() if ext.revenue else ("revenue (current, prior)",))))
            else:
                growth = ext.revenue[0] / ext.revenue[1] - 1.0 if ext.revenue[1] else 0.0
                flagged = quality.revenue_inflation_tell(
                    growth, ext.gross_margin,
                    universal["revenue_inflation_min_growth"], universal["revenue_inflation_max_margin"])
                r.ran(check, flagged,
                      f"revenue {growth:+.1%} on gross margin {ext.gross_margin:.1%} "
                      f"(flags above {universal['revenue_inflation_min_growth']:.0%} growth at or below "
                      f"{universal['revenue_inflation_max_margin']:.0%} margin)",
                      (*ext.ids(check), *(rev_cagr.fact_ids if rev_cagr else ())))

        # ---- disclosure + model-specific ---------------------------------------------------------
        elif check == "disclosure_gap":
            if not ext.disclosure_scanned:
                r.unavailable(check, ("annual-report text (no filing was walked in this run)",))
            else:
                r.ran(check, bool(ext.disclosure_gaps),
                      ("mandated disclosures absent: " + ", ".join(ext.disclosure_gaps))
                      if ext.disclosure_gaps
                      else "every mandated Schedule III / forensic section located in the filing",
                      ext.ids(check))

        elif check == "promoter_lending":
            if ext.promoter_loans is None and ext.promoter_lending_disclosed is not None:
                # The Schedule III row is absent but the Ind AS 24 note was read, and it is the better
                # source anyway: Schedule III reports a balance, the note reports the transactions. A note
                # listing only director remuneration is the strongest statement a promoter group can make.
                disclosed = ext.promoter_lending_disclosed
                categories = ", ".join(ext.related_party_categories) or "none"
                pay = (f"; KMP remuneration ₹{ext.kmp_remuneration_cr:,.2f}cr"
                       if ext.kmp_remuneration_cr is not None else "")
                r.ran(check, disclosed,
                      f"related-party note read ({ext.locator(check) or 'AR'}): categories disclosed = "
                      f"{categories}{pay}", ext.ids(check))
            elif ext.promoter_loans is None:
                r.unavailable(check, ("loans and advances to promoters/KMP (Schedule III row)",))
            else:
                share, flagged = quality.promoter_loan_share(
                    ext.promoter_loans[0], ext.promoter_loans[1],
                    model_specific["promoter_loan_max_share"])
                r.ran(check, flagged,
                      f"loans to promoters/KMP {share:.1%} of advances vs limit "
                      f"{model_specific['promoter_loan_max_share']:.0%}", ext.ids(check))

        # ---- lender checks (ADR-0002/0012; first wired to real filings by ADR-0050) ---------------
        # Two of the seven are computable from the FACE of a lender's statements — the credit-cost line
        # and the loan book are both printed there. The other five need note-level disclosure (asset
        # quality, ECL stages, assignment income), so they name what they need rather than reporting the
        # generic "no evaluator wired": a reader must be able to tell a check we cannot run from a
        # disclosure the company did not make.
        elif check in ("provision_book_divergent", "reserve_suppression"):
            impairment = _consecutive_pair(facts, D.IMPAIRMENT)
            book = _consecutive_pair(facts, D.LOAN_BOOK)
            if impairment is None or book is None:
                r.unavailable(check, tuple(
                    name for name, got in ((f"{D.IMPAIRMENT} (two consecutive years)", impairment),
                                           (f"{D.LOAN_BOOK} (two consecutive years)", book))
                    if got is None))
            elif check == "provision_book_divergent":
                pg, bg, flagged = quality.provision_book_divergence(
                    impairment[0].value, impairment[1].value, book[0].value, book[1].value,
                    lender["provision_book_divergence_max"])
                r.ran(check, flagged,
                      f"impairment {pg:+.1%} vs loan book {bg:+.1%}, gap {abs(pg - bg):.2f} vs limit "
                      f"{lender['provision_book_divergence_max']:.2f} "
                      f"({impairment[1].period}->{impairment[0].period})",
                      tuple(f.fact_id for f in (*impairment, *book)))
            else:
                rate_now = impairment[0].value / book[0].value if book[0].value else 0.0
                rate_before = impairment[1].value / book[1].value if book[1].value else 0.0
                flagged = quality.reserve_suppression_flag(
                    rate_now, rate_before, lender["reserve_suppression_min_drop"])
                # Direction is the whole point (ADR-0012): reserves RISING is honest recognition of
                # stress, and only a material CUT into a book is the fraud tell.
                r.ran(check, flagged,
                      f"credit cost {rate_before:.2%} -> {rate_now:.2%} of the book "
                      f"({'cut' if rate_now < rate_before else 'raised'}); flags only a cut beyond "
                      f"{lender['reserve_suppression_min_drop']:.2%}",
                      tuple(f.fact_id for f in (*impairment, *book)))

        elif check in ("gnpa_drift", "provision_coverage_low", "restructured_book_high",
                       "gain_on_sale_reliant", "held_for_sale_no_reserve"):
            r.unavailable(check, (_LENDER_NOTE_INPUTS[check],))

        else:
            # A check the playbook selects that this evaluator does not implement must be VISIBLE.
            # Silently dropping it would let the report imply a check ran when nothing was evaluated.
            r.unavailable(check, ((f"no evaluator wired for '{check}' in this run "
                                   "(requires data this pipeline does not yet ingest)"),))

    for check in playbook.suppressed:
        models = ", ".join(m.value for m in playbook.models) or "no detected model"
        r.records.append(CheckRecord(
            name=check, outcome=CheckOutcome.NOT_APPLICABLE,
            reason=f"suppressed by the {models} playbook — the check is invalid for this business "
                   "model (ADR-0002/0017), so a 'pass' would be meaningless",
        ))

    metrics = quality.ForensicMetrics()
    for check, field in CHECK_TO_FIELD.items():
        if check in r.values:
            metrics = replace(metrics, **{field: r.values[check]})
    for check in r.fired:
        if check in CHECK_TO_FIELD:
            continue                       # value checks are flagged by the screen itself
        if check in quality.ForensicMetrics.__dataclass_fields__:
            metrics = replace(metrics, **{check: True})

    return CheckEvaluation(tuple(r.records), metrics, tuple(playbook.applies))
