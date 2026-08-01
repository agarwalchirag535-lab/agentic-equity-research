"""Line-by-line interrogation of the financial statements (ADR-0022).

THE GAP THIS CLOSES
The Phase-2 report was arithmetically sound and analytically shallow. It said "revenue compounded at
11.2%" and moved on. The owner's objection is the correct one: *"we can't just see the revenue, we have to
see why the revenue is increasing... if the debt is increasing we can't consider it wrong, we have to find
the answer why the debt is increasing."* A number without its cause is a screener output; the cause is the
research.

So this module turns each statement line into an **interrogation**: a fixed set of analyst questions from
`config/line_items.yaml`, each resolved exactly one of three ways and never by silence.

  ANSWERED        a derivation in `DerivedSet` answers it. The finding renders with the number, the
                  formula, and the input fact ids — Law 1 (no LLM-authored numbers) and Law 2 (provenance).
  UNANSWERED      nothing in the sources read can answer it, so the question is **printed anyway** with
                  `needs:` naming the exact annual-report row that would close it. This is the house
                  standard ("say I don't know") made structural, and it doubles as the extraction backlog.
  NOT_APPLICABLE  the question is invalid for the detected business model (receivable days on a bank), so
                  it is suppressed with a reason rather than answered wrongly. ADR-0002/0017.

WHY THE THREE-WAY DISTINCTION IS THE WHOLE POINT
A report that omits what it could not check is indistinguishable from one where everything was clean —
the same defect ADR-0021 fixed for the forensic checks, one layer up. An unanswered question is evidence
about the *disclosure*, and `unanswered_high` feeds the verdict: a company whose revenue cannot be
decomposed into volume and price has not earned a compounding verdict, however good its ratios look.

Deterministic and offline: every judgment clause comes from a `bands:` threshold in config (SPEC §3 — no
policy numbers in Python), and nothing here calls an LLM or the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from firm.core.pipeline.derive import DerivedSet
from firm.schemas._base import Citation


class AnswerStatus(str, Enum):
    ANSWERED = "ANSWERED"
    UNANSWERED = "UNANSWERED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class GapKind(str, Enum):
    """WHOSE fault an unanswered question is. The distinction changes what the verdict may conclude.

    DISCLOSURE — the pipeline knows how to read this row, went looking, and the sources did not carry it.
                 That is evidence *about the company*, and it is allowed to move the verdict: a listed
                 company whose cash balance is not in its own filing has told you something.
    CAPABILITY — the firm has no extractor for this yet. The row may well be sitting in the annual report,
                 unread. That is evidence *about us*, and it must NOT be charged to the company. It lowers
                 confidence (we know less) and it goes on the backlog, but it cannot make a business look
                 opaque because our note-parser is unfinished.

    Getting this backwards is the subtle failure the whole module could have shipped with: a firm that
    marks companies down for its own missing code will reject every good business it cannot yet read, and
    call that rigour.
    """

    DISCLOSURE = "DISCLOSURE"
    CAPABILITY = "CAPABILITY"
    NONE = "NONE"


@dataclass(frozen=True)
class Answer:
    """One analyst question and what the sources could actually say about it."""

    line_item: str
    question_id: str
    question: str
    status: AnswerStatus
    severity: str = "medium"
    gap: GapKind = GapKind.NONE            # UNANSWERED only — see GapKind
    finding: str = ""                      # the deterministic sentence, ANSWERED only
    metric: str | None = None
    value: float | None = None
    citation: Citation | None = None
    fact_ids: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()            # what would answer it, UNANSWERED only
    reason: str = ""                       # why UNANSWERED / NOT_APPLICABLE

    @property
    def is_answered(self) -> bool:
        return self.status is AnswerStatus.ANSWERED

    @property
    def counts_against_coverage(self) -> bool:
        """NOT_APPLICABLE questions are excluded from the denominator — suppressing an invalid question is
        a correct answer, not a gap, so it must not make a bank look opaque."""
        return self.status is not AnswerStatus.NOT_APPLICABLE


@dataclass(frozen=True)
class LineItemDossier:
    """Every question asked of one statement line, with its answers."""

    line_item: str
    label: str
    why: str
    answers: tuple[Answer, ...]

    @property
    def applicable(self) -> tuple[Answer, ...]:
        return tuple(a for a in self.answers if a.counts_against_coverage)

    @property
    def answered(self) -> tuple[Answer, ...]:
        return tuple(a for a in self.answers if a.is_answered)

    @property
    def coverage(self) -> float:
        """Share of applicable questions this line item could actually answer. 1.0 when none apply."""
        applicable = self.applicable
        return 1.0 if not applicable else len(self.answered) / len(applicable)

    @property
    def unanswered_high(self) -> tuple[Answer, ...]:
        return tuple(
            a for a in self.answers
            if a.status is AnswerStatus.UNANSWERED and a.severity == "high"
        )

    @property
    def undisclosed_high(self) -> tuple[Answer, ...]:
        """High-severity questions the sources were asked and could not answer — the verdict-moving set."""
        return tuple(a for a in self.unanswered_high if a.gap is GapKind.DISCLOSURE)


@dataclass(frozen=True)
class Interrogation:
    """The full line-by-line pass, ready to render and to feed the verdict."""

    dossiers: tuple[LineItemDossier, ...]
    version: str

    @property
    def all_answers(self) -> tuple[Answer, ...]:
        return tuple(a for d in self.dossiers for a in d.answers)

    @property
    def coverage(self) -> float:
        applicable = [a for a in self.all_answers if a.counts_against_coverage]
        if not applicable:
            return 1.0
        return len([a for a in applicable if a.is_answered]) / len(applicable)

    @property
    def unanswered_high(self) -> tuple[Answer, ...]:
        return tuple(a for d in self.dossiers for a in d.unanswered_high)

    @property
    def undisclosed_high(self) -> tuple[Answer, ...]:
        """The only unanswered set allowed to degrade a verdict (see `GapKind`)."""
        return tuple(a for d in self.dossiers for a in d.undisclosed_high)

    @property
    def capability_gaps(self) -> tuple[Answer, ...]:
        """Questions blocked on an extractor the firm has not built. Our backlog, not the company's flaw."""
        return tuple(
            a for a in self.all_answers
            if a.status is AnswerStatus.UNANSWERED and a.gap is GapKind.CAPABILITY
        )

    def needs_index(self) -> tuple[str, ...]:
        """Every distinct source row that would close a gap — the extraction backlog, deduplicated.

        This is the operational payoff: the questions the pipeline cannot answer name their own fix, so
        "improve the data layer" stops being a vague instruction and becomes an ordered list.
        """
        seen: dict[str, None] = {}
        for answer in self.all_answers:
            if answer.status is AnswerStatus.UNANSWERED:
                for need in answer.needs:
                    seen.setdefault(need, None)
        return tuple(seen)


