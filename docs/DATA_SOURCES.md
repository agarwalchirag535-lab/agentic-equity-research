# DATA_SOURCES.md — sources, licence, rate limit, reliability grade

Reliability grades (SPEC §4): **A** audited filing · **B** exchange filing / rating rationale ·
**C** company presentation / concall claim · **D** media / broker note. Agents weight by grade and may
NOT build a core thesis pillar on grade **D** alone. Every source is accessed through
`src/firm/adapters/india/` so a dead source is a one-file fix.

> **Implemented (ADR-0009):** `screener.in` is the working primary fundamentals source — verified live,
> 10-yr consolidated financials + shareholding, no login (`adapters/india/screener.py`,
> graded **B**). Prices/liquidity/corporate-actions to come from a **broker API** or `jugaad-data`/`bse`
> (owner sets the broker key in `.env`; Claude never handles it). Concall/AR PDFs later, via BSE/NSE
> feeds. Point-in-time caveat: screener is a current snapshot — honest for as-of=today, not for
> historical eval (Phase 6). ToS caveat: automated access is for the owner's personal research, behind
> an adapter with caching/rate-limits; a paid licence or broker API is the clean path at scale.

| Source | What | Grade | Access | Rate limit / notes | Status |
|---|---|---|---|---|---|
| Company annual reports (PDF) | 10-yr financials, related-party, auditor, contingent liabs | A | download → bronze | none; large PDFs | TBD archive (PLAN OQ#1) |
| BSE/NSE exchange filings | results, shareholding, board changes, GSM/ASM | B | `bse` / `jugaad-data` / feeds | exchange-throttled; cache | active |
| Concall transcripts + audio | management guidance, Q&A, tone | C | investor-relations / feeds | scattered; per-company | TBD archive |
| Investor presentations | segment KPIs, capex plans | C | IR pages | none | manual/scrape |
| Credit rating rationales | leverage, covenants, refinancing | B | rating agency sites | none | active |
| Shareholding patterns | promoter/FII/DII/MF deltas, pledges | B | exchange | quarterly | active |
| AMFI | mutual-fund holdings | B | AMFI | daily NAV / monthly holdings | active |
| SEBI orders / surveillance | regulatory actions, GSM/ASM | B | SEBI/exchange | none | active |
| Bulk/block deals | counterparty flows | B | exchange | daily | active |
| Price/volume history | liquidity floor, ADV, re-rating | B | `jugaad-data` | NSE-throttled; cache | active |
| Media / broker notes | context only | D | web | never load-bearing | active |

## Point-in-time obligation
Every ingested row records `published_at`. The fact-store query layer (`core/facts/`) filters
`published_at <= as_of`. Sources that cannot supply a trustworthy `published_at` are quarantined and may
not feed historical eval runs (SPEC Law 3, PLAN §9).

## Open sourcing decisions (see PLAN OQ#1, OQ#2)
- Authoritative source of record for 10-yr point-in-time financials + 12-quarter concalls: **undecided.**
- Golden-set (30 cases, 2015–2021, frozen `as_of`): sourcing + licence review **pending** before Phase 6.
