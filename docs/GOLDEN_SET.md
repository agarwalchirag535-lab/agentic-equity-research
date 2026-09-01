# GOLDEN_SET.md — design before construction

> **Status: FINAL — eight cases, all signed (ADR-0087; ported by ADR-0057, grown by ADR-0061).**
> Six clean negatives across five hardness classes, two adverse positives —
> behind `firm eval` / `make eval`. Current (2026-08-31, ADR-0060): **7 of 7 in band, 0 extraction
> failures, 0 regressions, positives 1/1** — the set's first fully green run, with Five-Star's
> readings authored (PORT-1b closed) and CAL-1 closed without moving a threshold. Open: CAL-2 (§6)
> and human sign-off on all seven cases. Written 2026-08-30 after the point-in-time defects the third
> line's ADRs recorded, which are the reason it was written before any case was added.
>
> **Wave 1 immediately caught five fabricated facts — written by the author of the cases, not by the
> pipeline.** See ADR-0061. The `method` field is what made them visible.

## 0. What this is for, and what would make it worthless

Every forensic threshold in `config/*.yaml` is a guess. STATUS §3D has said so since the beginning, and
this session put numbers on it: a HARD_FAIL on Five-Star Business Finance from a provision-coverage floor
calibrated on a different lending model (ADR-0058), and a HARD_FAIL on Alkyl Amines FY23 from a cash-yield
band missed by 0.8 percentage points of the band. The firm cannot know which of those is real.

The golden set is the instrument that answers that. It is **not** a test suite for the code — 841 unit
tests already do that, and all of them passed through every defect this session found. It is a
measurement of whether the *judgment* is right.

**The way it fails is by validating itself.** Four concrete mechanisms, each with a countermeasure below:

| how it goes circular | countermeasure |
|---|---|
| labels come from our own output | §2 — labels are external events with a citation and a date |
| a uniform upstream bug becomes a fitted parameter | §1 — prerequisites; ADR-0059 is the worked example |
| extraction error and judgment error get confused | §4 — every case records human-verified FACTS, scored separately from verdicts |
| thresholds are reported on the data they were fit to | §6 — disjoint calibration and evaluation splits |

## 1. Prerequisites — what must be true before the first case is added

ADR-0059 is why this section exists. Had the golden set been built first, every pre-2022 case would have
carried a fabricated `disclosure_gap`, calibration would have learned to discount that signal to
compensate, and the resulting thresholds would have been wrong for every filing after 2022. **A bug
uniform across the calibration set is indistinguishable from a property of the world.** No care taken
inside the golden set catches that; it has to be fixed upstream.

- [x] **Point-in-time document filtering** — verified: replay at 2019/2021/2023 ingests 2/4/7 filings.
- [x] **Point-in-time rulebook** — `config/disclosure_mandates.yaml` (ADR-0059).
- [x] **Attribution split** — our extraction failures are never the company's disclosure gap
      (ADR-0055, ADR-0059).
- [x] **Deterministic replay** — filings are content-addressed in bronze; a re-run is bit-identical.
- [~] **Dated reference rates.** MECHANISM BUILT, DATA NOT YET SUPPLIED (ADR-0078).
      `config/reference_rates.yaml` + `core/compute/rates.py` give `risk_free_rate` a point-in-time
      lookup by fiscal year, and the cash-yield check now states which vintage's rate its floor came
      from. `by_fiscal_year` is deliberately EMPTY: typing RBI yields in from memory would fabricate a
      primary input, and nothing downstream could detect it. Until rows are added from a citable
      published series the firm uses the undated 6.5% fallback and says so in every check that rests on
      it. **This item is not closed until the rows exist** — a test shows the flat rate false-positives
      in a low-rate year and false-negatives in a high-rate one, which is exactly the year-dependent
      error §1 warns calibration would learn to compensate for.
- [ ] **Pre-Ind AS extraction.** Everything validated so far is FY17+. Cases before FY2017 use the old
      Schedule III and have no Ind AS 109 / IRACP table at all. Either the window starts at FY2017 or the
      extractors are proven on older filings first — decide with evidence, not by assumption.

## 2. What a golden case is

> A **golden case** is one company at one `as_of` date, with an outcome that became public **after** that
> date, and a set of facts a human has verified against the filing.

Three parts, and the ordering is load-bearing:

1. **The label is an event, not a verdict.** `SEBI adjudication order`, `NCLT admission`,
   `auditor resignation`, `restatement`, `forensic audit ordered`, `delisting`, `promoter share pledge
   invocation`. Each carries a source URL and the date it became public. **A label is never derived from
   this system's output**, and never from a price move alone — a stock halving is not evidence of fraud,
   it is evidence of a stock halving.

   **Two positive classes, because they are not the same claim** (ADR-0062). `fraud` is an authority's
   finding of misstatement; `adverse` is a qualifying governance event nobody has adjudicated — an
   auditor walking out mid-term over unpaid fees, a forensic audit ordered. The firm must not CLEAR
   either, and they are scored separately: recall measured only on adjudicated frauds flatters itself.
