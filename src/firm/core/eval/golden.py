"""The golden set: cases, and the two independent assertions each one makes (ADR-0061).

`docs/GOLDEN_SET.md` is the design; this is the part of it that is code. Everything here is PURE — cases
in, verdicts out — so the scoring is unit-testable without opening a PDF, and so a change in scoring can
never be confused with a change in extraction.

THE TWO ASSERTIONS, AND WHY THEY MUST STAY APART.

  1. EXTRACTION — every fact a human verified against the filing must be reproduced, to the value and the
     period. A miss is a defect in the readers.
  2. JUDGMENT — the screen verdict must fall inside the band the case pre-registered, and its `must_flag`
     / `must_not_flag` must hold. A miss is a defect in the thresholds or the evaluators.

Collapsing them into one pass/fail is the mistake that makes a golden set useless: improving an extractor
then looks like improving calibration, and vice versa. This session is the evidence — the CreditAccess
GNPA series was wrong for months while 800 unit tests passed, and the fix moved five checks at once. Only
a suite that scores the two separately can tell you which half moved.

WHAT A CASE MAY NOT CONTAIN. No expected verdict derived from a previous run of this system, and no label
inferred from a price move. A case's label is an external, dated, cited event; a clean case's label is the
absence of one. `verified_facts` are read by a person from the filing, or from an INDEPENDENT primary
source, and each one records which.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from firm.adapters.base.tables import to_canonical_crore

#: How a verified fact was established. The distinction is what keeps the golden set from checking the
#: system against itself: `pipeline` is not in this list, and a case carrying it is refused at load.
VERIFICATION_METHODS = (
    #: read by a person from the filing itself, at the stated page
    "filing_page",
    #: stated by the company in a DIFFERENT regulatory filing — e.g. the Regulation 52(4) annexure to a
    #: quarterly result, which restates asset quality independently of the annual report
    "independent_filing",
    #: implied by an identity the filing itself prints — gross less allowance equals the balance-sheet
    #: line, components summing to their own total. The filing checks it, not us
    "arithmetic_identity",
    #: asserted identically by two filings published a year apart (a comparative column against the
    #: original), which no single misread can produce. WEAKER THAN `independent_filing`: it is two
    #: documents read by one extractor, so an error that repeats across both survives it.
    "cross_filing_overlap",
)

#: WHAT A POSITIVE CLAIMS, and the two are not the same claim (ADR-0062).
#:
#:   `fraud`   — an authority found misstatement: a SEBI adjudication or final order, an NCLT admission,
#:               a restatement forced on the company. The strongest label and the rarest.
#:   `adverse` — a qualifying governance or accounting EVENT that no authority has adjudicated: a
#:               statutory auditor resigning mid-term over unpaid fees or withheld information, a
#:               forensic audit ordered. Strong evidence, and it is not a finding of fraud.
#:
#: Both are positives — the firm must not CLEAR either — and they are scored separately, because a
#: system that catches adjudicated frauds and misses everything else has a recall number that flatters it.
POSITIVE_LABELS = ("fraud", "adverse")
LABELS = (*POSITIVE_LABELS, "clean")

#: Negative classes, ordered by how hard they are for the firm. The HARD ones are the point: a set of easy
#: negatives measures nothing, and the error that destroys this product is a confident rejection of an
#: honest company (docs/GOLDEN_SET.md §2).
NEGATIVE_CLASSES = (
    "easy",
    "hard_cyclical",         # margins and cash yield collapse in a downturn, no dishonesty
    "hard_capex",            # CWIP large for years, legitimately
    "hard_model_mismatch",   # a measure calibrated on a different business model
    "hard_deterioration",    # real stress, honestly disclosed — must REVIEW, never HARD_FAIL
    "hard_recovery",         # metrics improving off a bad year
)


@dataclass(frozen=True)
class VerifiedFact:
    """One figure a person established, and how. The baseline the extraction assertion scores against."""

    metric: str
    period: str
    value: float
    unit: str
    locator: str
    method: str
    source: str = ""
    #: Absolute tolerance in the fact's own unit, for a genuinely stated rounding difference. It defaults
    #: to zero because these are printed figures and a reader who needs slack is usually hiding an
    #: assumption they have not stated.
    tolerance: float = 0.0

    @property
    def canonical(self) -> float | None:
        """The value in ₹ crore, which is what the fact store holds. None if the unit is not a money scale."""
        return to_canonical_crore(self.value, self.unit) if self.unit in ("INR_cr", "INR_lakh") else None

    def matches(self, actual: float | None) -> bool:
        """Equal as FIGURES, which is not the same as equal as floats.

        TWO THINGS THIS GOT WRONG ON THE SET'S FIRST RUN, both worth keeping written down.

        First, exactness. A lakh figure reaches ₹crore through a multiplication, so an exact comparison
        rejects 13,227.94 against 13,227.940000000001. `Overlap.is_rounding` learned that in
        `core/ingest/filings.py`; the same relative tolerance is used here, leaving `tolerance` its real
        job — a stated rounding difference — rather than quietly absorbing float representation error.

        Second, and the one that actually matters: **a verified fact is recorded in the unit the filing
        PRINTS**. Writing "624.83" for a page that prints "62,482.67" in lakh is a human doing arithmetic
        and rounding, and it fails against the true 624.8267 for a reason that has nothing to do with
        extraction. The `unit` field exists so the person records what they read and the harness does the
        conversion — which is also the only version a second reader can check against the page.
        """
        expected = self.canonical if self.canonical is not None else self.value
        return actual is not None and math.isclose(
            actual, expected, rel_tol=1e-9, abs_tol=self.tolerance)


@dataclass(frozen=True)
class Expectation:
    """What the case predicts, written BEFORE the pipeline is run on it.

    A band rather than a point: the honest claim about a clean company under stress is "REVIEW at worst",
    not "exactly REVIEW". Narrowing a band after seeing the answer is how a golden set decays into a
    record of what the system currently does, so a change here belongs in the diff with its reason.
    """

    screen_at_worst: str
    screen_at_best: str = "PASS"
    must_flag: tuple[str, ...] = ()
    must_not_flag: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    ticker: str
    as_of: date
    label: str                     # 'fraud' | 'clean'
    manifest: str
    expectation: Expectation
    verified_facts: tuple[VerifiedFact, ...] = ()
    negative_class: str = ""
    label_event: Mapping[str, Any] | None = None
    #: False until a person has signed the case off. The harness reports it rather than hiding it: a set
    #: whose provenance is "someone said so" is worth less than one that says who, and when.
    human_signed_off: bool = False
    #: A case the firm is KNOWN to fail today, with the tracking id of the open question. It is recorded
    #: rather than deleted or weakened, and it does not fail the gate — but the harness shouts if it
    #: starts PASSING, because that means the question was answered and nobody updated the case. A
    #: red case nobody notices turning green is how a calibration debt gets forgotten.
    known_failure: str = ""
    notes: str = ""


class GoldenCaseError(ValueError):
    """A case file that cannot be trusted. Refused at load, never repaired silently."""


def parse_case(raw: Mapping[str, Any], *, source: str = "") -> GoldenCase:
    """Build a case, refusing anything that would let the set validate the system against itself."""
    where = f" in {source}" if source else ""
    label = str(raw.get("label", ""))
    if label not in LABELS:
        raise GoldenCaseError(f"label must be one of {LABELS}, got {label!r}{where}")

    as_of = raw["as_of"] if isinstance(raw["as_of"], date) else date.fromisoformat(str(raw["as_of"]))
    event = raw.get("label_event")
    if label in POSITIVE_LABELS:
        if not event:
            raise GoldenCaseError(
                f"a {label} case needs a label_event with a source and a date{where}")
        event_date = (event["date"] if isinstance(event["date"], date)
                      else date.fromisoformat(str(event["date"])))
        # THE WHOLE POINT OF THE CASE. If the event was already public at `as_of`, the run is not being
        # asked whether it saw it coming — it is being asked whether it can read the news.
        if event_date <= as_of:
            raise GoldenCaseError(
                f"label_event.date {event_date} is not after as_of {as_of}{where}: the case would test "
                "hindsight rather than foresight")
        if not str(event.get("source", "")).strip():
            raise GoldenCaseError(f"label_event needs a citable source{where}")
    elif event:
        raise GoldenCaseError(f"a clean case must not carry a label_event{where}")

    negative_class = str(raw.get("negative_class", ""))
    if label == "clean" and negative_class not in NEGATIVE_CLASSES:
        raise GoldenCaseError(
            f"clean case needs a negative_class from {NEGATIVE_CLASSES}, got {negative_class!r}{where}")

    facts = []
    for entry in raw.get("verified_facts", ()):
        method = str(entry.get("method", ""))
        if method not in VERIFICATION_METHODS:
            # `pipeline` is deliberately not a method. A fact this system produced cannot be the baseline
            # this system is scored against, and naming that in the error is the point of the check.
            raise GoldenCaseError(
                f"verified_facts.method must be one of {VERIFICATION_METHODS}, got {method!r}{where} — "
                "a fact the pipeline produced cannot be the baseline the pipeline is scored against")
        facts.append(VerifiedFact(
            metric=str(entry["metric"]), period=str(entry["period"]), value=float(entry["value"]),
            unit=str(entry.get("unit", "INR_cr")), locator=str(entry.get("locator", "")),
            method=method, source=str(entry.get("source", "")),
            tolerance=float(entry.get("tolerance", 0.0)),
        ))

    exp = raw.get("expectation") or {}
    return GoldenCase(
        case_id=str(raw["case_id"]), ticker=str(raw["ticker"]), as_of=as_of, label=label,
        manifest=str(raw["manifest"]),
        expectation=Expectation(
            screen_at_worst=str(exp["screen_at_worst"]),
            screen_at_best=str(exp.get("screen_at_best", "PASS")),
            must_flag=tuple(exp.get("must_flag", ())),
            must_not_flag=tuple(exp.get("must_not_flag", ())),
            rationale=str(exp.get("rationale", "")),
        ),
        verified_facts=tuple(facts), negative_class=negative_class, label_event=event,
        human_signed_off=bool(raw.get("human_signed_off", False)),
        known_failure=str(raw.get("known_failure", "")),
        notes=str(raw.get("notes", "")),
    )


#: The enumeration a register-selected case must be traceable to. Written by `firm register`.
REGISTER_FILE = "_register.jsonl"


def load_cases(directory: str | Path) -> list[GoldenCase]:
    """Every case in a directory, in case-id order. A malformed case raises rather than being skipped."""
    root = Path(directory)
    out = [
        parse_case(yaml.safe_load(path.read_text()), source=path.name)
        for path in sorted(root.glob("*.yaml"))
        if not path.name.startswith("_")
    ]
    _check_against_register(out, root / REGISTER_FILE)
    return sorted(out, key=lambda c: c.case_id)


def _check_against_register(cases: Sequence[GoldenCase], register: Path) -> None:
    """A positive's citation must appear in the enumeration it was supposedly selected from (ADR-0064).

    THE CONTROL THIS EXISTS FOR. The first positive case was written with an INVENTED attachment URL —
    plausible in shape, wrong in every character, and pointing at nothing. A citation is the one field
    whose whole job is to let a reader check the claim, so a fabricated one is worse than none: it makes
    the case look auditable while being unauditable.

    Reading the letter is still a person's job and no check can replace it. What this can do is make the
    machine-checkable half machine-checked: the URL has to be one the register actually enumerated.
    Silent when no register file is present, because a case may legitimately come from another source —
    but then the case's provenance rests entirely on `human_signed_off`, which the report names.
    """
    if not register.exists():
        return
    known = {
        json.loads(line)["source"]
        for line in register.read_text().splitlines() if line.strip()
    }
    for case in cases:
        event = case.label_event or {}
        source = str(event.get("source", ""))
        if case.label in POSITIVE_LABELS and event.get("kind") in _REGISTER_KINDS:
            if source not in known:
                raise GoldenCaseError(
                    f"{case.case_id}: label_event.source is not in {register.name} — a citation that the "
                    "register never produced was not selected from it, whatever the case says")


#: Event kinds `firm register` enumerates, and therefore the ones a case can be traced back to.
_REGISTER_KINDS = ("auditor_resignation", "cfo_resignation", "ceo_resignation")


#: The screen verdicts, worst first. A band is an inclusive range over this order.
SCREEN_ORDER = ("HARD_FAIL", "FORENSIC_CAUTION", "REVIEW", "PASS")


def within_band(verdict: str, expectation: Expectation) -> bool:
    """Is `verdict` no worse than `screen_at_worst` and no better than `screen_at_best`?"""
    if verdict not in SCREEN_ORDER:
        return False
    rank = SCREEN_ORDER.index(verdict)
    return SCREEN_ORDER.index(expectation.screen_at_worst) <= rank <= SCREEN_ORDER.index(
        expectation.screen_at_best)


@dataclass(frozen=True)
class CaseResult:
    """One case scored. The two failure lists are kept apart on purpose — see the module docstring."""

    case_id: str
    ticker: str
    label: str
    negative_class: str
    screen: str
    extraction_failures: tuple[str, ...] = ()
    judgment_failures: tuple[str, ...] = ()
    facts_checked: int = 0
    human_signed_off: bool = False
    known_failure: str = ""

    @property
    def extraction_ok(self) -> bool:
        return not self.extraction_failures

    @property
    def judgment_ok(self) -> bool:
        return not self.judgment_failures

    @property
    def passed(self) -> bool:
        return self.extraction_ok and self.judgment_ok

    @property
    def unexpectedly_passing(self) -> bool:
        """A recorded failure that no longer fails. Louder than a pass, because the case is now stale."""
        return bool(self.known_failure) and self.passed

    @property
    def regression(self) -> bool:
        """A failure nobody has already written down. This is what the gate is allowed to care about."""
        return (not self.passed and not self.known_failure) or self.unexpectedly_passing


def score_case(
    case: GoldenCase,
    *,
    screen: str,
    flags: Iterable[str],
    facts: Mapping[tuple[str, str], float],
) -> CaseResult:
    """Score one case. `facts` is {(metric, period) -> value in the fact's unit}, from the run."""
    extraction: list[str] = []
    for fact in case.verified_facts:
        actual = facts.get((fact.metric, fact.period))
        if not fact.matches(actual):
            got = "absent" if actual is None else f"{actual:,.2f}"
            extraction.append(
                f"{fact.metric} {fact.period}: verified {fact.value:,.2f} ({fact.method}"
                f"{', ' + fact.locator if fact.locator else ''}), pipeline read {got}")

    fired = set(flags)
    judgment: list[str] = []
    if not within_band(screen, case.expectation):
        judgment.append(
            f"screen {screen} outside the pre-registered band "
            f"{case.expectation.screen_at_worst}..{case.expectation.screen_at_best}")
    for name in case.expectation.must_flag:
        if name not in fired:
            judgment.append(f"{name} was expected to flag and did not")
    for name in case.expectation.must_not_flag:
        if name in fired:
            judgment.append(f"{name} flagged and must not")

    return CaseResult(
        case_id=case.case_id, ticker=case.ticker, label=case.label,
        negative_class=case.negative_class, screen=screen,
        extraction_failures=tuple(extraction), judgment_failures=tuple(judgment),
        facts_checked=len(case.verified_facts), human_signed_off=case.human_signed_off,
        known_failure=case.known_failure,
    )


@dataclass(frozen=True)
class EvalReport:
    results: tuple[CaseResult, ...] = ()

    @property
    def extraction_failed(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if not r.extraction_ok)

    @property
    def judgment_failed(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if not r.judgment_ok)

    @property
    def regressions(self) -> tuple[CaseResult, ...]:
        """What should stop a release: an unrecorded failure, or a recorded one that quietly went away."""
        return tuple(r for r in self.results if r.regression)

    @property
    def known_failures(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if r.known_failure and not r.passed)

    @property
    def positives(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if r.label in POSITIVE_LABELS)

    @property
    def cleared_a_positive(self) -> tuple[CaseResult, ...]:
        """Positives the firm did NOT flag. The recall failure, and the only number Wave 2 exists for."""
        return tuple(r for r in self.positives if not r.judgment_ok)

    @property
    def unsigned(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if not r.human_signed_off)

    def by_negative_class(self) -> dict[str, tuple[int, int]]:
        """{negative class -> (judgment passes, total)}. Averaging these together hides the hard half."""
        out: dict[str, list[int]] = {}
        for r in self.results:
            if r.label != "clean":
                continue
            bucket = out.setdefault(r.negative_class, [0, 0])
            bucket[0] += int(r.judgment_ok)
            bucket[1] += 1
        return {k: (v[0], v[1]) for k, v in sorted(out.items())}

    def render(self) -> str:
        lines = [f"golden set: {len(self.results)} case(s)"]
        for r in sorted(self.results, key=lambda x: x.case_id):
            mark = "ok  " if r.passed else ("KNOWN" if r.known_failure else "FAIL")
            if r.unexpectedly_passing:
                mark = "STALE"
            sign = "" if r.human_signed_off else "  [unsigned]"
            lines.append(f"  {mark} {r.case_id:22} {r.label:5} {r.negative_class:20} "
                         f"screen={r.screen:14} facts={r.facts_checked}{sign}")
            for problem in r.extraction_failures:
                lines.append(f"        extraction: {problem}")
            for problem in r.judgment_failures:
                lines.append(f"        judgment:   {problem}")
        lines.append("")
        lines.append(f"extraction failures: {len(self.extraction_failed)} of {len(self.results)}")
        lines.append(f"judgment failures:   {len(self.judgment_failed)} of {len(self.results)}")
        for r in self.known_failures:
            lines.append(f"  recorded failure {r.case_id} — {r.known_failure}")
        for r in self.results:
            if r.unexpectedly_passing:
                lines.append(f"  STALE: {r.case_id} was recorded as failing ({r.known_failure}) and now "
                             "passes — close the question and update the case")
        lines.append(f"REGRESSIONS: {len(self.regressions)}")
        for name, (ok, total) in self.by_negative_class().items():
            lines.append(f"  negative class {name:22} {ok}/{total} judged correctly")
        if self.positives:
            ok = len([r for r in self.positives if r.judgment_ok])
            lines.append(f"  positives                            {ok}/{len(self.positives)} judged "
                         "correctly (the firm did not clear them)")
        if self.unsigned:
            lines.append(f"NOT YET HUMAN-SIGNED: {', '.join(r.case_id for r in self.unsigned)}")
        return "\n".join(lines)
