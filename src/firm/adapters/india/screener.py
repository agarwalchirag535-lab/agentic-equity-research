"""screener.in adapter — the primary fundamentals source (10-yr financials, shareholding).

Design: `fetch` (network) is separated from `parse_*` (pure) so the parser is tested against a saved
HTML fixture with no network. screener aggregates audited filings, so its data is graded B and its
provenance points to screener — ideally cross-checked against the primary annual report (grade A).

Point-in-time note (Law 3): screener exposes a *current* snapshot, not archived filings with their
original publish dates. For as-of=today this is honest (all shown data predates today). For historical
eval it is not — see docs/PLAN.md §9.
"""

from __future__ import annotations

import html as _html
import re
import ssl
import urllib.request

from firm.adapters.base.interfaces import FinancialRow, ShareholdingRow

_SECTION_STATEMENT = {"profit-loss": "pnl", "balance-sheet": "balance_sheet", "cash-flow": "cashflow"}
_SHAREHOLDING_CATEGORY = {
    "Promoters": "promoter", "FIIs": "fii", "DIIs": "dii", "Government": "government", "Public": "public",
}
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _ssl_context() -> ssl.SSLContext:
    """Use the certifi CA bundle — Python on macOS often can't find the system CA store."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover
        return ssl.create_default_context()


_BASIS_PATH = {"default": "", "consolidated": "consolidated/", "standalone": "standalone/"}


def fetch(ticker: str, basis: str = "default", timeout: float = 40.0) -> str:
    """Download the screener company page HTML (network).

    ``basis='default'`` fetches screener's own best-available page — important because a company's
    *consolidated* page can be stale (e.g. Alkyl Amines' consolidated series ends FY20 while its default/
    standalone page is current to FY26). Prefer default; the ingest layer flags staleness regardless.
    """
    url = f"https://www.screener.in/company/{ticker}/{_BASIS_PATH[basis]}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def _strip(html_fragment: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", html_fragment)).replace("\xa0", " ").strip()


def _period_to_fy(label: str) -> str | None:
    """'Mar 2015' -> 'FY15'. Non-fiscal columns (TTM, blanks) -> None."""
    m = re.match(r"[A-Za-z]{3}\s+(\d{4})", label)
    return f"FY{int(m.group(1)) % 100:02d}" if m else None


def _num(raw: str) -> tuple[float | None, bool]:
    """Parse a screener cell: '374,372' -> 374372.0; '10%' -> (0.10, True); '' / '-' -> (None, ...)."""
    s = _strip(raw).replace(",", "")
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    if s in ("", "-"):
        return None, pct
    try:
        v = float(s)
    except ValueError:
        return None, pct
    return (v / 100.0 if pct else v), pct


def _first_data_table(section_html: str) -> str | None:
    m = re.search(r'<table class="data-table.*?</table>', section_html, re.S)
    return m.group(0) if m else None


def parse_financials(html: str, ticker: str, consolidated: bool = True) -> list[FinancialRow]:
    rows: list[FinancialRow] = []
    for sec_id, statement in _SECTION_STATEMENT.items():
        sec = re.search(rf'<section id="{sec_id}".*?</section>', html, re.S)
        if not sec:
            continue
        table = _first_data_table(sec.group(0))
        if not table:
            continue
        periods = [_period_to_fy(_strip(t)) for t in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if not cells:
                continue
            metric = _strip(cells[0]).replace("+", "").strip()
            if not metric:
                continue
            for i, cell in enumerate(cells[1:], start=1):
                if i >= len(periods) or periods[i] is None:
                    continue
                value, pct = _num(cell)
                if value is None:
                    continue
                rows.append(FinancialRow(
                    ticker=ticker, statement=statement, metric=metric, period=periods[i],
                    value=value, unit="ratio" if pct else "INR_cr", consolidated=consolidated,
                    source="screener",
                ))
    return rows


def parse_shareholding(html: str, ticker: str) -> list[ShareholdingRow]:
    sec = re.search(r'<section id="shareholding".*?</section>', html, re.S)
    if not sec:
        return []
    table = _first_data_table(sec.group(0))
    if not table:
        return []
    periods = [_strip(t) for t in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    out: list[ShareholdingRow] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not cells:
            continue
        label = _strip(cells[0]).replace("+", "").strip()
        category = _SHAREHOLDING_CATEGORY.get(label)
        if category is None:
            continue
        for i, cell in enumerate(cells[1:], start=1):
            if i >= len(periods) or not periods[i]:
                continue
            s = _strip(cell).replace(",", "").rstrip("%")
            if s in ("", "-"):
                continue
            try:
                pct = float(s)  # keep as a percentage number (50.34), not a fraction
            except ValueError:
                continue
            out.append(ShareholdingRow(
                ticker=ticker, period=periods[i], category=category, pct=pct, source="screener",
            ))
    return out


class ScreenerSource:
    """Implements adapters.base.FundamentalsSource."""

    name = "screener"

    def annual_financials(self, ticker: str, basis: str = "default") -> list[FinancialRow]:
        return parse_financials(fetch(ticker, basis=basis), ticker)

    def shareholding(self, ticker: str, basis: str = "default") -> list[ShareholdingRow]:
        return parse_shareholding(fetch(ticker, basis=basis), ticker)
