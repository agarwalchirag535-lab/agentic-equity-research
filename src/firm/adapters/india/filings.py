"""Primary-document adapter: audited annual reports + concalls (grade A / C).

Screener (grade B) gives fast quantitative tables. The audited annual report is where the *forensic*
signal lives — the auditor's report, key audit matters, related-party transactions, contingent
liabilities, and the notes to accounts. Numbers alone don't reveal fraud; the notes do.

This adapter fetches the PDF (→ bronze), extracts text (→ silver), and locates the forensic-critical
sections so the forensic_accountant agent reads primary source, not an aggregator.
"""

from __future__ import annotations

import io
import ssl
import urllib.request

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Forensic-critical sections to locate in an annual report (SPEC §5 forensic_accountant).
SECTION_KEYWORDS: dict[str, list[str]] = {
    "auditors_opinion": ["Independent Auditor", "INDEPENDENT AUDITOR", "Auditor's Report"],
    "qualified_or_emphasis": ["Qualified Opinion", "Basis for Qualified", "Emphasis of Matter",
                              "EMPHASIS OF MATTER", "Disclaimer of Opinion", "Adverse Opinion"],
    "key_audit_matters": ["Key Audit Matters", "KEY AUDIT MATTERS"],
    "related_party": ["Related Party Transaction", "Related party", "RELATED PARTY"],
    "contingent_liabilities": ["Contingent Liabilit", "CONTINGENT LIABILIT"],
    "auditor_ceased_or_resigned": ["resignation of", "ceased to be the auditor", "casual vacancy"],
}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover
        return ssl.create_default_context()


def fetch_pdf(url: str, timeout: float = 90.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310
        return resp.read()


def extract_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def find_section(text: str, keywords: list[str], window: int = 4000) -> str:
    """Return the first ~window chars starting at the earliest matching heading keyword ('' if none).

    Case-insensitive: display fonts scramble case through text extraction ("contingent liability" in a
    small-caps face), and a mandated disclosure reported missing because of a font is a false gap —
    PC Jeweller FY17's contingent-liabilities note was about to be charged as undisclosed this way."""
    lowered = text.casefold()
    positions = [lowered.find(kw.casefold()) for kw in keywords]
    hits = [p for p in positions if p != -1]
    if not hits:
        return ""
    start = min(hits)
    return text[start:start + window]


def forensic_sections(text: str, window: int = 4000) -> dict[str, str]:
    """Locate every forensic-critical section; empty string means the section/keyword was not found."""
    return {name: find_section(text, kws, window) for name, kws in SECTION_KEYWORDS.items()}


# Legally-mandated disclosures always present in a listed company's audited AR (SA 701, Ind-AS 24,
# Companies Act). Absence is a signal, not a blank. `qualified_or_emphasis` and
# `auditor_ceased_or_resigned` are intentionally EXCLUDED — those are conditional; their absence is good.
REQUIRED_DISCLOSURES: frozenset[str] = frozenset(
    {"auditors_opinion", "related_party", "contingent_liabilities", "key_audit_matters"}
)

#: First fiscal year each requirement applies to. Key Audit Matters is SA 701, effective for audits of
#: periods beginning on/after 1 April 2017 — the FY18 annual report is the first that must carry it.
#: An FY17 filing without KAM is compliant, and calling it a gap is a false accusation (PC Jeweller run).
DISCLOSURE_EFFECTIVE_FY: dict[str, int] = {"key_audit_matters": 2018}


def disclosure_gaps(sections: dict[str, str], fiscal_year: int | None = None) -> tuple[list[str], bool]:
    """Which legally-mandated AR disclosures are missing from the extracted text (owner directive /
    ADR-0014). Delegates to the deterministic `disclosure_completeness` check (compute layer). A missing
    required section means either it was not disclosed or the filing could not be read — both are signals
    that feed the `disclosure_gap` forensic flag, never a silent blank. Returns (missing, is_flagged)."""
    from firm.core.compute.quality import disclosure_completeness

    required = REQUIRED_DISCLOSURES if fiscal_year is None else frozenset(
        name for name in REQUIRED_DISCLOSURES
        if DISCLOSURE_EFFECTIVE_FY.get(name, 0) <= fiscal_year
    )
    present = [name for name, txt in sections.items() if txt.strip()]
    return disclosure_completeness(required, present)