2. **`as_of` precedes the revelation by a stated margin** (default 12 months, recorded per case). The
   question the case asks is: *using only what was public then, did the firm see it?* An `as_of` after
   the revelation tests nothing.
3. **The expected outcome is pre-registered** — written into the case file before the pipeline is run on
   it, by whoever verified the facts.

### The negative class is the hard half

A fraud-only set teaches recall and hides the false-positive rate, which is the error that actually
destroys this product: the firm's output is *a rejection with an evidence chain*, and a wrong rejection
of an honest company is worse than a missed fraud, because it is the thing a reader can check.

Negatives are therefore graded, and the **hard** ones carry the weight:

| class | what it is | why it belongs | already have |
|---|---|---|---|
| easy negative | clean company, clean cycle | floor check | Alkyl Amines FY26 |
| **hard: cyclical downturn** | margins and cash yield collapse, no dishonesty | the FY23 HARD_FAIL | Alkyl Amines FY23 |
| **hard: heavy capex** | CWIP large for years, legitimately | `ageing_cwip` | Alkyl Amines FY21-23 |
| **hard: business-model mismatch** | measure calibrated on another model | ADR-0058 | Five-Star FY26 |
| **hard: genuine deterioration** | real stress, honestly disclosed | must REVIEW, not HARD_FAIL | Five-Star FY26 GNPA |
| **hard: recovering book** | metrics improving off a bad year | ADR-0052 | CreditAccess FY26 |

**Six hard negatives already exist with human-verified facts** from this session's real-company work —
including two verified against the companies' own Regulation 52(4) filings, which is an independent
source. That is the seed.

## 3. How companies are selected

Selection bias is the second way a golden set lies. Rules:

1. **Positives come from a register, not from memory.** BUILT: `firm register` enumerates BSE's
   market-wide Regulation 30 announcements by the exchange's own subcategory. 2022-2023 gave **404
   distinct company-events**, of which **73** survived the universe band and **331 exclusions are
   recorded with reasons** in `_excluded.jsonl`. Picking the frauds one already knows selects for famous,
   late-stage, obvious cases — the ones any system catches.

   **The register gives candidates; the label needs reading.** Auditor rotation is mandatory in India, so
   a resignation is not automatically adverse. A keyword classifier called both PC Jeweller and Styrenix
   adverse — it was matching SEBI's mandated disclosure *template*, which every letter contains. Reading
   them gives opposite answers: unpaid audit fees versus a fee dispute the filing explicitly says raises
   no concerns. **Of the twelve largest candidates, exactly one was genuinely adverse.** That low signal
   density is a finding about the register, and it makes the reading step the whole of the selection.
2. **Negatives are matched, not convenient.** For each positive, draw negatives from the same sector,
   size decile and year. Otherwise the set learns "microcap chemicals in 2019" rather than fraud.
3. **Every excluded candidate is recorded with its reason** in `evals/golden_set/_excluded.jsonl`. A
   selection process whose rejections are invisible cannot be audited for bias.
4. **Target 30 cases at roughly 1:2 positive:negative**, built in waves of 6-8 so the harness is proven
   before the manual cost is spent.

## 4. What a human must verify — facts, not verdicts

This is the mechanism that keeps extraction error separable from judgment error. Without it, improving an
extractor looks like improving calibration and vice versa — and this session showed how easily that
happens: the CreditAccess GNPA series was wrong for months while every unit test passed.

A human verifies, **from the filing, with page references**:

- the **inputs** each applicable check consumes (gross advances, gross NPA, allowance, cash, interest
  income, CWIP, receivables, revenue …) — the value and the page it is printed on;
- which mandated disclosures the filing **actually contains** and which it does not;
- the **business model** and, for a lender, the secured share;
- the **label** and its source.

A human does **not** verify "this should be a HARD_FAIL". Verdicts are the system's output and the thing
under test; pre-registering an expected *verdict band* (§6) is a hypothesis, not ground truth.

### Case file schema (`evals/golden_set/<TICKER>-<FY>.yaml`)

