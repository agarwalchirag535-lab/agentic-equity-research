# REPORT_ARCHITECTURE.md — the publishable research report (dual-verdict)

> **Owner directive (2026-07-30).** The firm publishes a professional report on a company **whatever the
> verdict** — not only when fraud is found. A company that passes the full pipeline gets a published
> positive thesis; a clean-but-overpriced company gets a published reject note; a red-flagged company gets
> a published caution report. The two short-seller reports in the repo root were *method references only*
> — the firm's product is its own report line, both directions, on Indian companies of every business
> structure. Ratified as ADR-0016.

## 1. Why dual-verdict publishing is load-bearing (not cosmetic)

- **A published "clean" is a claim, not an absence.** Saying "we found nothing" is only credible if the
  report shows **what was checked and how** — so every published report carries the full *Verified-Clean
  Checklist* (§3.5): every deterministic check that ran, its inputs' fact_ids, and its result — passes
  included. A clean verdict with an invisible process is worth nothing.
- **Symmetric evidentiary bar.** A positive report must survive the same red-team attack, the same
  citation/arithmetic/consistency validators, and the same evidence-graph invariants (R1–R6) as a negative
  one. Optimism is not a lower standard.
- **Symmetric falsifiability.** Positive reports carry **kill criteria** (dated events that would kill the
  thesis). Negative/caution reports carry **rehabilitation criteria** (dated, observable events that would
  reverse the caution). Both feed `memory/predictions.jsonl` and are Brier-scored — published verdicts are
  the firm's calibration record, in public.
- **The funnel decides *whether* to publish, the verdict decides *what*.** ~3,000 companies enter; most
  exit at Gates A–C with a one-line funnel record in `data/gold/rejected/` (not a report — proportionality).
  A full published report is produced for any company that (a) completes the deep pipeline, or (b) triggers
  a forensic finding worth documenting at any stage.

## 2. Verdict taxonomy (every published report carries exactly one)

| Verdict | Meaning | Publishable output |
|---|---|---|
| `COMPOUNDER` | Passed forensics, feasibility (§6.3), valuation discipline, red team | Full positive thesis + kill criteria |
| `QUALITY_WRONG_PRICE` | Forensically clean, good business; fails valuation/feasibility today | Reject note + re-entry triggers (the ALKYLAMINE case — already our house pattern) |
| `WATCH` | Structural promise, thesis not yet provable (often `EMERGING` track, ADR-0008) | Short note + what evidence would upgrade it |
| `FORENSIC_CAUTION` | Deterministic red flags + narrative corroboration | Caution report: evidence chain, replication steps, rehabilitation criteria |
| `INSUFFICIENT_DISCLOSURE` | Legally-public data missing/unreadable after primary-source effort | Opacity itself published as the finding (ADR-0014) |

Hard rule (SPEC §1): no verdict ever says "buy"/"sell" or gives a target-price recommendation. Positive =
"this thesis, these assumptions, these kill criteria." Negative = "this evidence, these questions the
company should answer." The `hedge`/`legal-framing` standards apply to both.

## 3. Report structure (fixed order — the order is the argument)

1. **Header block** — company, ISIN/ticker, `as_of`, run_id, verdict class, numeric confidence, agent
   versions, and the standing disclaimer (research artifact, not advice; no position language).
2. **Executive summary** — the one question, the verdict, the three load-bearing points, each with its
   evidence grade shown inline. One page, no more.
3. **Business model in plain language** — how money actually flows, atomic unit economics, where this
   company sits in its value chain. Written so a non-expert can follow the rest.
4. **The numbers** — computed-fact tables (every figure carries `[fact:...]`), 10-yr trends, common-size
   statements, sector-specific KPIs (per the business-model playbook, ADAPTIVE_FORENSICS.md).
5. **Forensic section — including the passes.** The Verified-Clean Checklist: every deterministic check
   run with inputs and results; notes-coverage % (line-by-line discipline, ADR-0017); disclosure gaps;
   related-party map; auditor/CARO summary. In a `FORENSIC_CAUTION` report this section leads; in a
   `COMPOUNDER` report it is the credibility backbone.
6. **Management & governance** — promise-vs-delivery scorecard, capital-allocation record, pledge
   trajectory, board interlocks (entity graph).
7. **Valuation** — reverse-DCF first (what the price already assumes), then scenarios with probabilities
   summing to 1, sensitivity on the two variables that matter.
8. **Thesis and anti-thesis** — the synthesizer's case and the red team's best attack, both shown. A
   report that hides the bear case (or, for a caution report, the bull rebuttal) does not ship.
9. **Kill / rehabilitation criteria** — dated, observable, resolvable from future filings without
   judgment. Minimum counts per SPEC §7.1.
10. **Predictions logged** — the falsifiable claims this report commits to, with probabilities.
11. **Evidence appendix** — claim → evidence chains from the evidence graph, replication instructions
    ("how a third party reproduces this"), source list with grades, and anything `UNAVAILABLE` stated as
    such.

