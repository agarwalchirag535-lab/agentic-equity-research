# VALIDATION_TIER0.md — live primary-source test of the new forensic checks

> **What this is.** A calibration record: the Tier-0 forensic checks
> (`core/compute/quality.py` originate-to-sell block + `core/compute/divergence.py`) run against **real,
> primary-source** figures for two Indian lenders, to prove the checks (a) don't false-positive on a
> quality name and (b) fire on genuine stress — using the real thresholds from
> [`config/thresholds.yaml`](../config/thresholds.yaml).
>
> **What this is NOT.** Not investment research, not a verdict on either company, **not an accusation of
> any wrongdoing.** A `REVIEW` flag means "a deterministic signal warrants a human/forensic look" — it is
> the opposite of a conclusion. Per Law 1, these checks surface signals; they never conclude fraud.
>
> **Sourcing discipline (project-owner directive).** Every figure below is verbatim from a **company-issued
> primary document** (audited results / the company's own investor presentation on its own domain), never
> an aggregator. Where a required input was not disclosed in the primary source, it is reported
> `UNAVAILABLE` and **not estimated**. Zero figures are derived or invented.

---

## A) Bajaj Finance — false-positive-resistance test (a high-quality large-cap NBFC)

**Primary source.** Bajaj Finance Q4 FY25 investor presentation, published on the company CDN
(`cms-assets.bajajfinserv.in`), 29 Apr 2025. This "international" deck is denominated in **USD MM**;
growth rates and ratios used by the checks are unit-invariant.

| Figure (verbatim) | FY25 | FY24 | Source |
|---|---|---|---|
| AUM | $47,897 MM | $38,000 MM | summary series, deck p.~70 |
| Loan losses & provisions | $916 MM | $532 MM | narrative: "…for FY25 was $916 MM as against $532 MM in FY24" |
| Profit after tax | $1,929 MM | $1,661 MM | P&L summary series |
| GNPA / NNPA | 0.96% / 0.44% | 0.85% / 0.37% | asset-quality note |
| Provision coverage (PCR) | 54% | 57% | provisioning series |
| Gain-on-assignment | **not broken out in this deck** | — | → `UNAVAILABLE` (exists in the annual-report P&L notes; **not guessed**) |

**Check results (real config thresholds):**
- `provision_book_divergence`: provisions **+72.2%** vs AUM **+26.0%** → gap **0.46**, threshold 0.50 → **no flag** (a calibrated near-miss: provisions grew ~2.8× faster than the book, reflecting the elevated FY25 credit costs BAF itself disclosed — but below the divergence line).
- `reserve_suppression`: charge/book **1.40% → 1.91%** (rose) → **no flag** (reserves rose, not cut).
- `gain_on_sale_reliance`: `UNAVAILABLE` → **no flag** (correctly not fabricated).
- **Deterministic verdict: `PASS`.** No false positive on a quality lender.

## B) CreditAccess Grameen — must-fire test (India's largest listed MFI, in the FY25 sector downturn)

**Primary source.** CreditAccess Grameen FY25 audited results press release (16 May 2025) and Q4&FY25
investor presentation, both on the company's own domain (`creditaccessgrameen.in`). Figures in **INR cr**.

| Figure (verbatim) | FY25 | FY24 | YoY | Source |
|---|---|---|---|---|
| GLP / AUM | 25,948 | 26,714 | −2.9% | results release, Business Highlights |
| **Impairment of financial instruments** | **1,929.5** | **451.8** | **+327.1%** | presentation P&L statement (printed YoY) |
| Profit after tax | 531.4 | 1,445.9 | −63.2% | presentation P&L statement |
| Net loans (of impairment allowance) | 24,274.4 | 25,105.0 | −3.3% | presentation balance sheet |
| GNPA | 4.76% | 1.18% | — | presentation key ratios |
| Total income | 5,756.1 | 5,172.7 | +11.3% | results release |
| PPOP | 2,638.4 | 2,391.0 | +10.3% | results release |
| Loan-sale / assignment gain | **not a material/separate line** | — | → `UNAVAILABLE` (on-book lender; **not guessed**) |

**Check results (real config thresholds):**
- `provision_book_divergence`: impairment **+327.1%** while the book **−2.9%** → gap **3.30** ≫ 0.50 → **FLAG**. This is the signature "earnings destroyed at the impairment line on a shrinking book": income +11.3% and PPOP +10.3%, yet PAT −63.2% — the entire collapse is below PPOP.
- `reserve_suppression`: charge/book **1.69% → 7.44%** (rose sharply) → **no flag**. Critical nuance: the company is provisioning **more** (ECL 5.07% of book, "conservative provisioning and accelerated write-off" per its release). The check correctly does **not** accuse a company that is honestly recognising stress.
- **Deterministic verdict: `REVIEW`** (one MEDIUM flag). Correctly routes to the forensic tier for a human look — cyclical MFI stress honestly recognised vs. something worse is a judgment the deterministic layer explicitly does not make.

---

## Why the contrast matters

The two runs together show the checks are **calibrated, not trigger-happy**:

1. **No false positive** on Bajaj Finance despite a real +72% provision jump (the divergence gate held at 0.46 < 0.50).
2. **A real fire** on CreditAccess's +327% impairment surge — but only to `REVIEW`, not `HARD_FAIL`.
3. **The reserve-suppression check distinguished the two directions of provision movement**: it stayed
   `False` for CreditAccess because reserves *rose*. The dangerous pattern (Sezzle) is provisions *falling*
   into a growing/riskier book; the honest pattern (CreditAccess FY25) is provisions *rising* to meet
   recognised stress. Same "provisions moved a lot," opposite forensic meaning — and the checks encode the
   difference.

## The primary-source lesson (project-owner directive, demonstrated)

- Both companies' data came from **the companies' own documents**, read directly (pypdf), not from an
  aggregator and not via a summarising model that could misread a figure.
- The BAF and CreditAccess investor-presentation PDFs are **image/dynamic-render heavy** — a naive text
  fetch failed. The fix that worked was fetching the file and parsing it directly. **Takeaway for the
  firm's `adapters/`: primary filings are often not cleanly text-extractable; the ingestion layer must
  handle OCR / direct PDF parsing, or it will silently fall back to secondary sources — exactly the
  failure mode to avoid.**
- Where a figure was genuinely not in the primary doc (gain-on-assignment), it was reported `UNAVAILABLE`,
  not filled — so no forensic conclusion rests on an invented number.