```yaml
case_id: XYZ-FY19
ticker: XYZ
as_of: 2019-09-30            # the day the run is frozen at
label: fraud                  # fraud | clean
label_event:                  # omitted for clean cases
  kind: sebi_order
  date: 2021-03-12            # must be after as_of
  source: https://www.sebi.gov.in/enforcement/orders/...
  summary: revenue recognised on circular trades with related parties
lead_months: 18               # as_of -> label_event.date
negative_class: hard_cyclical # for clean cases only
filings:                      # frozen, content-addressed
  - file: XYZ-AR-FY19.pdf
    sha256: 3c38...
    published_at: 2019-08-14
    published_at_basis: exchange-dissemination
verified_facts:               # the human's work, the scoring baseline for extraction
  - metric: balance_sheet:Gross NPA
    period: FY19
    value: 1225.61
    unit: INR_cr
    locator: p.123 l.43
    verified_by: <initials>
    verified_on: 2026-09-02
verified_disclosures:
  present: [related_party, contingent_liabilities]
  absent:  [key_audit_matters]
expectation:                  # PRE-REGISTERED, before the pipeline is run
  verdict_at_worst: HARD_FAIL
  verdict_at_best: REVIEW
  must_flag: [receivables_divergent]
  must_not_flag: []
  rationale: receivables grew 3x revenue for two years, disclosed in the filing
```

## 5. Provenance

The case file is evidence, so it carries the same discipline as a fact: the filing is pinned by `sha256`
so a re-run is bit-identical; `published_at` carries its `_basis`; every verified fact carries the page it
was read from and who read it; the label carries a URL and a date. `evals/` is git-tracked, so every
change to a case — a corrected fact, a re-baselined expectation — is a reviewable diff with a reason.

## 6. How thresholds are calibrated

1. **Split first, and split by company, not by case** — a company appearing at two `as_of` dates must
   fall entirely on one side, or the split leaks. Calibration ⅔, evaluation ⅓, fixed by seed and
   recorded.
2. **Fit only on the calibration split. Report only on the evaluation split.** A number quoted from the
   data it was fit to is not a measurement.
3. **The loss is asymmetric and the ratio is stated.** A false SEVERE on a clean company costs more than
   a missed flag, because the product is a rejection a reader can check and a wrong one discredits every
   other. The starting point is 5:1 against false positives, recorded in config and revisited with
   evidence — not tuned until the answer looks nice.
4. **Per-check operating points, not one aggregate.** Each check is scored only on cases where it was
   *applicable* (playbook ran it, inputs present) — otherwise ADR-0058's suppressions look like misses.
5. **A check that fires on no positive, or on more than a stated share of negatives, is reported
   UNCALIBRATED** and its severity is capped until it earns one. Silence is a result; a check nobody can
   show works should not be able to produce a SEVERE.
6. **Thresholds move in config, never in code**, and every move cites the calibration run that justified
   it.

### CAL-1 — CLOSED 2026-08-31 (ADR-0059), and not the way a threshold question closes
`cash_interest_inconsistent` fired SEVERE on Alkyl Amines FY23 at an implied cash yield of 2.55% against
a 2.60% floor, producing a HARD_FAIL on a company with no fraud, no restatement and no governance event.
The question recorded here was: is the band wrong, the severity wrong, the denominator wrong, or the flag
right?

**None of them. The observation was uninterpretable.** Measuring the whole FY19–FY26 series rather than
the failing year showed the yield is a year of interest over the MEAN of two balance-sheet endpoints, and
Alkyl's cash and bank balances fell 71% during FY23. The same two endpoints support 1.64% and 5.64%
equally. The check now asserts a threshold claim only where every timing story the endpoints tell agrees
with it (§7 of ADR-0059), so FY23 reports UNAVAILABLE naming the balances that would resolve it.
`cash_yield_floor_ratio` was not touched.

**What replaces CAL-1 is worse news, and it belongs here rather than in a footnote.** Eleven of the
twelve company-years the firm can read have endpoint bands too wide to test ANY floor, and the one
positive in the set (PC Jeweller, 5.34% / 5.38% / 4.23%) never approached it. So the threshold is not
vindicated — **it remains completely untested, and the check cannot currently be calibrated at all from
annual filings.** Closing that needs within-year balances (Reg 33 half-yearly balance sheets) or the
cash-and-bank note's current-account/term-deposit split, which is a capability item with a named remedy
rather than a number to argue about. See §6.5: on this evidence the check is UNCALIBRATED.

### CAL-2 — the provision-coverage floor is uncalibrated on either of its two possible measures
Recorded 2026-08-31 (ADR-0060). `provision_coverage_low` divides the WHOLE book's ECL allowance by the
Stage-3 gross; across the five readable lender-years that measure reads 119% / 91% / 55% / 107% / 121%
and the 50% floor has never fired — a lender provisioning a growing performing book clears it
structurally. The stage-3-specific PCR (now read for Five-Star: 54.3% → 51.3% → 41.4%) WOULD fire —
on exactly the lender whose pre-registered case says that firing is wrong, because its book is 99.98%
secured by registered mortgage and no lender discloses collateral value against Stage-3. The measure
question and the collateral gate are one question. The inputs are read and reported (the check's
detail names its measure and prints the PCR and secured share, non-load-bearing); the floor moves only
when a lender positive exists to calibrate against — wave 3's register has the candidates.

