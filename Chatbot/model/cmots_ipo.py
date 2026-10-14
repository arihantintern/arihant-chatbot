"""the cmots IPO feed -- same shape as cmots.py/cmots_mf.py, different vendor
path (`/web/api/...`), reusing that module's http client and retry logic.

Smaller surface than equities or mutual funds -- there are only ~150 IPOs total,
so even the six endpoints below that need a per-company loop (no bulk wildcard)
finish in seconds, not minutes. `fetch_calendar` covers upcoming/open/closed in
three cheap calls; `fetch_draft_prospectus` and `fetch_recently_listed` turned
out to be bulk too, despite looking like they'd need per-company loops.
"""
from __future__ import annotations

from cmots import _get

CALENDAR_STATUSES = ("upcoming", "open", "closed")
_CALENDAR_OPTION = {"upcoming": 1, "open": 2, "closed": 3}


# ------------------------------------------------------------------------- bulk
def fetch_ipo_master() -> list[dict]:
    return _get("/web/api/IPO_Master/-")


def fetch_calendar(status: str) -> list[dict]:
    """status: one of CALENDAR_STATUSES. The '-' wildcards give every IPO in
    that bucket, not just a sample."""
    option = _CALENDAR_OPTION[status]
    return _get(f"/web/api/Fillinitialipo/{option}/-/-/-")


def fetch_recently_listed(exchange: str, top: int = 20) -> list[dict]:
    """exchange: 'bse' or 'nse'. Post-listing price performance."""
    return _get(f"/web/api/getrecentlylistedipo/{exchange}/-/-/ipo/{top}")


def fetch_draft_prospectus() -> list[dict]:
    """no input needed -- every SEBI draft filing in one call, despite the doc
    implying a per-company lookup."""
    return _get("/web/api/DraftProspectMain/sebi")


# ------------------------------------------------------------------- per-IPO loop
def fetch_ipo_details(co_code: int) -> dict | None:
    """timelines + background + director, merged by CMOTS itself into one call."""
    rows = _get(f"/web/api/NEWIPOdetails/{co_code}")
    return rows[0] if rows else None


def fetch_ipo_financials(co_code: int) -> list[dict]:
    return _get(f"/web/api/IPOFinancial/{co_code}/S")


def fetch_ipo_synopsis(co_code: int) -> dict | None:
    rows = _get(f"/web/api/IPOSynopsisMain/{co_code}/1")
    return rows[0] if rows else None


def fetch_ipo_strengths(co_code: int) -> list[dict]:
    return _get(f"/web/api/IPOStrengthDetails/{co_code}")


def fetch_ipo_risks(co_code: int) -> list[dict]:
    return _get(f"/web/api/IPORisks/{co_code}")


def fetch_ipo_peers(co_code: int) -> list[dict]:
    return _get(f"/web/api/IPOIndustryPeerDetails/{co_code}")
