# FORENSIC_METHODOLOGY.md — Reverse-engineered from primary evidence

> **Status:** analysis + *proposed* extensions. Nothing here overrides [`SPEC.md`](SPEC.md). Where this
> doc recommends a change to the firm, it is written as a **proposal** for you to ratify into
> [`DECISIONS.md`](DECISIONS.md) — it does not decide anything by itself.
>
> **Evidence base (grade A — primary documents in repo root):**
> - Hindenburg Research, *"Carvana: A Father-Son Accounting Grift For The Ages"*, 2025-01-02 (5pp dense).
> - Hindenburg Research, *"Sezzle: A Failing 'Buy Now, Pay Later' Platform…"*, 2024-12-18 (3pp dense).
>
> Both are **short-biased activist reports**. Citations below use `[C p.N]` / `[S p.N]` = the report and
> the page it sits on. Every methodological claim traces to a specific finding; where I generalise beyond
> the two reports it is tagged **[inference]** or **[speculation]** per house style (`_shared/epistemics.md`).

---

## 0. Read this first — the honest framing

You asked for a world-class forensic research OS and threw a lot of vocabulary at it. Three things
before the substance, because rubber-stamping the brief would waste your time.

**0.1 — The buzzword audit (what's real vs. noise).** You listed *"Harness, Jailbreak, no Hallucination,
recursive self-improvement, Chain of Thought, Beam Search, Softmax, Transformer"* plus a Hindi list of
five principles. Sorted honestly:

| You said | Verdict | Why |
|---|---|---|
| **Evidence graph + source hierarchy** | **Real, load-bearing, partially built** | This is the spine. SPEC has A/B/C/D grades + provenance (Laws 2, 3). The *graph* (claims ↔ evidence ↔ contradictions) is not yet built. §4 below specifies it. |
| **Multi-agent debate** | **Real, partly built** | SPEC's `red_team` runs *after* the thesis. True adversarial debate (bull vs. bear, forensic veto) is the right upgrade. §5. |
| **Reflection / red-team loops** | **Real, built** | SPEC §7 post-mortem + `red_team` + Brier calibration already are this. Don't rebuild it. |
| **Retrieval-first (sources not memory)** | **Real, built** | Laws 2 & 7 + bronze/silver/gold + point-in-time query layer *are* retrieval-first. This is the firm's whole thesis. |
| **Confidence calibration + verification pipeline** | **Real, built** | `_shared/epistemics.md` + `core/monitoring/brier.py` + the four validators. |
| **Harness** | **Real, built** | SPEC §9 DAG + gates + tracing. |
| **Chain-of-Thought** | Real but trivial | It's a prompting technique, not architecture. The agents already reason step-wise in their `narrative` field. |
| **Recursive self-improvement** | Real but **dangerous if unbounded** | SPEC §7.3 already gates prompt-evolution behind ≥3 clustered lessons + a human PR approval. Keep that leash. Auto-rewriting a forensic agent with no human is how you get a confidently-wrong fraud detector. |
| **Beam search / Softmax** | **Cargo-cult — drop it** | These are decoder internals of an LLM, not design choices for a research platform. "Beam search" *loosely* rhymes with keeping multiple live hypotheses (§3 P1) — but call it hypothesis management, not beam search. Softmax over what? There is no meaningful surface for it here. |
| **Jailbreak** | **Actively wrong — reject it** | A forensic platform's entire value is epistemic discipline (Laws 1–7). "Jailbreaking" the model removes the guardrails that stop it inventing a balance sheet. The correct move is the opposite: *more* constraint, not less. If you meant "make the model willing to make a hard negative accusation," that's a **prompt-role** problem (an adversarial `short_analyst` persona), not a safety-bypass problem. §5. |

**0.2 — The structural mismatch you should decide on.** Your firm (SPEC §1) is a **long** engine: *"can
this compound 5–10x, self-funded, under honest management?"* The two example reports are **short**
activist reports: *"this is a mirage; here's the fraud; insiders are cashing out."* These share forensic
DNA but differ in **goal, evidence sourcing, and output**:

- The firm's forensic layer detects fraud **on the face of the filings** — deterministic math on reported
  numbers (`quality.py`) plus reading the audited notes (ADR-0011).
- **Every headline finding in both reports is invisible on the face of the filings.** The Cerberus
  related-party unmasking came from a **UCC lien search**; "we approved 100% of applicants" came from a
  **former-employee interview**; the 6,776-vs-23,000 merchant gap came from **counting rows on a website**;
  the $542M pledge was in a **footnote on page 42**. None of these live in screener.in or in a clean-read
  of the annual report.

**The single most important conclusion of this whole exercise:** *the firm as specced today would give
Carvana a soft PASS and miss the entire Sezzle thesis*, because its data layer stops at the filing. The
gap is not analytical horsepower — it is **evidence sourcing**. §6 makes this concrete; §7 proposes the
fix. Per your memory note that forensic fraud detection is the headline priority, I recommend folding the
short-seller's *investigative sourcing* into the existing forensic tier rather than building a separate
"short mode." (Say if you'd rather have a standalone activist product; that changes the roster.)

**0.3 — What this doc is.** Not a summary of the reports. A reverse-engineering of *how they were built*,
turned into (a) named reusable patterns, (b) an evidence-graph spec, (c) a workflow mapped to your
pipeline, (d) a gap analysis against your firm, and (e) prioritized, phase-aware proposals. It optimizes
for institutional accuracy over speed, as you asked.

---

## 1. Research philosophy (inferred from the artifacts)

What both reports *do*, not what they *say* they do:

1. **Start from a divergence, not a company.** The thesis is always a **contradiction**: a number moving
   the opposite way from the reality that should drive it. Carvana: profitability *improves* while used-car
   prices fall 20.3% and subprime delinquencies exceed the GFC `[C p.1]`. Sezzle: revenue +71% and net
   income +1,093% while merchants −51% and customers −20% `[S p.1]`. **The gap is the hypothesis.** [inference:
   this is the generative engine — everything downstream is built to explain or destroy the gap.]

2. **Distrust the number; find the mechanism.** They never stop at "earnings look manufactured." They name
   the **lever**: gain-on-loan-sale timing, related-party warranty pull-forward, `held-for-sale`
   classification to avoid CECL reserves `[C p.4]`; provision cuts 3.5%→1.2% of merchant sales `[S p.1]`.
   A red flag without a named mechanism is not shippable.

3. **The most trusted evidence is the evidence the target cannot retract.** Ranked by how they weight it:
   (i) **government/public records** the target didn't author — UCC liens, state registries, court
   dockets, NYSE disciplinary records, ISDA registrations `[C p.2, p.4]`; (ii) **the target's own words in
   binding filings**, especially where they contradict management's spoken claims (10-K says DriveTime deals
   are *"not always negotiated at arm's length"* while IR emails call them *"arm's length"* `[C p.3]`);
   (iii) **third-party quantitative data** (Morningstar/S&P ABS reports, Manheim, Fitch `[C p.1,3]`);
   (iv) **named-but-anonymous human sources** — former employees/counterparties — used to explain
   *intent and mechanism*, never as the sole pillar for a number.

4. **Avoid speculation by construction, then hedge the residue in law.** Numbers come from filings and
   third-party datasets (never invented). Where they must infer, the language degrades deliberately:
   *"appears to," "suspected," "we believe," "indicating,"* and they **tell the reader how to reproduce
   the search** (*"navigate to Arizona's UCC Lien Search and search…"* `[C p.5 fn.6]`). This is the same
   discipline as your `_shared/epistemics.md` three-state model (`supported`/`refuted`/`unknown`) — they
   just enforce it with libel exposure instead of a Pydantic schema.

5. **Conviction is built by triangulation, not by a single smoking gun.** No one finding carries the
   thesis. Conviction = *N independent sources of different grades pointing the same way* (filing + trust
   report + former-employee interview + competitor interview + litigation exhibit). This is exactly your
   "evidence count × grade" confidence rule — applied to a graph.

---

## 2. The evidence-type taxonomy (extends the firm's A/B/C/D)

Your grades (SPEC §4): **A** audited filing · **B** exchange/rating · **C** company claim · **D** media.
That taxonomy is built for a *long analyst reading filings*. The reports use a wider universe. Proposed
extension — a second axis: **source class**, orthogonal to reliability grade.

| Source class | Instances in the reports | Reliability | Verifiability | Firm status |
|---|---|---|---|---|
| **Binding filing (issuer-authored)** | 10-K/10-Q, proxy footnote p.42 pledge `[S p.1]`, ABS trust reports `[C p.3]` | A | High (public) | ✅ ADR-0011 |
| **Government / public record (3rd-party-authored)** | AZ UCC liens, MD entity registry, ISDA, NYSE discipline, court dockets `[C p.2,4]` | **A** (target can't retract) | **High + replicable** | ❌ **not sourced** |
| **Third-party quantitative dataset** | Morningstar/S&P ABS pre-sale, Manheim index, Fitch, CarEdge `[C p.1,3]`; FactSet Form-4 counts `[S p.1]` | B | High | ⚠️ partial (screener only) |
| **Litigation instrument** | 332-pp class action w/ 12 confidential witnesses `[C p.3-4]`; Sliwa v. Sezzle `[S p.2]` | B–C (allegation, not finding) | Medium | ❌ not sourced |
| **FOIA / regulatory-intelligence** | Disclosure Insight: undisclosed SEC investigations `[C p.4]` | C | Low (2nd-hand) | ❌ not sourced |
| **HUMINT — former insider** | "approved 100% of applicants" `[C p.3]`; "Fight Club… we don't talk about DriveTime" `[C p.3]` | C (about intent/mechanism) | Low (anonymous) | ❌ not sourced |
| **HUMINT — counterparty/competitor** | Wells Fargo, Ally, CarMax execs `[C p.2,3]` | C | Low | ❌ not sourced |
| **Ground / product truth** | website merchant count 6,776 vs 23,000 `[S p.1]`; Target/Lamps Plus checkout has no Sezzle `[S p.2]` | B (directly observed) | **High + replicable** | ❌ not sourced |
| **Consumer-complaint corpus** | BBB 1.1★/986 complaints, Trustpilot, Reddit, CFPB spike `[S p.2]` | D individually, **C in aggregate** | Medium | ❌ not sourced |
| **Web archive** | Wayback: Grant Thornton's removed DriveTime tribute `[C p.4]` | B (timestamped) | High | ❌ not sourced |

**Rules the reports follow (adopt these into `epistemics.md`):**
- **Government/public records and directly-observed ground truth outrank issuer filings** when they
  conflict, because the issuer didn't author them and they're independently replicable.
- **HUMINT never carries a *number*.** It carries *intent, mechanism, and where to look next.* A number
  always comes back to a filing or a dataset. (This is your Law 1, generalised to human sources.)
- **A single anonymous source is a lead, not a pillar.** It ships only when a document or dataset
  corroborates it. Both reports pair every damning quote with a filing (e.g. the "extend-and-pretend" quote
  is backed by S&P extension data: 1.97%→4.18%, largest of 23 issuers `[C p.3]`).
- **Complaint corpora are grade-D individually but grade-C in aggregate** if volume + trend + independent
  venues agree (BBB *and* Trustpilot *and* Reddit *and* CFPB `[S p.2]`).

---

## 3. The reusable investigation patterns

Each pattern: **the move → evidence in both reports → why it works → automation suitability → the AI
failure mode → firm status.** These are the transferable "how they think," industry-agnostic.

### P1 — The Divergence Hypothesis (the generative engine)
**Move.** Find a headline metric moving *opposite* to the exogenous force that should drive it; make that
gap the falsifiable hypothesis. **Evidence.** Carvana GPU +209% while Manheim −20.3% `[C p.1]`; Sezzle
provisions −66% (3.5%→1.2%) *into* a subprime book, then revenue +71% while its own funnel shrinks
`[S p.1]`. **Why.** Exogenous forces (used-car prices, delinquency cycles) are not manipulable by the
issuer; a metric decoupling from them is either a genuine edge or an artifact — and the base rate favours
artifact. **Automation: HIGH** — this is deterministic once you have the external series. **AI failure:**
inventing the external series or mis-signing the expected relationship. **Firm status: ❌** — the firm
has no exogenous/macro series wired into `quality.py`; `macro_strategist` is top-down narrative, not a
divergence detector. **Proposal P1 → §7.**

### P2 — The Insider-Cashout Overlay (the clock)
**Move.** Overlay insider selling / pledging / margin-loan extraction on the promotional narrative and the
stock chart; treat concentrated insider exit as the thesis's timing signal. **Evidence.** Garcia II sold
$3.6B (Aug'20–Aug'21) → stock −99%; now +$1.4B again, near-daily `[C p.1-2]`. Sezzle: $542M pledged =
30% of the company, buried in a p.42 footnote `[S p.1]`; $71M sold in 2024; pre-IPO investor −87% via 62
Form 4s after a board resignation `[S p.1]`. **Why.** Margin-loan pledges extract cash **without a Form 4
and without selling** — the quietest exit. Concentrated, well-timed insider exit is the highest-signal
"management knows" indicator. **Automation: HIGH** for Form-4/pledge extraction; **MEDIUM** for the
timing-overlay judgment. **AI failure:** treating routine 10b5-1 selling as signal; missing pledges hidden
in footnotes (a parsing/recall failure). **Firm status: ⚠️** — `ownership_flows_analyst` tracks
shareholding deltas + `management_analyst` tracks pledges, but **pledge-as-hidden-exit** and
**margin-loan-in-a-footnote** are not first-class signals, and the "insider-exit-as-clock" overlay is absent.

### P3 — The Related-Party Siphon / Prop
**Move.** Map the private-entity constellation around the issuer; look for value **flowing in to flatter
public numbers** (prop) or **out to enrich insiders** (siphon). **Evidence (a masterclass).** DriveTime
(CEO's father's private co.) is used to: pull warranty profit-share *forward* (~58% more warranty income/unit
than CarMax `[C p.3]`); absorb inventory at a premium instead of Carvana marking it down ($105M over 3yrs
`[C p.3]`); service loans so delinquencies become *extensions* not defaults `[C p.3]`; and — per the class
action — a "sham" round-trip that was 169% of Q4'21 unit-sales growth `[C p.4]`. **Why.** A private
related party has no disclosure obligation, so it's a one-way mirror: it can eat losses to make the public
co. look good while the insider profits via public stock. The CarMax exec's line captures the logic:
substantial losses at private DriveTime are rational if the owner "benefits with his stock options… on
Carvana" `[C p.3]`. **Automation: MEDIUM** — the related-party *map* can be built from filings + registries;
the *quantification of the subsidy* needs a comparable (CarMax's disclosed $949/unit) and judgment.
**AI failure:** accepting "arm's length" boilerplate; failing to connect the private entity across
documents. **Firm status: ⚠️** — `forensic_accountant` does a "related-party map" but only from the
filing; it has no registry/graph layer and no "prop vs siphon" quantification.

### P4 — Say-vs-File-vs-Reality triangulation
**Move.** For each management claim, pull the *same fact* from three layers — what they **said** (call/IR),
what they **filed** (10-K), what is **observable** (data/product/records) — and surface the contradictions.
**Evidence.** "We don't take credit risk over an extended period" (CEO) vs. on-balance-sheet loans +50% to
$553M (filing) `[C p.4]`. IR: DriveTime deals are "arm's length" vs. 10-K: "not always negotiated at arm's
length" `[C p.3]`. "Quality not impacted" (CFO) vs. former reconditioning lead: hidden "economy line" with
lowered standards `[C p.4]`. Sezzle "confidence in our underwriting" vs. provisions +130% on a +6% book
`[S p.1]`. **Why.** Spoken claims are grade-C data *about management*; the delta between what they say and
what they must legally file is itself the finding. **Automation: HIGH** — this is a text-diff/entailment
task across three corpora. **AI failure:** the highest — LLMs paraphrase a contradiction into agreement,
or hallucinate a filing statement. Must be citation-locked. **Firm status: ⚠️** — `transcript_analyst`
tracks guidance drift and `management_analyst` scores promise-vs-delivery, but neither does the explicit
**claim ↔ filing ↔ observable** three-way join. **This is your highest-ROI, most-automatable gap.**

### P5 — The Quiet-Change Detector
**Move.** Track what *stopped* or *got quieter* — deletions, redactions, dropped guidance, silent
partnership deaths, accounting-policy changes. **Evidence.** Ally agreement amended 5× in 2 years, each
redacting more (33 metrics in the Jan-2024 amendment) `[C p.2]`; the new $800M buyer never mentioned on
earnings calls `[C p.2]`; Grant Thornton's DriveTime tribute *removed* from its site (caught via Wayback)
`[C p.4]`; Sezzle's Target/Lamps Plus/Bellacor partnerships announced loudly, ended silently `[S p.2]`.
**Why.** Fraud is rarely a false positive statement; it's usually an *omission* or a *quiet reversal*.
Absence is the signal. **Automation: MEDIUM-HIGH** — redaction counts, doc-to-doc diffs, archive snapshots,
"announced-then-absent" partnership tracking are all mechanisable. **AI failure:** can't detect what isn't
there without a prior snapshot to diff against; needs point-in-time archives (your Law 3 infrastructure
helps here). **Firm status: ❌** — no diffing, no archive layer, no "silent reversal" tracker.

### P6 — Unmasking the undisclosed counterparty (the OSINT chain)
**Move.** When the issuer hides a counterparty, reconstruct identity from a *chain* of independent public
records until it resolves to a name. **Evidence (the set-piece).** Carvana claims the $800M loan buyer is an
"unrelated third party." Chain: (1) filing dates of the receivable sales → (2) two "Towd Point Auto" trusts
filed AZ UCC liens on those exact dates → (3) MD registry: both trusts' principal office = 875 Third Ave,
10th floor = Cerberus HQ → (4) ISDA registration used `cerberusswaps@cerberus.com` + a Cerberus MD's name →
(5) Carvana director **Dan Quayle** is Cerberus's Chairman of Global Investments → conclusion: *undisclosed
related party* → (6) corroborating tell: Quayle sold ~half his Carvana stake the same month as the first
transaction `[C p.2]`. **Why.** Each link is individually weak; chained, they're near-conclusive, and
every link is replicable by a third party (they publish the search steps). **Automation: MEDIUM** — each
lookup is an API/scrape (registry, UCC, ISDA, litigation); **the chaining and the "does this resolve to a
name?" judgment is where a human/agent adds value.** **AI failure:** fabricating a registry hit or a link
that doesn't exist — catastrophic here; every hop must be a stored artifact with a URL. **Firm status: ❌**
— no public-records adapters, no entity-resolution graph.

### P7 — Earnings-quality accounting levers (the on-filing forensics)
**Move.** Enumerate the specific accounting choices that convert reality into reported profit. **Evidence.**
(a) **Reserve suppression** — `held-for-sale` classification ⇒ no CECL loss reserves on a growing $553M book
`[C p.4]`; Sezzle cutting provisions to hit profitability `[S p.1]`. (b) **Cookie-jar timing** — warehousing
loan sales across the quarter line to "move very large amounts of income" `[C p.4]`. (c) **Cost
reclassification** — dumping ~$390M/yr of selling costs (warranty, outbound logistics, title/reg) into SG&A
to inflate Retail GPU by ~34.5% vs. peers `[C p.4]`. (d) **Revenue pull-forward** — recognising warranty
profit-share up front "to the extent probable it won't reverse" `[C p.3]`. (e) **Gain-on-sale dependence** —
gain-on-loan-sale = 2.2× net income `[C p.1]`. **Why.** These are the mechanisms behind P1's divergence.
**Automation: HIGH** for the ratio-level tells (gain-on-sale/NI, provision/book growth divergence,
CFO/PAT), **LOW** for the reclassification detection (needs peer-comparable cost structure + notes reading).
**AI failure:** misreading accounting-policy language (moderate-to-high). **Firm status: ✅/⚠️** — this is
`quality.py`'s home turf (CFO/PAT, accruals, cash-reality checks, ADR-0006). **But note:** your checks are
built for *industrials*; a **lender/BNPL/originate-to-sell** model needs the ADR-0002 financial branch
*plus new checks* (gain-on-sale reliance, provision-vs-book divergence, reserve-model choice). §7.

### P8 — Ground / product truth
**Move.** Go verify the business physically/digitally: count the thing, use the product, call the customer.
**Evidence.** Sezzle claims 23,000 merchants; the website's own store list shows **6,776** `[S p.1]`.
Checkout pages at Target/Lamps Plus/Bellacor show **no Sezzle option**; they **phoned Lamps Plus and
Ministry of Supply to confirm** `[S p.2]`. **Why.** Directly-observed reality is grade-B, replicable, and
immune to the issuer's framing. **Automation: HIGH** for web-scrapeable counts/integration checks; **LOW**
for phone calls / physical visits (human). **AI failure:** none unique if it's just structured scraping —
but the agent must not *infer* a merchant count it didn't actually enumerate. **Firm status: ❌** — the
firm reads filings, never the product. In India this maps to: GST/e-way-bill volumes, plant satellite
imagery, dealer/distributor counts, app-download and review trends, job-posting velocity.

### P9 — The gatekeeper-failure map
**Move.** Assess whether the people *supposed* to catch this are independent and competent. **Evidence.**
Carvana's "independent" audit committee has two ex-DriveTime directors; Greg Sullivan was NYSE-suspended in
1992 for repaying Garcia II in violation of a prohibition, then was DriveTime's president `[C p.4]`; auditor
Grant Thornton is mid-tier, 10+ years, and also audited DriveTime `[C p.4]`. Sezzle's "Head of Risk" for a
subprime lender had **no prior corporate experience** (ex-teaching specialist) `[S p.1]`. **Why.** Fraud
needs failed gatekeepers; independence-on-paper ≠ independence-in-fact. **Automation: MEDIUM** — board/
auditor tenure + interlock detection from proxies + registries + LinkedIn is largely mechanisable.
**AI failure:** conflating title with competence; missing an interlock that requires cross-doc entity
resolution. **Firm status: ⚠️** — `management_analyst` covers board independence + auditor tenure, but not
**director-interlock graphs** or **competence red-flags**.

### P10 — Base-rate & historical-analogy anchoring
**Move.** Anchor the fraud to a known pattern and state the prior. **Evidence.** Carvana ≈ "early 2000s
mortgage-backed securities" (former director) `[C p.3]`; Sezzle's conclusion generalises: "every couple of
years a slew of firms go public claiming… the holy grail of high-risk lending… there is no new magical
lending model" `[S p.2]`. **Why.** It sets the reader's prior against the promotion, and it's exactly your
house rule *"state the base rate first."* **Automation: MEDIUM** — requires a curated case library.
**AI failure:** false analogy / confabulated base rate. **Firm status: ✅ (principle)/❌ (data)** — the
principle is in `house_style.md`; the **fraud-archetype case library** to compute the base rate doesn't
exist. This is what your `evals/golden_set` should double as.

---

## 4. The evidence graph (spec)

This is the "evidence graph + source hierarchy" you asked for, made concrete. It is the missing data
structure that turns triangulation into something auditable and prevents unsupported conclusions.

**Node types:** `Claim`, `Evidence`, `Entity` (person / company / trust / fund), `Event` (dated).
**Edge types:** `supports`, `refutes`, `depends_on`, `corroborates`, `contradicts`, `affiliated_with`,
`controls`, `transacted_with`, `derived_from`.

Every **Claim** node carries (this generalises your `_base.py` `Citation`/`Confidence`/`OpenQuestion`):
```
Claim {
  id, statement, claim_type: {observation|inference|speculation},   # house-style separation, enforced
  supporting: [evidence_id...], refuting: [evidence_id...],
  confidence: float[0,1],            # = f(evidence count × grade × independence), never vibes
  source_reliability: A|B|C|D,       # weakest grade among load-bearing support
  source_class: <§2 taxonomy>,
  freshness: as_of vs published_at,  # Law 3: no evidence with published_at > as_of
  depends_on: [claim_id...],         # so a refuted parent cascades to children
  open_questions: [str...],          # non-empty (house style)
  replication: str                   # "how a third party reproduces this" (the Hindenburg tell)
}
```
**Hard invariants (validators, blocking):**
- **No conclusion without a path to grade ≤B evidence.** A `Claim` used in the thesis whose entire support
  is grade-C/D → fails (your Law: no pillar on grade-D alone). Generalises `citation_validator`.
- **Contradictions are surfaced, never silently resolved** — a `Claim` with non-empty `refuting` must be
  explicitly adjudicated in prose (generalises `consistency_validator`).
- **Every number node traces to `core/compute` or a named dataset** (Law 1/2).
- **Refutation cascades:** if a parent `Claim` flips to `refuted`, every `depends_on` child is re-opened.

An **Entity graph** side-car powers P3/P6/P9: `affiliated_with`/`controls`/`transacted_with` edges built
from registries + proxies, so "undisclosed related party" becomes a *graph query* (is there a path from
the counterparty to an insider?) rather than a lucky catch.

---

## 5. Multi-agent architecture — the deltas from your roster

You already have 14 agents + the `_shared` standards + validators. **Do not rebuild them.** The reports
imply a small number of *investigative* roles the current roster lacks, plus a debate structure.

**New agents (proposed):**
| Agent | Mission | Inputs | Tools | Limitation / veto |
|---|---|---|---|---|
| `osint_records_analyst` | Resolve entities & unmask undisclosed counterparties via public records (P6, P9) | entity names, filing dates | registry/UCC/court/ISDA/Wayback adapters | Output is *leads + artifacts*, never a number; every hop stored with a URL |
| `ground_truth_analyst` | Verify the business physically/digitally (P8) | company, product URLs, claimed counts | web scrape, app-store, review APIs, (human) call scripts | Must *enumerate*, never estimate a count it didn't observe |
| `humint_synthesizer` | Structure interview evidence into claims about *intent/mechanism* (P3, P4, P7) | interview notes | — | **Forbidden from sourcing any number**; single source = lead not pillar |
| `divergence_scanner` | Deterministic P1: flag metric-vs-exogenous decouplings | computed metrics + external series | `core/compute` | Pure code; no LLM number (Law 1) |
| `short_analyst` (debate) | Argue the *fraud* case as hard as possible; the adversary to `thesis_synthesizer` | full evidence graph | — | The "willing to make the hard accusation" role you meant by "jailbreak" — a **persona**, not a safety bypass |

**Debate structure (the real "multi-agent debate"):** `thesis_synthesizer` (bull) ⟷ `short_analyst`
(bear) argue over the **same evidence graph**; `forensic_accountant` holds the **absolute veto** (already
in its spec); `red_team` then attacks the *winner*. The disagreement itself is logged as `contradicts`
edges — you get the debate transcript as graph state, not as lost prose. This upgrades SPEC §9's "Tier-3
sequential" into a genuine adversarial round while keeping the DAG explicit.

**Communication protocol:** unchanged — agents exchange **JSON only** (Law 4), now specifically
**evidence-graph fragments** (Claim/Evidence/Entity nodes), never prose.

---

## 6. Gap analysis — what the firm would MISS today (the payoff section)

Run the two targets through the firm *as specced* and mark what survives:

| Finding (the actual thesis driver) | Source class needed | Would the firm catch it today? |
|---|---|---|
| Carvana profit ↑ while used-car prices ↓20.3% (P1) | exogenous series | **No** — no macro/price series in `quality.py` |
| Gain-on-loan-sale = 2.2× net income (P7) | 10-Q line items | **Partial** — only if a "gain-on-sale reliance" check exists (it doesn't yet) |
| $800M loans to undisclosed Cerberus-linked buyer (P6) | UCC + registry + ISDA chain | **No** — no public-records adapters |
| "Approved 100% of applicants" / lax underwriting (P4/P7) | former-employee HUMINT | **No** — no HUMINT channel |
| DriveTime warranty pull-forward / inventory dumping (P3) | 10-K notes + comparable + HUMINT | **Partial** — narrative RP map exists; no prop/siphon quantification |
| Retail GPU inflated 34.5% via SG&A dumping (P7) | notes + peer cost structure | **No** — needs cross-peer cost reclassification detection |
| Sezzle $542M pledge in a p.42 footnote (P2) | proxy footnote | **Partial** — depends on footnote-level extraction recall |
| Sezzle 23,000 vs 6,776 real merchants (P8) | website enumeration | **No** — firm never reads the product |
| Sezzle partnerships announced-then-dead (P5) | press-release vs checkout diff | **No** — no quiet-change detector |
| Provisions +130% on a +6% book (P1/P7) | 10-Q, deterministic | **Yes** — this one the firm *can* catch (divergence in reported numbers) |
| Audit-committee/DriveTime interlocks (P9) | proxy + registry + LinkedIn | **Partial** — independence noted, interlocks not graphed |

**Score: of ~11 thesis drivers, the firm as-specced clearly catches ~1–2, partially catches ~4, and
misses ~5.** The misses are *precisely* the off-filing investigative findings. That is the case for §7.

---

## 7. Proposals (prioritized, phase-aware — respecting "don't skip phases")

Ordered by ROI-per-unit-effort. **None of these authorise skipping the current Phase 0→1 gate.** They
slot into later phases; a few are cheap enough to land now.

**Tier 0 — ✅ BUILT & VALIDATED (2026-07-30).** Implemented in `core/compute/quality.py` (originate-to-sell
block) and `core/compute/divergence.py`; thresholds in `config/thresholds.yaml`; ratified as ADR-0012/0013/
0014; 100% compute coverage retained. Validated live on real primary-source data — see
[`VALIDATION_TIER0.md`](VALIDATION_TIER0.md) (PASS on Bajaj Finance, REVIEW on CreditAccess Grameen's FY25
stress; no false positive; nothing fabricated). Original spec of the two items:
1. **New `quality.py` checks for originate-to-sell / lender models** (extends ADR-0002/0006): `gain_on_sale
   / net_income` ratio; `provision_growth vs loan_book_growth` divergence; reserve-model flag
   (held-for-sale ⇒ no CECL); revenue-recognition-pull-forward flag. Thresholds → `config/thresholds.yaml`.
   *Acceptance:* on a synthetic BNPL with provisions +130%/book +6%, the check fires. 100% coverage (Law 1).
2. **`divergence_scanner` (P1) as pure code** + a small `config/exogenous.yaml` of external series
   (used-car index, sector delinquency, commodity spreads) with `published_at`. *This is the highest-value
   deterministic add* and it's testable offline.

**Tier 1 — Phase 2/3 (the evidence graph + the say-vs-file join):**
3. **Evidence-graph module** per §4 — ✅ **core BUILT (2026-07-30):** the data model
   (`schemas/evidence.py`: `EvidenceClaim`/`Evidence`/`Entity`/`EvidenceEdge`/`EvidenceGraph`, composing
   the `_base.py` provenance primitives) and the deterministic blocking invariants
   (`core/validators/evidence_graph.py`: R1 no load-bearing conclusion without grade-A/B support · R2
   contradictions must be adjudicated · R3 numbers need provenance · R4 refutation cascade · R5 no
   dangling refs · R6 point-in-time). 100% covered; the Carvana Cerberus-related-party chain is modelled
   as a test and validates clean. **Still to do:** graph-query helpers (entity-path search for P6/P9) and
   wiring agents to emit/consume graph fragments (that part is genuinely Phase 2/3 — agent tier).
4. **P4 `claim ↔ filing ↔ observable` triangulator** — highest-automation forensic win; a citation-locked
   entailment pass over (transcript, filing, dataset). Wire into `transcript_analyst`/`management_analyst`.
5. **Footnote-level extraction hardening** (P2) — the $542M pledge lived on p.42; extraction recall on
   proxy/annual-report footnotes must be measured, not assumed (ADR-0011 already flags PDF-table noise).
   *Partial (2026-07-30, ADR-0015):* the ingestion **plumbing** is now hardened — `adapters/base/extract.py`
   (OCR fallback + "unreadable = signal, not blank"), `adapters/base/sourcing.py` (primary-first grade
   policy, secondary-only flag), and `filings.disclosure_gaps()` (missing mandated disclosure → flag).
   **Still open:** provenance-locked *numeric* table extraction (bind each figure to doc_id+page).

**Tier 2 — Phase 3/4 (investigative sourcing — the real gap, real work):**
6. **Public-records adapters** (`adapters/india/registries.py`): MCA/ROC (corporate structure), CERSAI
   (charges/liens — the India UCC analogue), NCLT/court dockets, SEBI orders, GST where available. This is
   the P6/P9 backbone. **This is genuinely hard and is where an activist edge actually lives.**
7. **`ground_truth_analyst` (P8)** — dealer/distributor counts, app-store trends, review corpora, job-post
   velocity, plant satellite imagery. India-specific, behind `adapters/india/`.
8. **`osint_records_analyst` + Entity graph** (P6/P9) — director-interlock detection, undisclosed-RP path
   queries.
9. **Quiet-change detector (P5)** — doc-to-doc redaction/guidance diffs + web-archive snapshots; leans on
   your existing point-in-time infrastructure (Law 3).

**Tier 3 — Phase 4+ (judgment & structure):**
10. **`short_analyst` debate persona + adversarial round** (§5) — the correct reading of your "jailbreak."
11. **HUMINT channel** (`humint_synthesizer`) — structured, number-forbidden. Mostly a *process + schema*,
    since sourcing humans is manual. Ships last because it's the least automatable and the highest legal-risk.
12. **Fraud-archetype case library (P10)** — dual-purpose with `evals/golden_set`; compute base rates from it.

**Legal safeguard (cross-cutting, non-optional):** the firm's output boundary (SPEC §1: "never emits buy")
has a mirror on the short side — **never emit an accusation of fraud as fact.** Adopt the reports'
discipline as a validator: forensic conclusions render as *"appears to / suspected / the evidence indicates,
and here is how to reproduce it,"* graded, with the disconfirming search shown. A `legal_framing_validator`
should flag any forensic claim stated as unhedged fact without a grade-≤B path. This is `hedge_detector`'s
inverse and equally load-bearing.

---

## 8. Investigation workflow, mapped to your pipeline

Hindenburg's implicit workflow vs. SPEC §8 stages. Per stage: **automation suitability** and **where a
human is mandatory.**

| Their stage | Your SPEC §8 analogue | Automation | Human-mandatory? |
|---|---|---|---|
| Tip / narrative discovery (dozens flagged Carvana; East 72 letter on Sezzle) | *(missing)* — add a lead intake | LOW | Yes (judgment on what to chase) |
| Divergence hypothesis (P1) | Stage 2 forensic quick-kill | HIGH | No |
| Public-data collection | Stage 0–1 ingest (bronze) | HIGH | No |
| On-filing accounting analysis (P7) | Stage 2 + `forensic_accountant` | HIGH | Review |
| Related-party / corporate-structure (P3/P6/P9) | `forensic_accountant` (partial) | MEDIUM | Yes (the "is this a name?" call) |
| OSINT public records (P6/P9) | *(missing)* → Tier-2 proposal | MEDIUM | Yes (chain adjudication) |
| HUMINT interviews (49 for Carvana) | *(missing)* → Tier-3 | LOW / **Impossible** to automate the interview | **Yes, entirely** |
| Alt / third-party data (P1/P8) | *(missing)* → Tier-0/2 | HIGH | No |
| Ground / product verification (P8) | *(missing)* → Tier-2 | HIGH (web) / **Impossible** (site visit) | Partial |
| Cross-validation / triangulation (P4) | `consistency_validator` (partial) | HIGH | Review |
| Valuation + insider-cashout clock (P2) | Stage 6 `valuation_modeler` | MEDIUM | Review |
| Adversarial debate (§5) | Stage 7 `red_team` (partial) | MEDIUM | Review |
| Legal review | *(missing)* → §7 legal validator + human counsel | LOW | **Yes** (an accusation is libel exposure) |
| Publication | Stage 8 report | HIGH | **Yes** (final sign-off) |

---

## 9. AI failure modes & safeguards (summary)

The recurring places an LLM will hurt a forensic system, ranked by damage:
1. **Fabricating a public record / registry hit / filing quote (P6, P4)** — *catastrophic.* Safeguard:
   every evidence node stores the raw artifact + URL; a fetch that returned nothing → `unknown`, never a
   confident node. No node, no claim.
2. **Paraphrasing a contradiction into agreement (P4)** — the say-vs-file join must be citation-locked and
   quote-exact, verified by `arithmetic_validator`'s textual cousin.
3. **Misreading accounting-policy language (P7)** — moderate-high; keep the *numbers* deterministic
   (`quality.py`) so the LLM only narrates the mechanism, never derives the figure (Law 1).
4. **False confidence from a single anonymous source (HUMINT)** — enforce "single source = lead, not
   pillar"; confidence caps until a document corroborates.
5. **False historical analogy / confabulated base rate (P10)** — base rates come from the case-library
   dataset, not from the model's memory (retrieval-first, as you asked).
6. **Losing the thread across a long chain (P6)** — the evidence graph *is* the anti-context-loss
   mechanism: the chain is state on disk, not tokens in a window. (This is your "context = RAM, project =
   hard drive" principle, implemented.)
7. **Confusing "willing to accuse" with "unconstrained" (the jailbreak trap)** — the `short_analyst`
   persona is adversarial *within* the guardrails; the veto and the legal-framing validator stay on.

---

## 10. Hidden-process inference & how much becomes public

What almost certainly existed behind these reports but wasn't shown [inference from the artifacts]:
- **An interview program with source management** — 49 interviews (Carvana) over 4 months implies
  scheduling, transcripts, consent/anonymity handling, and a credibility grade per source. Only ~20–30
  quotes surfaced.
- **A working evidence repository** keyed by claim, with far more leads than made the cut (the report is
  the *surviving* subset).
- **Financial models** for every quantified estimate: the $897/unit GPU adjustment, the 30% warranty
  attach-rate, the $390M annualisation, the $427M insider-gain calc — each is a spreadsheet with assumptions
  (they footnote the method, e.g. fn.23 `[C p.5]`).
- **A legal review pass** that set every hedge ("appears," "suspected," "we believe") and every "the
  company should clarify" — libel-proofing, not throat-clearing.
- **Hypothesis revisions** — leads that died (the report only shows what corroborated).
- **A short book established before publication** (disclosed) — the timing of publication is itself part of
  the process.

**Estimated public fraction: ~5–15% of total research effort surfaces in the report** [speculation —
consistent with the 4-month/49-interview cost vs. the ~5 pages of output, but not independently verified].
The implication for the firm: budget for the 85–95% that stays internal — the working-paper trail,
source management, and killed hypotheses — which is exactly what your `runs/` trace + evidence graph +
`data/gold/rejected/` are for. Build the iceberg, not just the tip.

---

## 11. What to take to `DECISIONS.md` (if you ratify)

Candidate ADRs, in priority order: (1) **originate-to-sell / lender forensic checks** in `quality.py`
[Tier-0]; (2) **exogenous-series divergence scanner** [Tier-0]; (3) **evidence-graph module + invariants**
[Tier-1]; (4) **say-vs-file-vs-observable triangulator** [Tier-1]; (5) **public-records adapters for India
(MCA/CERSAI/NCLT/SEBI)** [Tier-2 — the real activist edge]; (6) **legal-framing validator** [cross-cutting];
(7) **`short_analyst` adversarial debate round** [Tier-3]. Each should carry its own acceptance test in the
style of SPEC §11 before it's built.
