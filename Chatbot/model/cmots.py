"""the cmots market-data feed -- one function per endpoint the scheduler calls.

IP-whitelisted, no key, confirmed working straight from this network (see the
ArihantCmotsApis doc for the full ~250-endpoint catalog; this covers the equity
core subset in v1). Every response is the same envelope --
`{"success": bool, "data": [...], "message": str}` -- unwrapped once here so every
fetch function below returns a plain list of dicts.

Unlike `web.py`/`history.py`, failures here are NOT swallowed. Those modules sit in
the answer path, where a flaky call must never break a chat turn; this one runs
out-of-band in the scheduler, where a silent empty list would look identical to
"nothing changed today" and hide a real outage. `_get` retries transient errors a
few times, then raises, and it's the caller's job (bulk job vs per-company loop)
to decide whether one failure aborts the run or just skips one company.
"""
from __future__ import annotations

import time

import requests

from config import CMOTS_BASE_URL, CMOTS_RETRIES, CMOTS_RETRY_BACKOFF_S, CMOTS_TIMEOUT_S

_session: requests.Session | None = None


def _http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": "arihantBot/1.0"})
    return _session


def _get(path: str) -> list[dict]:
    """GET {CMOTS_BASE_URL}{path} -> the unwrapped `data` list.

    Retries connection errors and 5xx with a doubling backoff -- the transient
    "remote end closed connection" seen in testing is exactly what this is for.
    A 200 with `success: false` is not transient, so it raises immediately.
    """
    url = f"{CMOTS_BASE_URL}{path}"
    last_exc: Exception | None = None
    for attempt in range(CMOTS_RETRIES):
        try:
            resp = _http().get(url, timeout=CMOTS_TIMEOUT_S)
            resp.raise_for_status()
            body = resp.json()
        except (requests.RequestException, ValueError) as e:
            last_exc = e
            if attempt < CMOTS_RETRIES - 1:
                time.sleep(CMOTS_RETRY_BACKOFF_S * (2 ** attempt))
            continue
        if not body.get("success"):
            # "no data available" is CMOTS's normal answer for a company that simply
            # has none of this -- e.g. a tiny/dormant company with no ratio history --
            # not a fetch error. Anything else (bad request, server error message) still
            # raises, since that's worth the scheduler counting as a real failure.
            if "no data" in str(body.get("message", "")).lower():
                return []
            raise RuntimeError(f"cmots {path} -> success=false: {body.get('message')}")
        return body.get("data") or []
    raise RuntimeError(f"cmots {path} failed after {CMOTS_RETRIES} attempts: {last_exc}")


# ------------------------------------------------------------------- bulk, all companies
def fetch_company_master() -> list[dict]:
    return _get("/msf/api/CompanyMaster")


def fetch_bhav_copy(exchange: str) -> list[dict]:
    """exchange: 'nse' or 'bse'. Today's EOD OHLCV for every listed company."""
    return _get(f"/msf/api/EOD-Bhav-Copy/{exchange}")


def fetch_corporate_actions(period: str = "15Day") -> list[dict]:
    """period: Today/Week/15Day/30Day/-. Dividend/bonus/split/rights/buyback/merger,
    tagged by `CorpType`, for every company in one call."""
    return _get(f"/msf/api/ConsolidatedCorportate/{period}/-")


def fetch_results_calendar(period: str = "week") -> list[dict]:
    """period: Today/Week/Later."""
    return _get(f"/msf/api/ResultsInfo/{period}")


def fetch_result_announcements() -> list[dict]:
    return _get("/msf/api/QuarterlyResultAnnouncement")


def fetch_daily_announcements(exchange: str) -> list[dict]:
    """exchange: 'nse' or 'bse'."""
    return _get(f"/msf/api/Announcement/{exchange}")


NEWS_SECTIONS = ("Hot-pursuit", "Stock-alert", "Corporate-news")


def fetch_market_news(section: str, top: int = 100) -> list[dict]:
    """section: one of NEWS_SECTIONS.

    Superseded by fetch_news_archive below as the scheduler's actual news
    source -- kept here since the fetch itself still works, just with `co_code`
    empty on nearly every row (confirmed live), which made the resulting `news`
    documents impossible to look up by company.
    """
    return _get(f"/msf/api/CapitalMarketLiveNews/{section}/-/{top}")


# a different CMOTS feed for the same three news types, plus stock alerts --
# confirmed live to carry a real `Co_code`/`co_code` on nearly every row, unlike
# fetch_market_news above. This is what the scheduler actually uses.
NEWS_ARCHIVE_SECTIONS = {
    "hot_pursuit": "hot-pursuit",
    "corporate_news": "corporate-news",
    "results_announcements": "results%20-%20announcements",
}


