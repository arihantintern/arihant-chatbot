"""the cmots mutual-fund feed -- same shape as cmots.py, different vendor path
(`/MF/api/...` instead of `/msf/api/...`), so it reuses that module's http client
and retry logic rather than duplicating it.

Most of this is bulk, unlike the equity per-company endpoints: `SchemeMasters`,
`RiskFactors`, `AUMGrowth`, `MFDashboard` and friends all take a wildcard `-` (or
a large enough `top` count) and hand back every scheme in one call. Only three
things genuinely need a per-item loop -- see cmots_scheduler.py:

- `fetch_peer_comparison` and `fetch_nav_history` -- confirmed live, no wildcard,
  need one call per mf_schcode.
- `fetch_stock_holders` -- takes a *stock's* co_code, not a scheme code, so it
  loops over the equity company universe you already have, not the MF one.

**`fetch_nav_history`'s URL is a trap.** `/HistoricalNAV/{schcode}/M/1/-/-/{junk}`
-- the scheme selector is the FIRST path segment, and the LAST one is inert
(tested: swapping it for a nonsense value returns identical rows). Get the
positions backwards and every call "succeeds" while quietly returning scheme 1's
history for every scheme you asked about.
"""
from __future__ import annotations

from cmots import _get

# a working amccode for CategoryMaster -- testing showed the category name (last
# segment) is what actually selects the taxonomy; the amccode barely matters, so
# one fixed value covers every category
_CATEGORY_AMCCODE = 21273
MF_CATEGORIES = ("equity", "debt", "hybrid")


# ------------------------------------------------------------------- bulk, all schemes
def fetch_scheme_master() -> list[dict]:
    return _get("/MF/api/SchemeMasters/-/-/-/-/-/-")


def fetch_scheme_returns(top: int = 10000) -> list[dict]:
    """top must exceed the real scheme count (~8500) to get everything in one call."""
    return _get(f"/MF/api/SchemeReturns/-/-/{top}")


def fetch_risk_factors() -> list[dict]:
    return _get("/MF/api/RiskFactors/-")


def fetch_dividend_details(top: int = 5000) -> list[dict]:
    return _get(f"/MF/api/DividendDetails/-/{top}")


def fetch_aum_growth() -> list[dict]:
    """no input -- full AUM history, every scheme, one row per month. Large
    (~140k rows) but still one call."""
    return _get("/MF/api/AUMGrowth")


def fetch_market_activity() -> list[dict]:
    """MF Dashboard -- market-wide daily equity/debt buy-sell activity, not
    per-scheme."""
    return _get("/MF/api/MFDashboard")


def fetch_nfo(top: int = 5000) -> list[dict]:
    return _get(f"/MF/api/NewFundOffer/NFO/-/{top}")


def fetch_portfolio_activity(direction: str, top: int = 5000) -> list[dict]:
    """direction: 'In' or 'Out'. Recent portfolio adds/removes across all funds --
    the API itself doesn't say which in its row shape, hence the caller tagging
    it (see cmots_store.upsert_mf_portfolio_activity)."""
    return _get(f"/MF/api/WhatsInAndOut/{direction}/2/{top}")


def fetch_category_master(category: str) -> list[dict]:
    """category: one of MF_CATEGORIES."""
    return _get(f"/MF/api/CategoryMaster/{_CATEGORY_AMCCODE}/{category}")


# ------------------------------------------------------------------- per-scheme loop
def fetch_peer_comparison(mf_schcode: int) -> list[dict]:
    return _get(f"/MF/api/PeerComparision/{mf_schcode}")


def fetch_nav_history(mf_schcode: int, period: str = "M", count: int = 60) -> list[dict]:
    """the scheme selector is the FIRST segment -- see module docstring."""
    return _get(f"/MF/api/HistoricalNAV/{mf_schcode}/{period}/{count}/-/-/-")


# --------------------------------------------------------- per-stock loop (equity side)
def fetch_stock_holders(co_code: int, top: int = 20) -> list[dict]:
    """which mutual fund schemes hold this STOCK -- co_code here is an equity
    company code, not a scheme code, so this loops over company_master's
    universe, not the MF one."""
    return _get(f"/MF/api/HoldingAcrossFunds/{co_code}/{top}")