## 7. How regression testing uses it

The golden set runs as a **separate, opt-in tier** — `firm eval`, wrapped by `make eval` — never in the
fast unit suite: it needs the PDFs and takes minutes, and a slow default suite stops being run.

Two independent assertions per case, and keeping them independent is the point:

1. **Extraction regression** — every `verified_fact` must be reproduced by the pipeline, to the value and
   the period. A miss is an extraction defect and is reported as such, with the human's page reference
   next to what we read. This is the assertion that would have caught the ADR-0054 year-crossing bug on
   the day it appeared.
2. **Judgment regression** — the verdict must fall inside the pre-registered band, and `must_flag` /
   `must_not_flag` must hold.

A verdict change **fails loudly** and can only be accepted by editing the case file with a reason — the
same discipline as a snapshot test, except the reason is committed. Re-baselining silently is how a
golden set decays into a record of what the system currently does.

`firm eval` reports: per-case pass/fail split by the two assertion types and the confusion matrix by
negative class — so "we got worse at hard cyclical negatives" is visible rather than averaged away.
Per-check operating points arrive with Wave 2, when there are positives to compute them against.

**A recorded failure is not a silent one.** `known_failure` carries the tracking id of an open question
(CAL-1 today). Such a case does not gate a release — but a recorded failure that starts **passing** does,
because a red case nobody notices turning green is how a calibration debt gets forgotten.

**Facts are recorded in the unit the filing PRINTS.** A person writes 44,609.68 lakh because that is what
the page says; the harness converts. Writing the ₹crore equivalent rounded to two decimals is a human
doing arithmetic, and it fails for a reason that has nothing to do with extraction — which is exactly
what happened on the first run.

## 8. Cost, and the honest order of work

PLAN §9 warns this is 3-5× harder than the agent phases and that is not an exaggeration: the manual
verification is the cost, and it cannot be automated without reintroducing the circularity.

Wave 1 (the seed) is cheap because the work is done: **six hard negatives** already have human-verified
facts from this session, two of them cross-checked against the companies' own Regulation 52(4) filings.
Building the harness and the case schema against those, with **zero positives**, is worth doing on its
own — it proves the two-assertion split and it immediately makes the FY23 and Five-Star questions
answerable as regressions rather than arguments.

Wave 2 adds positives from the register (§3), which is where the real cost begins.

## 9. The second instrument: a series sweep (added 2026-08-31, ADR-0059)

Labelled cases are expensive — a person reads a filing, an event has to have happened, and a lead time
has to have elapsed. There is a cheaper instrument that answers a different question, and CAL-1 was
closed by it rather than by the case that recorded it.

> A **series sweep** replays one check across every company-year the firm can read and asks whether the
> spread is explicable. It needs no label, no event and no human verification.

What it is for, and why it is not a substitute for §2: a case asks *did the firm reach the right verdict
on this company?* A sweep asks *is this check measuring anything at all?* The second question is
logically prior, and cheaper, and the golden set kept asking the first one first.

The worked example is CAL-1. Read at FY23 alone, `cash_interest_inconsistent` posed a threshold
question nobody could answer from one observation. Read across FY19–FY26 of the same company it posed
no threshold question at all: the check fires only in years the cash balance moved violently, which is
a property of a two-endpoint average and not of Alkyl Amines. **Same check, same data, opposite
conclusion — the difference is entirely the width of the window the analyst looked through.**

Standing steps, in this order:

1. **Sweep before you calibrate.** For any check about to be tuned, replay it across every readable
   company-year and print value, threshold and — where the input is a rate over a moving balance — the
   band the endpoints support. A check whose spread on one honest company already crosses its own
   threshold is not ready to be calibrated on labelled cases.
2. **A wide band is a capability finding, not a calibration finding.** It names data the firm is not
   reading (here: Reg 33 half-yearly balance sheets, or the cash-and-bank note's split). It belongs in
   the backlog, not in an argument about a number.
3. **Sweep after any threshold change too**, for the same reason §7 re-runs the cases: a number moved
   to fit one company-year should be visible against all the others.

Current sweep, 4 companies × their readable years: **35 flow-over-average-stock rates, 16 (46%) pinned
to within 20% of their own value.** Cost of debt and cash yield are the loose ones; the accrual ratio
behaves. That fraction is itself a metric worth watching — it is the share of the firm's rate
arithmetic that currently means what it says.