def fetch_news_archive(section: str, start: str, end: str, count: int = 200) -> list[dict]:
    """section: a key of NEWS_ARCHIVE_SECTIONS. start/end as 'DD-mon-YYYY'."""
    path = NEWS_ARCHIVE_SECTIONS[section]
    return _get(f"/msf/api/HistoricalNewsArihantcapital/{path}/{start}/{end}/{count}")


def fetch_stock_alert_archive(start: str, end: str) -> list[dict]:
    """start/end as 'DD-mon-YYYY'. ~55% of rows carry co_code -- the rest are
    alerts spanning several stocks at once ('Stock Alert: X, Y, Z') that don't
    reduce to a single company."""
    return _get(f"/msf/api/StockalertArihantcapital/{start}/{end}")


def fetch_stock_wise_news(co_codes: list[int]) -> list[dict]:
    """up to 10 co_codes per call (CMOTS's own limit) -- the most reliable
    company link there is, since you're asking by company directly rather than
    hoping the article got tagged. Used for the per-company sync loop, not the
    bulk archive above."""
    codes = ",".join(str(c) for c in co_codes[:10])
    return _get(f"/msf/api/LatestStockWiseNews/{codes}")


# --------------------------------------------------------------- per-company loop
def fetch_company_profile(co_code: int) -> dict | None:
    """chairman, registered office, auditor, registrar -- one row, or None."""
    rows = _get(f"/web/api/CompProfile/{co_code}")
    return rows[0] if rows else None


def fetch_board_of_directors(co_code: int) -> list[dict]:
    return _get(f"/web/api/BoardofDirectors/{co_code}")


def fetch_about_company(co_code: int) -> dict | None:
    rows = _get(f"/web/api/AboutCompany/{co_code}")
    return rows[0] if rows else None


def fetch_shareholding_data(co_code: int) -> list[dict]:
    """quarterly promoter/FII/MF/insurance/public %, one row per YRC (quarter)."""
    return _get(f"/msf/api/ShareholdingData/{co_code}")


def fetch_shareholding_pattern(co_code: int) -> list[dict]:
    """same idea, different cut -- this one has Pledged_Per, which the other
    doesn't. Merged with fetch_shareholding_data's rows by YRC in the store."""
    return _get(f"/msf/api/ShareHoldingPatternEquity/{co_code}")


def fetch_keystats(co_code: int, exchange: str = "bse") -> dict | None:
    """PE/EPS/ROE/etc snapshot for one company. One row, or None."""
    rows = _get(f"/msf/api/Keystats/{exchange}/{co_code}/s")
    return rows[0] if rows else None


def fetch_financial_ratios(co_code: int) -> list[dict]:
    """multi-year ratio history for one company, newest `yrc` first."""
    return _get(f"/msf/api/FinancialRatios/{co_code}/C")


def fetch_results_quarterly(co_code: int, basis: str) -> list[dict]:
    """basis: 'S' (standalone) or 'C' (consolidated). One endpoint for every
    company -- confirmed live that a bank co_code comes back in the bank-shaped
    schema (InterestEarned/TotalIncome/NetProfit) automatically, no separate
    bank URL needed despite what the doc's examples implied."""
    return _get(f"/msf/api/ResultsQuarterly/{co_code}/{basis}")


def fetch_results_yearly(co_code: int, basis: str) -> list[dict]:
    return _get(f"/msf/api/ResultsYearly/{co_code}/{basis}")


def fetch_balance_sheet_yearly(co_code: int, basis: str) -> list[dict]:
    return _get(f"/msf/api/YearlyBalanceSheet/{co_code}/{basis}")


# ------------------------------------------------------------------------- bulk
def fetch_fii_dii(category: str, period: str = "D") -> list[dict]:
    """category: 'FIICash' or 'DIICash' -- 'FIIFuture'/'FIIOption' return no
    data currently (confirmed live, likely discontinued). period: D/M/Y."""
    return _get(f"/msf/api/FIIDIIData/{period}/{category}")


def fetch_world_indices() -> list[dict]:
    return _get("/msf/api/WorldIndices")


def fetch_key_financials(co_code: int) -> list[dict]:
    """peer-comparison group for one company -- the queried co_code plus its
    peers, `ord`-ranked. Every row is upserted under its own co_code, so this
    also fills in data for whichever peers happen to surface."""
    return _get(f"/msf/api/CompPeerKeyParams/{co_code}/c/5")


# ------------------------------------------------------------- historical backfill
def fetch_historical_price(co_code: int, start: str, end: str, exchange: str = "BSE") -> list[dict]:
    """start/end as 'DD-mon-YYYY' (e.g. '01-aug-2025'), CompanyChart's own format."""
    return _get(f"/msf/api/CompanyChart/{exchange}/{co_code}/{start}/{end}")