def _format(value: float, unit: str) -> str:
    """Render a number the way an analyst would write it. Formatting only — no policy here."""
    if unit == "pct":
        return f"{value:.1%}"
    if unit == "pp":                      # a change in a ratio, in percentage points, signed
        return f"{value * 100:+.1f}pp"
    if unit == "inr_cr":
        return f"₹{value:,.0f} crore" if value >= 0 else f"-₹{abs(value):,.0f} crore"
    if unit == "x":
        return f"{value:.2f}x"
    # A turnover measure is denominated in DAYS. Rendering it as a multiple ("54.78x") reads as a
    # ratio-of-something and is wrong in a section whose whole subject is how long cash is tied up.
    if unit == "days":
        return f"{value:+.1f} days" if abs(value) < 15.0 else f"{value:,.1f} days"
    return f"{value:,.2f}"


def _band_clause(value: float, bands: Sequence[Mapping[str, Any]]) -> str:
    """The first matching band's `says`. Bands are POLICY and live in config, never here.

    A band with neither `at_least` nor `at_most` is the fallback and matches unconditionally, so an
    ordered list reads top-down like the analyst's own thresholds.
    """
    for band in bands:
        floor, ceiling = band.get("at_least"), band.get("at_most")
        if floor is not None and value < floor:
            continue
        if ceiling is not None and value > ceiling:
            continue
        return str(band.get("says", ""))
    return ""


def _applicability(spec: Mapping[str, Any], models: Sequence[str]) -> str | None:
    """None when the question applies; otherwise the reason it is suppressed for these models."""
    detected = set(models)
    excluded = set(spec.get("exclude_models") or ())
    if hit := detected & excluded:
        return f"not a meaningful question for a {'/'.join(sorted(hit))} business model"
    only = set(spec.get("models") or ())
    if only and not (detected & only):
        return (
            f"scoped to {'/'.join(sorted(only))}; this company was detected as "
            f"{'/'.join(sorted(detected)) or 'no specific model'}"
        )
    return None