## 4. Validators that gate publication (all blocking)

Existing: citation, arithmetic, consistency, hedge, evidence-graph R1–R6. Added by this architecture:
- **verified-clean completeness** — a `COMPOUNDER`/`QUALITY_WRONG_PRICE` report must enumerate every
  check in the applicable playbook; a skipped check must say why (never silently absent).
- **symmetry** — positive reports must contain kill criteria; negative reports must contain
  rehabilitation criteria; both must contain the opposing case (§3.8).
- **legal framing** — forensic claims render as evidence-indicates language with replication steps;
  unhedged accusation of fraud as fact = build failure.

## 5. Status — BUILT (2026-07-30)

- `schemas/report.py` — `ResearchReport` (6 verdicts **plus the four-value `Outcome` axis above them**,
  ADR-0067; sections now include `return_potential` (ADR-0068), `valuation` (ADR-0069), `gates`
  (ADR-0071) and `management_questions` (ADR-0066)), `VerifiedCleanChecklist`,
  `CheckRecord` (PASS / FLAG / NOT_APPLICABLE / UNAVAILABLE, the latter two requiring a reason),
  `Criterion` (dated, filing-resolvable), `ReportClaim` (grade inline).
- `core/validators/publication.py` — the **four** blocking gates (P4 was added by ADR-0022 and this line
  went on saying three): **P1** verified-clean completeness (every
  expected check accounted for; note coverage must be 100%), **P2** symmetry (positives need ≥3 dated kill
  criteria incl. one load-bearing; negatives need rehabilitation criteria; both need the opposing case and
  non-empty open questions), **P3** legal framing (unhedged fraud accusations blocked; a FORENSIC_CAUTION
  needs replication steps, ≥1 FLAG, and may not rest only on grade C/D), and **P4** line-item integrity
  (ADR-0022: every unanswered analyst question names what would answer it, every suppressed one says why,
  and a positive verdict may not ship while high-severity questions the filings were asked stay
  unanswerable from them).

  When a gate blocks, the run no longer ends in silence: the publication ladder (ADR-0065) republishes
  a report that asserts strictly less — supplemented, then verdict-withheld, then deterministic-only —
  and states on the artifact what it withheld and why. The gates were not relaxed to achieve that.
- `core/report/render.py` — markdown + JSON renderer. `write_report()` **runs the gates and refuses to
  write an invalid report** (`ReportNotPublishable`), so a misleading artifact cannot reach disk by
  accident. Uncited numbers render as `**UNCITED**` rather than passing as sourced.
- 28 tests, all three modules 100% covered.

## 5a. Status — WIRED (Phase 2, ADR-0021)

The report is no longer assembled by hand. `core/pipeline/deep_dive.py` produces it end to end:

- **§4 numbers** come from `core/pipeline/derive.py`, where each figure carries its formula, its input
  `Fact`s, and a citation graded at the **worst** input grade — so a ratio can never look better-sourced
  than the facts underneath it.
- **§5 checklist** comes from `core/pipeline/checks.py`, which records an explicit outcome for every check
  the playbook selects. `UNAVAILABLE` names the missing inputs; `NOT_APPLICABLE` names the suppressing
  business models. This is what makes P1 meaningful rather than satisfiable by omission.
- **§2 load-bearing points** are the claims the evidence graph promoted (grade A/B support + confidence
  floor), deduplicated and capped run-wide — the same set R1 checked.
- **§9 criteria** are computed by `core/report/criteria.py` from metrics + `thresholds.yaml`, dated to the
  next FY close plus the filing lag. A failed feasibility gate becomes the §2 re-entry trigger.
- **the verdict** is the deterministic ladder in `core/report/assemble.py`; the forensic agent's veto can
  only make it worse.
- **§6 management and §7 valuation** are wired: `management_analyst` (Phase 3) and `valuation_modeler` /
  `portfolio_manager` (Phase 4, ADR-0069/0070) narrate whenever staffed, above a deterministic Valuation
  section carrying the reverse DCF and the priced grid. When an agent genuinely did not run, the section
  says so explicitly rather than rendering empty — absent is not clean.

One amendment to §4 above: the note-coverage gate now exempts `INSUFFICIENT_DISCLOSURE`, whose finding *is*
the unreadable filing, and instead requires that verdict to be evidenced by an `UNAVAILABLE` check or a
named disclosure gap — the same standard `FORENSIC_CAUTION` is held to. First published artifact:
`reports/ALKYLAMINE/2026-07-23-433c94208117/`.

## 6. Formats

`reports/{TICKER}/{run_id}/report.md` + `report.json` (the structured object the validators check) —
extending the existing `reports/ALKYLAMINE.md` + `.json` pattern. Markdown is the publishable artifact;
JSON is the auditable one. Both git-tracked (Law 6).
