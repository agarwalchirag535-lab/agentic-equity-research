"""What each agent is actually shown — the evidence its mandate needs, not everyone's evidence (ADR-0038).

THE DEFECT THIS FIXES
`agent_facts_payload` built one payload and `build_packets` handed the same object to every agent. With
three agents that was right: `business_analyst`, `financial_statement_analyst` and `forensic_accountant`
all reason about the same statements. With eight it became the reason five of them could not work.
Hashing the rendered packets showed the evidence block byte-identical across all eight, so:

  * `transcript_analyst`, whose mandate is "read 12+ quarters of concalls as a time series" and whose
    declared inputs are concall transcripts, received no transcript text — and was asked for
    `guidance_drift`, `dodged_questions` and `tone_trace`.
  * `ownership_flows_analyst`, asked for `smart_money_score` and a days-to-exit number, received no
    shareholding pattern, no pledge status and no price history.
  * `management_analyst`, asked to build a promise-vs-delivery scorecard from twelve concalls, received
    twenty-six profitability ratios.

An agent in that position has two options and both are failures: invent something plausible, or return
nulls that read as "nothing to report" (ADR-0027's false-clean problem, now at the agent layer). The
firm was measuring neither, because a null was indistinguishable from a clean finding.

THE PREREQUISITE VOCABULARY IS THE BRIEF
`config/roster.yaml` already declares what each agent needs — `requires: [shareholding, pledge]`. That
list is now what builds the brief, so the two cannot drift: an agent the roster plans is an agent whose
declared inputs were assembled, and an input the roster names with no builder here is a loud failure
rather than a silent omission.

AN ABSENT INPUT IS STATED, NEVER OMITTED
Every prerequisite appears in the brief. One the run could not supply appears as an explicit
`UNAVAILABLE` block naming the mandate obligation it blocks and instructing the agent to return null for
the dependent field. Leaving it out instead would ask the agent to notice an absence, and models do not
reliably notice absences — they fill them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from firm.core.compute import multibagger, quality
from firm.core.compute.models import BusinessModel
from firm.core.ingest.documents import DocumentIngest
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.pipeline.derive import DerivedSet
from firm.core.pipeline.filing import FilingWalk
from firm.core.report.assemble import NotesReview

#: The most recent N calls a transcript brief carries. The mandate asks for "12+ quarters", and beyond
#: that the marginal quarter costs more context than it adds. Older calls are still counted in the
#: coverage line so the agent knows the series is longer than the window it was given.
_MAX_CALLS = 12
#: Quotes per call. A call that produced 15 forward-looking statements is usually repeating one; taking
#: the first few keeps the brief readable without hiding that there were more (the count is stated).
_MAX_QUOTES_PER_CALL = 8
#: Entries in the promise ledger. Twelve quarters of calls yield ~150 dated commitments on a company that
#: talks as much as this one; the scorecard is built from the recent ones, and the total is stated so the
#: agent knows the window is a window.
_MAX_PROMISES = 80


@dataclass(frozen=True)
class EvidenceBundle:
    """Everything a run gathered, before it is split up per agent."""

    ticker: str
    as_of: date
    derived: DerivedSet
    evaluation: CheckEvaluation
    screen: quality.ForensicScreenResult
    feasibility: multibagger.FeasibilityResult | None
    models: Sequence[BusinessModel]
    notes: NotesReview
    documents: DocumentIngest | None = None
    walk: FilingWalk | None = None
    peers: Any = None                      # PeerSet | None — typed loosely to keep the import one-way


def _unavailable(reason: str, blocks: str, instruction: str) -> dict[str, Any]:
    """A prerequisite the run could not supply, stated in the terms the agent has to act on.

    Three fields because three different things need saying: what is missing, which part of this agent's
    own mandate it makes unanswerable, and what to do about it. The third matters most — "return null"
    is an instruction a model follows, while a bare absence is a gap a model fills.
    """
    return {
        "status": "UNAVAILABLE",
        "reason": reason,
        "blocks": blocks,
        "instruction": instruction,
        "whose_gap": "the firm's coverage, not the company's disclosure — do NOT hold this against the "
                     "company, and do not treat it as a clean finding",
    }


def _transcripts_block(bundle: EvidenceBundle) -> dict[str, Any]:
    ingest = bundle.documents
    calls = list(ingest.usable_transcripts) if ingest is not None else []
    if not calls:
        return _unavailable(
            "no concall transcript was ingested for this company",
            "guidance drift, dodged questions, the tone trace, and any promise-vs-delivery scorecard",
            "return `guidance_drift` as an explicit statement that no transcript was read, and leave "
            "`dodged_questions` and `tone_trace` empty rather than inferring them from the financials",
        )

    window = calls[-_MAX_CALLS:]
    return {
        "status": "AVAILABLE",
        "coverage": (f"{len(calls)} calls read, {calls[0].held_on} to {calls[-1].held_on}; "
                     f"the {len(window)} most recent are quoted below"),
        "refusals": list(ingest.refusals) if ingest is not None else [],
        "how_to_use": (
            "These are verbatim quotes with the page they appear on. Quote them; do not convert any "
            "statement into a number (Law 1). A management claim is grade-C evidence about MANAGEMENT, "
            "not about the business."
        ),
        "calls": [
            {
                "period": call.read.period,
                "held_on": call.held_on.isoformat() if call.held_on else None,
                "source": call.file,
                "management_present": [
                    {"name": s.name, "role": s.role} for s in call.read.management],
                "cfo_present": any(s.is_cfo for s in call.read.management),
                "analysts_present": list(call.read.analysts),
                "exchanges": len(call.read.exchanges),
                "guidance_statements_found": len(call.read.guidance),
                "guidance": [
                    {"speaker": q.speaker, "page": q.page, "quote": q.text}
                    for q in call.read.guidance[:_MAX_QUOTES_PER_CALL]
                ],
                "answers_that_declined_to_disclose": [
                    {"speaker": q.speaker, "page": q.page, "quote": q.text}
                    for q in call.read.deflections[:_MAX_QUOTES_PER_CALL]
                ],
                "questions_met_with_a_refusal": [
                    {"analyst": e.analyst, "page": e.page, "question": e.question, "answer": e.answer}
                    for e in call.read.exchanges if e.deflected
                ][:_MAX_QUOTES_PER_CALL],
            }
            for call in window
        ],
    }


def _guidance_block(bundle: EvidenceBundle) -> dict[str, Any]:
    """The promise ledger: every dated forward-looking statement, oldest first.

    Separate from the transcript block even though it comes from the same documents, because the two
    agents ask different questions of it. `transcript_analyst` reads a call as a *call*; the promise
    ledger is a single dated sequence spanning calls, which is the only shape a promise-vs-delivery
    scorecard can be built from.
    """
    ingest = bundle.documents
    calls = list(ingest.usable_transcripts) if ingest is not None else []
    promises = [
        {
            "made_on": call.held_on.isoformat() if call.held_on else None,
            "quarter": call.read.period,
            "speaker": quote.speaker,
            "locator": f"{call.file} p.{quote.page}",
            "promise": quote.text,
        }
        for call in calls for quote in call.read.guidance
    ]
    if not promises:
        return _unavailable(
            "no transcript was ingested, so no dated management commitment could be extracted",
            "the promise-vs-delivery scorecard, which is this agent's primary mandate",
            "return `promise_delivery_score` as null and say in the narrative that no commitment could "
            "be resolved because no transcript was read",
        )
    window = promises[-_MAX_PROMISES:]
    return {
        "status": "AVAILABLE",
        "count": len(promises),
        "shown": (f"the {len(window)} most recent of {len(promises)}"
                  if len(window) < len(promises) else "all of them"),
        "how_to_use": (
            "Each entry is something management SAID WOULD HAPPEN, on a date. Resolve each against what "
            "the computed financials show actually happened, and score delivered / (delivered + missed + "
            "quietly dropped). A promise whose goalpost moved is not a promise kept. `promise_delivery_score` "
            "must still be null unless the compute layer produced it — state the score's components in "
            "prose instead."
        ),
        "promises": window,
    }


def _shareholding_block(bundle: EvidenceBundle) -> dict[str, Any]:
    ingest = bundle.documents
    series = list(ingest.shareholding_series) if ingest is not None else []
    if not series:
        return _unavailable(
            "no SEBI shareholding pattern was ingested for this company",
            "promoter-stake trend, free-float trend and every institutional-flow reading",
            "return `smart_money_score` and `institutional_absence_read` as null, and say the "
            "shareholding record was not read",
        )
    return {
        "status": "AVAILABLE",
        "source": "SEBI LODR Reg. 31 quarterly shareholding patterns, filed by the company",
        "coverage": f"{len(series)} quarters, {series[0].as_on} to {series[-1].as_on}",
        "how_to_use": (
            "Promoter % is a grade-A filed figure with a fact id — cite it, never restate it from memory. "
            "The delta between quarters is the finding; a single quarter is not."
        ),
        "quarters": [
            {
                "period": item.period,
                "as_on": item.as_on.isoformat() if item.as_on else None,
                "as_on_basis": item.summary.as_on_basis,
                "promoter_pct": item.summary.promoter_pct,
                "public_pct": item.summary.public_pct,
                "promoter_shareholders": item.summary.promoter_shareholders,
                "fact_ids": list(item.fact_ids),
            }
            for item in series
        ],
        "refusals": [r for r in (ingest.refusals if ingest else ()) if "shareholding" in r.lower()],
    }


def _pledge_block(bundle: EvidenceBundle) -> dict[str, Any]:
    ingest = bundle.documents
    series = list(ingest.shareholding_series) if ingest is not None else []
    if not series:
        return _unavailable(
            "no shareholding pattern was ingested, so the pledge question was never read",
            "the promoter-pledge trajectory",
            "return `promoter_pledge_pct` as null",
        )
    answered = [s for s in series if s.summary.pledged is not None]
    return {
        "status": "AVAILABLE",
        "question": ("Reg. 31: 'Whether any shares held by promoters are pledge or otherwise "
                     "encumbered?' — the company's own answer, quarter by quarter"),
        "how_to_use": (
            "THREE STATES, NOT TWO. `false` means the company was asked and answered No — a real "
            "governance finding you may report. `null` means the question was not located in that "
            "filing — you may NOT report it as unpledged. A quarter where the answer flips is the event "
            "worth writing about."
        ),
        "quarters_answered": len(answered),
        "quarters_unanswered": len(series) - len(answered),
        "history": [
            {"period": s.period, "as_on": s.as_on.isoformat() if s.as_on else None,
             "pledged": s.summary.pledged}
            for s in series
        ],
    }


def _segments_block(bundle: EvidenceBundle) -> dict[str, Any]:
    walk = bundle.walk
    rows = dict(walk.rows) if walk is not None else {}
    segment_rows = {k: v for k, v in rows.items() if "segment" in k.lower()}
    if not segment_rows:
        return _unavailable(
            "the Ind AS 108 segment note is downloaded inside the annual report but no reader has been "
            "built for it, so no per-segment revenue, result or capital-employed row is available",
            "naming the atomic unit and connecting it arithmetically to a year-7 revenue — the whole "
            "mandate of this agent",
            "return `units_today`, `units_plausible_in_7y`, `contribution_margin_per_unit` and "
            "`payback_years` as null. Name the unit in `unit_definition` and state, in the narrative, "
            "exactly which filing row would let the arithmetic be done",
        )
    return {"status": "AVAILABLE", "rows": {k: v.value for k, v in segment_rows.items()}}


def _peers_block(bundle: EvidenceBundle) -> dict[str, Any]:
    peers = bundle.peers
    if peers is None or not getattr(peers, "companies", ()):
        return _unavailable(
            "no peer set has been ingested for this company",
            "sizing the profit pool, identifying who holds pricing power, and separating structural "
            "from cyclical",
            "say plainly in `profit_pool` and `structural_vs_cyclical` that no peer comparison was "
            "possible, and leave `pricing_power_holders` empty rather than naming competitors from "
            "background knowledge — an unsourced competitor list is exactly the fabrication the "
            "citation validator exists to catch",
        )
    return {
        "status": "AVAILABLE",
        "how_to_use": (
            "Each peer's figures are computed from that peer's OWN filings by the same compute layer, "
            "so they are comparable. Cite a peer figure by its fact id like any other number."
        ),
        "as_of": peers.as_of.isoformat() if getattr(peers, "as_of", None) else None,
        "companies": peers.as_payload(),
    }


def _prices_block(bundle: EvidenceBundle) -> dict[str, Any]:
    return _unavailable(
        "no price or traded-volume history is ingested — the firm has no market-data adapter",
        "days-to-exit at 20% of ADV, position sizing, and any liquidity claim",
        "return `days_to_exit_at_20pct_adv` as null. Do NOT describe liquidity in adjectives instead; "
        "the mandate forbids a concentration claim without the days number, so the honest answer is "
        "that the constraint could not be quantified",
    )


def _financials_block(bundle: EvidenceBundle) -> dict[str, Any]:
    """Present for completeness: the computed metrics already sit at the top level of every packet."""
    return {
        "status": "AVAILABLE",
        "see": "`computed_metrics`, `metrics_unavailable`, `checklist` and `feasibility_gate` above",
    }


def _filing_block(bundle: EvidenceBundle) -> dict[str, Any]:
    walk = bundle.walk
    if walk is None:
        return _unavailable(
            "no audited annual report was walked in this run — the figures rest on a grade-B snapshot",
            "any claim resting on the notes to accounts, Schedule III rows or auditor language",
            "confine yourself to the computed metrics and say which of your conclusions would change "
            "if the filing had been read",
        )
    return {
        "status": "AVAILABLE",
        "notes_enumerated": bundle.notes.notes_total,
        "note_coverage": bundle.notes.coverage,
        "substantive_share": bundle.notes.substantive_share,
        "caro_flags": [{"clause": c, "finding": f} for c, f in walk.caro_flags],
        "mandated_disclosures_not_found": list(walk.missing_disclosures),
    }


#: Roster prerequisite -> the evidence block that satisfies it. Keys are exactly the vocabulary in
#: `config/roster.yaml`, so a prerequisite with no builder is caught by `build_brief` rather than
#: quietly producing a thinner brief than the roster promised.
EVIDENCE_BUILDERS = {
    "financials": _financials_block,
    "filing": _filing_block,
    "segments": _segments_block,
    "transcripts": _transcripts_block,
    "guidance": _guidance_block,
    "shareholding": _shareholding_block,
    "pledge": _pledge_block,
    "peers": _peers_block,
    "prices": _prices_block,
}


class UnknownPrerequisiteError(KeyError):
    """A roster prerequisite with no evidence builder — a wiring bug, surfaced instead of ignored."""


def build_brief(requires: Sequence[str], bundle: EvidenceBundle) -> dict[str, Any]:
    """The evidence block for one agent: every prerequisite it declared, supplied or explicitly absent."""
    brief: dict[str, Any] = {}
    for prerequisite in requires:
        builder = EVIDENCE_BUILDERS.get(prerequisite)
        if builder is None:
            raise UnknownPrerequisiteError(
                f"roster prerequisite {prerequisite!r} has no evidence builder in "
                f"core/pipeline/briefs.py — the agent would be planned and then run blind, which is "
                f"the exact failure this module exists to prevent"
            )
        brief[prerequisite] = builder(bundle)
    return brief


def build_briefs(
    requirements: Mapping[str, Sequence[str]], bundle: EvidenceBundle
) -> dict[str, dict[str, Any]]:
    """`{agent: brief}` for every planned agent, from the roster's own `requires` lists."""
    return {agent: build_brief(requires, bundle) for agent, requires in requirements.items()}


__all__ = [
    "EVIDENCE_BUILDERS",
    "EvidenceBundle",
    "UnknownPrerequisiteError",
    "build_brief",
    "build_briefs",
]