def _answer(
    line_item: str, spec: Mapping[str, Any], derived: DerivedSet, models: Sequence[str], window: str
) -> Answer:
    """Resolve one configured question against the derivations. Never returns a silent gap."""
    qid, question = str(spec["id"]), " ".join(str(spec["question"]).split())
    severity = str(spec.get("severity", "medium"))
    needs = tuple(str(n) for n in (spec.get("needs") or ()))
    common = {
        "line_item": line_item, "question_id": qid, "question": question, "severity": severity,
    }

    if (reason := _applicability(spec, models)) is not None:
        return Answer(**common, status=AnswerStatus.NOT_APPLICABLE, reason=reason)

    metric = spec.get("metric")
    if metric is None:
        # No metric at all: nothing in the compute layer even attempts this question, so it is blocked on
        # an extractor the firm has not written. A CAPABILITY gap — ours, not the company's.
        return Answer(
            **common, status=AnswerStatus.UNANSWERED, gap=GapKind.CAPABILITY, needs=needs,
            reason="no extractor reads this yet — it requires the primary-source rows named below",
        )

    derivation = derived.get(str(metric))
    if derivation is None:
        # `DerivedSet.missing` is the discriminator, and it is exact: a metric lands there only because
        # `derive_metrics` tried to build it and found an input absent. That is a real DISCLOSURE gap. A
        # metric absent from both `values` and `missing` was never attempted at all, so the gap is ours.
        missing = derived.missing.get(str(metric), ())
        if missing:
            return Answer(
                **common, status=AnswerStatus.UNANSWERED, gap=GapKind.DISCLOSURE, metric=str(metric),
                needs=needs, reason=f"the sources read do not disclose: {', '.join(missing)}",
            )
        return Answer(
            **common, status=AnswerStatus.UNANSWERED, gap=GapKind.CAPABILITY, metric=str(metric),
            needs=needs,
            reason=(
                f"no derivation for {metric!r} exists in the pipeline yet, so this question was never put "
                "to the sources — a gap in the firm's extraction, not in the filing"
            ),
        )

    # A derivation can be arithmetically correct and still meaningless: ALKYLAMINE's implied cost of debt
    # computes to 100% because year-end borrowings are ~₹2cr against ₹18cr of interest paid during the
    # year. Printing that as a finding — with a confident band clause attached — would be worse than
    # printing nothing, because the prose lends authority to a degenerate denominator. `plausible:` in
    # config declares the range in which the ratio carries information; outside it the question is
    # UNANSWERED and says why, which is the same treatment as a missing input.
    plausible = spec.get("plausible") or {}
    low, high = plausible.get("min"), plausible.get("max")
    if (low is not None and derivation.value < low) or (high is not None and derivation.value > high):
        # The ratio computed but carries no information, and the fix is a better input (an average balance
        # from the borrowings note) rather than a new extractor — so this is a DISCLOSURE gap.
        return Answer(
            **common, status=AnswerStatus.UNANSWERED, gap=GapKind.DISCLOSURE, metric=str(metric),
            value=derivation.value, needs=needs,
            reason=" ".join((
                f"computes to {_format(derivation.value, str(spec.get('unit', 'ratio')))}, outside the "
                f"range in which this ratio carries information — "
                # `because` is a folded YAML scalar and arrives with newlines; the report needs one line
                # or the trailing break splits the markdown list that follows.
                f"{plausible.get('because', 'the inputs are too small for the ratio to be meaningful')}"
            ).split()),
        )

    unit = str(spec.get("unit", "ratio"))
    rendered = _format(derivation.value, unit)
    against_txt = ""
    if (against := spec.get("against")) is not None:
        other = derived.get(str(against))
        # The companion metric may be measured in something else entirely — "capex ran at 3.44x of
        # depreciation, on ₹1,388 crore of gross spend" needs two units in one sentence, and forcing the
        # second into the first printed the rupee total as "1388.14x".
        against_unit = str(spec.get("against_unit", unit))
        against_txt = _format(other.value, against_unit) if other is not None else "unavailable"
    template = str(spec.get("template", "{v}"))
    finding = template.replace("{v}", rendered).replace("{a}", against_txt).replace("{window}", window)
    if clause := _band_clause(derivation.value, spec.get("bands") or ()):
        finding = f"{finding.rstrip('.')} — {clause}."
    return Answer(
        **common, status=AnswerStatus.ANSWERED, finding=finding, metric=str(metric),
        value=derivation.value, citation=derivation.citation, fact_ids=derivation.fact_ids,
    )


def interrogate(
    derived: DerivedSet, models: Sequence[str], registry: Mapping[str, Any]
) -> Interrogation:
    """Ask every configured question of every statement line, for one company as-of one date.

    `registry` is `config/line_items.yaml` already loaded, passed in rather than read here so the caller
    owns configuration and this stays a pure function (testable with a two-question registry).
    """
    window = (
        f"{derived.first_period}-{derived.last_period}"
        if derived.first_period and derived.last_period else "the available history"
    )
    dossiers = tuple(
        LineItemDossier(
            line_item=str(item["id"]),
            label=str(item.get("label", item["id"])),
            why=" ".join(str(item.get("why", "")).split()),
            answers=tuple(
                _answer(str(item["id"]), q, derived, models, window)
                for q in (item.get("questions") or ())
            ),
        )
        for item in (registry.get("line_items") or ())
    )
    return Interrogation(dossiers=dossiers, version=str(registry.get("version", "0")))
