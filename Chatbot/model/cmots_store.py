"""cmots market data, filed in mongo -- one collection per shape, upserted by a
natural key so a rerun (the scheduler runs daily, plus `--once` while testing)
never duplicates a row.

Connection handling copies `history.py`'s rule for the *read* side: `get_company`,
`latest_price` and friends return `None`/`[]` if mongo is unreachable, because a
market-data lookup failing must fall through to the bot's existing answer tiers,
not crash the turn. The *write* side (`upsert_*`, called only from the scheduler,
never from a chat turn) does the opposite and raises, so a scheduler run's own
error handling -- and its own log line -- is what surfaces a stale feed, instead
of it silently looking like "nothing new today".

**This connects with `CMOTS_MONGO_URI`, not `MONGO_URI`.** This bot's own chat
history is unconfigured until `.env` names a real cluster, and cmots data
shouldn't wait on that -- it defaults to the local mongod that already holds it
(see config.py), independent of whatever the history feature ends up pointed at.

**co_code arrives inconsistently typed** -- a float from most endpoints, a string
from `ConsolidatedCorportate` -- so every write path runs it through `_co_code()`
to land on a plain int before it's used as (part of) a key.
"""
from __future__ import annotations

import difflib
import re
import time
from datetime import datetime, timezone

from config import CMOTS_DB, CMOTS_MONGO_URI, MONGO_TIMEOUT_MS

_client = None
_db = None
_state = "not tried yet"

# refreshed on demand from company_master; used for fuzzy name matching so a
# typo'd or partial company name doesn't require loading 6000+ rows per lookup
_name_cache: list[tuple[str, int]] = []
_name_cache_at = 0.0
_NAME_CACHE_TTL_S = 600


def connect(force: bool = False) -> bool:
    global _client, _db, _state
    if _db is not None and not force:
        return True
    if _client is not None and not force:
        return False

    try:
        from pymongo import ASCENDING, MongoClient
    except ImportError:
        _state = "pymongo is not installed (pip install pymongo)"
        _client, _db = False, None
        return False

    try:
        _client = MongoClient(CMOTS_MONGO_URI, serverSelectionTimeoutMS=MONGO_TIMEOUT_MS,
                              tz_aware=True, appname="abot-cmots")
        _client.admin.command("ping")
        db = _client[CMOTS_DB]
        db.company_master.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.company_master.create_index([("_name_key", ASCENDING)], name="name")
        db.company_master.create_index([("_symbol_key", ASCENDING)], name="symbol")
        db.prices_eod.create_index([("co_code", ASCENDING), ("date", ASCENDING)],
                                    unique=True, name="co_date")
        db.corporate_actions.create_index(
            [("co_code", ASCENDING), ("CorpType", ASCENDING), ("CorpDate", ASCENDING),
             ("AnnoucementDate", ASCENDING)], unique=True, name="action")
        db.corporate_actions.create_index([("co_code", ASCENDING)], name="co")
        db.results_calendar.create_index(
            [("ISIN", ASCENDING), ("ResultDate", ASCENDING), ("QtrPeriod", ASCENDING)],
            unique=True, name="result")
        db.news.create_index([("Sno", ASCENDING)], unique=True, name="sno")
        db.news.create_index([("co_code", ASCENDING)], name="co")
        db.keystats.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.financial_ratios.create_index([("co_code", ASCENDING), ("yrc", ASCENDING)],
                                          unique=True, name="co_yrc")
        db.key_financials.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.company_profile.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.shareholding_pattern.create_index([("co_code", ASCENDING), ("YRC", ASCENDING)],
                                              unique=True, name="co_yrc")
        db.results_quarterly.create_index(
            [("co_code", ASCENDING), ("YRC", ASCENDING), ("basis", ASCENDING)],
            unique=True, name="co_yrc_basis")
        db.results_yearly.create_index(
            [("co_code", ASCENDING), ("YRC", ASCENDING), ("basis", ASCENDING)],
            unique=True, name="co_yrc_basis")
        db.balance_sheet_yearly.create_index(
            [("co_code", ASCENDING), ("YRC", ASCENDING), ("basis", ASCENDING)],
            unique=True, name="co_yrc_basis")
        db.fii_dii_activity.create_index([("Date", ASCENDING)], unique=True, name="date")
        db.world_indices.create_index([("indexname", ASCENDING), ("date", ASCENDING)],
                                       unique=True, name="index_date")

        # -------------------------------------------------------------- mutual funds
        db.mf_scheme_master.create_index([("mf_schcode", ASCENDING)], unique=True,
                                          name="mf_schcode")
        db.mf_scheme_master.create_index([("_name_key", ASCENDING)], name="name")
        db.mf_scheme_returns.create_index([("mf_schcode", ASCENDING)], unique=True,
                                           name="mf_schcode")
        db.mf_risk_factors.create_index([("mf_schcode", ASCENDING)], unique=True,
                                         name="mf_schcode")
        db.mf_dividends.create_index(
            [("mf_schcode", ASCENDING), ("DivDate", ASCENDING), ("RecordDate", ASCENDING)],
            unique=True, name="div")
        db.mf_aum_history.create_index([("mf_schcode", ASCENDING), ("AUMDate", ASCENDING)],
                                        unique=True, name="mf_date")
        db.mf_market_activity.create_index([("TRANS_DATE", ASCENDING)], unique=True,
                                            name="date")
        db.mf_nfo.create_index([("mf_schcode", ASCENDING)], unique=True, name="mf_schcode")
        db.mf_portfolio_activity.create_index(
            [("mf_schcode", ASCENDING), ("CO_CODE", ASCENDING), ("invdate", ASCENDING),
             ("direction", ASCENDING)], unique=True, name="activity")
        db.mf_category_master.create_index(
            [("MainCategory", ASCENDING), ("VCLASSCODE", ASCENDING)], unique=True, name="cat")
        db.mf_peer_comparison.create_index([("mf_schcode", ASCENDING)], unique=True,
                                            name="mf_schcode")
        db.mf_nav_history.create_index([("mf_schcode", ASCENDING), ("NAVDATE", ASCENDING)],
                                        unique=True, name="mf_date")
        db.mf_stock_holders.create_index(
            [("Co_Code", ASCENDING), ("mf_schcode", ASCENDING), ("InvDate", ASCENDING)],
            unique=True, name="stock_fund")
        db.mf_news.create_index([("sno", ASCENDING)], unique=True, name="sno")

        # ------------------------------------------------------------------------ ipo
        db.ipo_master.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.ipo_master.create_index([("_name_key", ASCENDING)], name="name")
        db.ipo_calendar.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.ipo_listed_performance.create_index(
            [("co_code", ASCENDING), ("exchange", ASCENDING)], unique=True, name="co_exchange")
        db.ipo_details.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.ipo_financials.create_index([("co_code", ASCENDING), ("yrc", ASCENDING)],
                                        unique=True, name="co_yrc")
        db.ipo_synopsis.create_index([("co_code", ASCENDING)], unique=True, name="co_code")
        db.ipo_strengths.create_index([("co_code", ASCENDING), ("sno", ASCENDING)],
                                       unique=True, name="co_sno")
        db.ipo_risks.create_index([("co_code", ASCENDING), ("sno", ASCENDING)],
                                   unique=True, name="co_sno")
        db.ipo_peers.create_index([("co_code", ASCENDING), ("SerialNo", ASCENDING)],
                                   unique=True, name="co_serial")
        db.ipo_draft_prospectus.create_index([("co_code", ASCENDING)], unique=True,
                                              name="co_code")
    except Exception as e:
        why = str(e).split("Topology Description")[0].split(",")[0].strip() or type(e).__name__
        _state = f"off -- {why} (is mongod running? cmots data unavailable)"
        _db = None
        return False

    _db = db
    _state = f"connected -- {CMOTS_DB}"
    return True


def enabled() -> bool:
    return _db is not None


def status() -> str:
    host = CMOTS_MONGO_URI.split("@")[-1]
    return f"{_state}  [{host}]"


def _co_code(row: dict) -> int | None:
    for key in ("co_code", "CO_CODE", "Co_Code", "CompanyCode", "Co_code"):
        if row.get(key) is not None:
            try:
                return int(float(row[key]))
            except (TypeError, ValueError):
                return None
    return None


def _schcode(row: dict) -> int | None:
    """same idea as `_co_code`, for the MF side's own key -- arrives as
    `mf_schcode`, `MF_SCHCODE` or `Mf_SchCode` depending on which endpoint."""
    for key in ("mf_schcode", "MF_SCHCODE", "Mf_SchCode"):
        if row.get(key) is not None:
            try:
                return int(float(row[key]))
            except (TypeError, ValueError):
                return None
    return None


def _project(row: dict, fields: tuple[str, ...]) -> dict:
    """keep only `fields` from `row` -- the MF collections are deliberately
    trimmed (unlike the equity ones, which mostly keep the raw row) since the
    same scheme identity/return figures repeat across half a dozen MF endpoints;
    every non-identity collection carries only its own unique data plus
    `mf_schcode` to join back to `mf_scheme_master`."""
    return {k: row[k] for k in fields if k in row}


def _iso_date(value) -> str | None:
    """'2026-08-12T00:00:00' or '01-Aug-2025' -> '2026-08-12'. None if unparseable."""
    if not value:
        return None
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[0]
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


# ------------------------------------------------------------------------ writes
def _bulk_upsert(collection: str, rows: list[dict], key_fn) -> int:
    """generic path: every row maps 1:1 onto its collection's own shape, keyed by
    `key_fn`. Raises on a mongo error rather than swallowing it -- see module
    docstring."""
    if not connect():
        raise RuntimeError("cmots store: mongo unavailable, cannot write")
    from pymongo import UpdateOne

    ops = []
    for row in rows:
        key = key_fn(row)
        if key is None or any(v is None for v in key.values()):
            continue
        ops.append(UpdateOne(key, {"$set": row}, upsert=True))
    if not ops:
        return 0
    result = _db[collection].bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


def upsert_company_master(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        r["_name_key"] = (r.get("companyname") or "").strip().lower()
        r["_symbol_key"] = (r.get("nsesymbol") or r.get("bsecode") or "").strip().lower()
        return {"co_code": co}
    return _bulk_upsert("company_master", rows, key)


def upsert_prices_eod(rows: list[dict]) -> int:
    """normalizes both feeders -- daily bulk EOD-Bhav-Copy and the per-company
    CompanyChart backfill -- onto one shape, since they don't share field names."""
    normalized = []
    for r in rows:
        co = _co_code(r)
        date = _iso_date(r.get("date") or r.get("TradeDate"))
        if co is None or date is None:
            continue
        normalized.append({
            "co_code": co, "date": date,
            "open": r.get("Open", r.get("open")), "high": r.get("High", r.get("high")),
            "low": r.get("Low", r.get("low")), "close": r.get("Close", r.get("close")),
            "volume": r.get("Volume", r.get("volume")), "value": r.get("Value", r.get("value")),
            "symbol": r.get("ScripCode"),
            "company_name": r.get("CompName") or r.get("compname") or r.get("lname"),
        })
    return _bulk_upsert("prices_eod", normalized,
                        lambda r: {"co_code": r["co_code"], "date": r["date"]})


def upsert_corporate_actions(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        return {"co_code": co, "CorpType": r.get("CorpType"), "CorpDate": r.get("CorpDate"),
                "AnnoucementDate": r.get("AnnoucementDate")}
    return _bulk_upsert("corporate_actions", rows, key)


def upsert_results_calendar(rows: list[dict]) -> int:
    return _bulk_upsert("results_calendar", rows,
                        lambda r: {"ISIN": r.get("ISIN"), "ResultDate": r.get("ResultDate"),
                                   "QtrPeriod": r.get("QtrPeriod")})


# the same article's Sno can come back from more than one feed with different
# casing for the same field (fetch_news_archive uses 'Date'/'Heading', while
# fetch_stock_alert_archive uses 'DATE'/'heading') -- since $set only adds or
# overwrites the keys it's given, merging both into one doc without
# normalizing first leaves every casing variant sitting there permanently.
_NEWS_FIELD_ALIASES = {
    "Sno": ("Sno", "sno"), "Date": ("Date", "DATE", "date"),
    "Time": ("Time", "time"), "Heading": ("Heading", "heading"),
    "Caption": ("Caption", "caption"), "Section_name": ("Section_name", "section_name"),
}


def upsert_news(rows: list[dict], feed: str) -> int:
    """same article can surface under more than one feed (e.g. a stock alert
    that's also corporate news) -- `feeds` accumulates every tag seen for a Sno
    instead of the generic upsert's plain overwrite."""
    if not connect():
        raise RuntimeError("cmots store: mongo unavailable, cannot write")
    from pymongo import UpdateOne

    ops = []
    for r in rows:
        for canonical, aliases in _NEWS_FIELD_ALIASES.items():
            value = next((r[a] for a in aliases if a in r), None)
            for a in aliases:
                r.pop(a, None)
            if value is not None:
                r[canonical] = value
        sno = r.get("Sno")
        if sno is None:
            continue
        co = _co_code(r)
        if co is not None:
            r["co_code"] = co
        ops.append(UpdateOne({"Sno": sno}, {"$set": r, "$addToSet": {"feeds": feed}},
                              upsert=True))
    if not ops:
        return 0
    result = _db.news.bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


def upsert_keystats(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        r["as_of"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {"co_code": co}
    return _bulk_upsert("keystats", rows, key)


def upsert_financial_ratios(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None or r.get("yrc") is None:
            return None
        r["co_code"] = co
        return {"co_code": co, "yrc": r.get("yrc")}
    return _bulk_upsert("financial_ratios", rows, key)


def _with_pl_aliases(row: dict) -> dict:
    """bank and non-bank companies report the same P&L concepts under different
    field names (ProfitAfterTax vs NetProfit, Total vs TotalIncome) -- these two
    computed fields let a lookup check one name regardless of company type,
    without discarding the original bank/non-bank-specific fields."""
    row["net_profit"] = row.get("ProfitAfterTax", row.get("NetProfit"))
    row["total_income"] = row.get("Total", row.get("TotalIncome"))
    return row


def _upsert_pl_statement(collection: str, rows: list[dict], basis: str) -> int:
    def key(r):
        co = _co_code(r)
        if co is None or r.get("YRC") is None:
            return None
        r["co_code"] = co
        r["basis"] = basis
        _with_pl_aliases(r)
        return {"co_code": co, "YRC": r["YRC"], "basis": basis}
    return _bulk_upsert(collection, rows, key)


def upsert_results_quarterly(rows: list[dict], basis: str) -> int:
    return _upsert_pl_statement("results_quarterly", rows, basis)


def upsert_results_yearly(rows: list[dict], basis: str) -> int:
    return _upsert_pl_statement("results_yearly", rows, basis)


def upsert_balance_sheet_yearly(rows: list[dict], basis: str) -> int:
    def key(r):
        co = _co_code(r)
        if co is None or r.get("YRC") is None:
            return None
        r["co_code"] = co
        r["basis"] = basis
        return {"co_code": co, "YRC": r["YRC"], "basis": basis}
    return _bulk_upsert("balance_sheet_yearly", rows, key)


def upsert_fii_dii(rows: list[dict]) -> int:
    """rows already merged by Date -- see cmots_scheduler.sync_fii_dii."""
    return _bulk_upsert("fii_dii_activity", rows, lambda r: {"Date": r.get("Date")}
                        if r.get("Date") else None)


def upsert_world_indices(rows: list[dict]) -> int:
    return _bulk_upsert("world_indices", rows,
                        lambda r: {"indexname": r.get("indexname"), "date": r.get("date")}
                        if r.get("indexname") and r.get("date") else None)


def upsert_key_financials(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        return {"co_code": co}
    return _bulk_upsert("key_financials", rows, key)


def upsert_company_profile(docs: list[dict]) -> int:
    """one doc per company, each already merged (by the caller) from CompProfile +
    BoardofDirectors + AboutCompany -- see cmots_scheduler.sync_company_profile."""
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        return {"co_code": co}
    return _bulk_upsert("company_profile", docs, key)


def upsert_shareholding_pattern(docs: list[dict]) -> int:
    """one doc per (company, quarter) -- see cmots_scheduler.sync_shareholding for
    how ShareholdingData and ShareHoldingPatternEquity get merged by YRC first."""
    def key(r):
        co = _co_code(r)
        if co is None or r.get("YRC") is None:
            return None
        r["co_code"] = co
        return {"co_code": co, "YRC": r["YRC"]}
    return _bulk_upsert("shareholding_pattern", docs, key)


# -------------------------------------------------------------------- mutual funds
_SCHEME_MASTER_FIELDS = (
    "mf_schcode", "mf_cocode", "amficode", "sch_name", "isin", "isin_Reinvestment",
    "FundManager", "LaunchDate", "Category", "MainCategory", "ClassCode", "frequency",
    "FundType", "InvestmentType", "InvestmentType1", "MCAPCategory", "riskometervalue",
    "MinInvestment", "IncrementalInvestment", "MinInvestment_SIP", "EntrytLoad", "ExitLoad",
    "navrs", "navdate", "SchemeAUM", "BMCode", "BenchmarkName", "1YEAR", "3YEAR", "5YEAR",
    "inception",
)
_SCHEME_RETURNS_FIELDS = (
    "mf_schcode", "DATE", "1WEEK", "1MONTH", "3MONTH", "6MONTH",
    "Category_1WRet", "Category_1MRet", "Category_3MRet", "Category_6MRet",
    "Category_1YRet", "Category_3YRet", "Category_5YRet", "Category_IncRet",
    "BM_1WRet", "BM_1MRet", "BM_3MRet", "BM_6MRet", "BM_1YRet", "BM_3YRet", "BM_5YRet",
)
_RISK_FACTORS_FIELDS = ("mf_schcode", "Date", "BETA", "SD", "TREYNOR", "ALPHA", "SHARPE",
                        "RSQUARE", "PTRatio", "pb", "pe", "Sortino")
_DIVIDEND_FIELDS = ("mf_schcode", "DivPer", "DivAmount", "DIVPERPU", "Divtype", "DivDate",
                    "RecordDate", "DIVTYPCODE")
_NFO_FIELDS = ("mf_schcode", "LName", "Sch_Name", "Launc_Date", "CLDATE", "MININVT",
              "OFFERPRICE", "SCHEME", "Objective", "SIZE", "VClass", "TypeName", "VClassCode")
_PORTFOLIO_ACTIVITY_FIELDS = ("mf_schcode", "CO_CODE", "invdate", "Perc_Hold", "mktvalue",
                              "NO_SHARES", "PortfolioDate", "AssetType", "rating")
_PEER_COMPARISON_FIELDS = ("mf_schcode", "Co_Name", "mf_cocode", "Ord", "SubCategory",
                           "SubCategoryCode", "Dividend", "DivUnit")
_STOCK_HOLDERS_FIELDS = ("sch_Name", "mf_schcode", "InvDate", "MktValue", "Co_Code", "Co_Name",
                         "Perc_Hold", "TOTNAV", "no_shares")


def upsert_mf_scheme_master(rows: list[dict]) -> int:
    def key(r):
        sch = _schcode(r)
        if sch is None:
            return None
        trimmed = _project(r, _SCHEME_MASTER_FIELDS)
        trimmed["mf_schcode"] = sch
        trimmed["_name_key"] = (r.get("sch_name") or "").strip().lower()
        r.clear()
        r.update(trimmed)
        return {"mf_schcode": sch}
    return _bulk_upsert("mf_scheme_master", rows, key)


def _mf_upsert(collection: str, rows: list[dict], fields: tuple[str, ...], extra_key=None):
    """the shared shape behind most MF upserts: trim to `fields`, key by
    mf_schcode (plus whatever `extra_key` adds, for the collections with more
    than one row per scheme)."""
    def key(r):
        sch = _schcode(r)
        if sch is None:
            return None
        trimmed = _project(r, fields)
        trimmed["mf_schcode"] = sch
        r.clear()
        r.update(trimmed)
        k = {"mf_schcode": sch}
        if extra_key:
            for field in extra_key:
                if r.get(field) is None:
                    return None
                k[field] = r[field]
        return k
    return _bulk_upsert(collection, rows, key)


def upsert_mf_scheme_returns(rows: list[dict]) -> int:
    return _mf_upsert("mf_scheme_returns", rows, _SCHEME_RETURNS_FIELDS)


def upsert_mf_risk_factors(rows: list[dict]) -> int:
    return _mf_upsert("mf_risk_factors", rows, _RISK_FACTORS_FIELDS)


def upsert_mf_dividends(rows: list[dict]) -> int:
    return _mf_upsert("mf_dividends", rows, _DIVIDEND_FIELDS, extra_key=("DivDate", "RecordDate"))


def upsert_mf_aum_history(rows: list[dict]) -> int:
    return _mf_upsert("mf_aum_history", rows, ("AUMDate", "AUM"), extra_key=("AUMDate",))


def upsert_mf_market_activity(rows: list[dict]) -> int:
    return _bulk_upsert("mf_market_activity", rows,
                        lambda r: {"TRANS_DATE": r.get("TRANS_DATE")}
                        if r.get("TRANS_DATE") else None)


def upsert_mf_nfo(rows: list[dict]) -> int:
    return _mf_upsert("mf_nfo", rows, _NFO_FIELDS)


def upsert_mf_portfolio_activity(rows: list[dict], direction: str) -> int:
    def key(r):
        sch = _schcode(r)
        co = r.get("CO_CODE")
        if sch is None or co is None or r.get("invdate") is None:
            return None
        trimmed = _project(r, _PORTFOLIO_ACTIVITY_FIELDS)
        trimmed["mf_schcode"] = sch
        trimmed["direction"] = direction
        r.clear()
        r.update(trimmed)
        return {"mf_schcode": sch, "CO_CODE": co, "invdate": r["invdate"], "direction": direction}
    return _bulk_upsert("mf_portfolio_activity", rows, key)


def upsert_mf_category_master(rows: list[dict]) -> int:
    return _bulk_upsert("mf_category_master", rows,
                        lambda r: {"MainCategory": r.get("MainCategory"),
                                   "VCLASSCODE": r.get("VCLASSCODE")}
                        if r.get("MainCategory") and r.get("VCLASSCODE") is not None else None)


def upsert_mf_peer_comparison(rows: list[dict]) -> int:
    return _mf_upsert("mf_peer_comparison", rows, _PEER_COMPARISON_FIELDS)


def upsert_mf_nav_history(rows: list[dict]) -> int:
    return _mf_upsert("mf_nav_history", rows, ("NAVDATE", "NAVRS", "ADJNAVRS"),
                      extra_key=("NAVDATE",))


def upsert_mf_stock_holders(rows: list[dict]) -> int:
    def key(r):
        sch = _schcode(r)
        co = r.get("Co_Code")
        if sch is None or co is None or r.get("InvDate") is None:
            return None
        trimmed = _project(r, _STOCK_HOLDERS_FIELDS)
        trimmed["mf_schcode"] = sch
        r.clear()
        r.update(trimmed)
        return {"Co_Code": co, "mf_schcode": sch, "InvDate": r["InvDate"]}
    return _bulk_upsert("mf_stock_holders", rows, key)


def upsert_mf_news(rows: list[dict], feed: str) -> int:
    """same feeds-accumulation idea as the equity `upsert_news`."""
    if not connect():
        raise RuntimeError("cmots store: mongo unavailable, cannot write")
    from pymongo import UpdateOne

    ops = []
    for r in rows:
        sno = r.get("sno") or r.get("Sno")
        if sno is None:
            continue
        trimmed = _project(r, ("section_name", "date", "time", "heading", "caption", "arttext"))
        trimmed["sno"] = sno
        ops.append(UpdateOne({"sno": sno}, {"$set": trimmed, "$addToSet": {"feeds": feed}},
                              upsert=True))
    if not ops:
        return 0
    result = _db.mf_news.bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


# -------------------------------------------------------------------------- ipo
_SYNOPSIS_FIELDS = ("lname", "regadd1", "regadd2", "regdist", "regstate", "regpin", "tel1",
                   "fax1", "email", "internet", "object", "OPENDATE", "CLOSDATE",
                   "APPNMONEY1", "APPNMONEY2", "ALOTMONEY1", "ALOTMONEY2", "MULTIPLES",
                   "MIN_APPLN", "PROJCOST", "publiss1", "TOT_EQTY", "ISSUEPRICE", "ParValue",
                   "IssuePri2", "listdate")
_PEER_FIELDS = ("CompanyName", "ISSUETYPE", "SerialNo", "CompanyCode_PeerCompany",
               "CompanyName_PeerCompany", "FaceValue", "Standalone_Consolidated", "YRC",
               "TotalIncome", "EPSBasic", "EPSDiluted", "NetAssetValue", "PEBasic",
               "PEDiluted", "RONW", "Comment")


def upsert_ipo_master(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        r["_name_key"] = (r.get("companyname") or "").strip().lower()
        return {"co_code": co}
    return _bulk_upsert("ipo_master", rows, key)


def upsert_ipo_calendar(rows: list[dict], status: str) -> int:
    """upcoming/open/closed all land in one collection -- an IPO is only ever in
    one bucket at a time, so `status` on the latest sync is enough; no need to
    key by status too."""
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        r["status"] = status
        return {"co_code": co}
    return _bulk_upsert("ipo_calendar", rows, key)


def upsert_ipo_listed_performance(rows: list[dict], exchange: str) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        r["exchange"] = exchange
        return {"co_code": co, "exchange": exchange}
    return _bulk_upsert("ipo_listed_performance", rows, key)


def upsert_ipo_details(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        return {"co_code": co}
    return _bulk_upsert("ipo_details", rows, key)


def upsert_ipo_financials(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None or r.get("yrc") is None:
            return None
        r["co_code"] = co
        return {"co_code": co, "yrc": r["yrc"]}
    return _bulk_upsert("ipo_financials", rows, key)


def upsert_ipo_synopsis(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        trimmed = _project(r, _SYNOPSIS_FIELDS)
        trimmed["co_code"] = co
        r.clear()
        r.update(trimmed)
        return {"co_code": co}
    return _bulk_upsert("ipo_synopsis", rows, key)


def upsert_ipo_strengths(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None or r.get("sno") is None:
            return None
        r["co_code"] = co
        return {"co_code": co, "sno": r["sno"]}
    return _bulk_upsert("ipo_strengths", rows, key)


def upsert_ipo_risks(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None or r.get("sno") is None:
            return None
        r["co_code"] = co
        return {"co_code": co, "sno": r["sno"]}
    return _bulk_upsert("ipo_risks", rows, key)


def upsert_ipo_peers(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None or r.get("SerialNo") is None:
            return None
        trimmed = _project(r, _PEER_FIELDS)
        trimmed["co_code"] = co
        r.clear()
        r.update(trimmed)
        return {"co_code": co, "SerialNo": r["SerialNo"]}
    return _bulk_upsert("ipo_peers", rows, key)


def upsert_ipo_draft_prospectus(rows: list[dict]) -> int:
    def key(r):
        co = _co_code(r)
        if co is None:
            return None
        r["co_code"] = co
        return {"co_code": co}
    return _bulk_upsert("ipo_draft_prospectus", rows, key)


# ------------------------------------------------------------------------- reads
# every function below is fail-open: mongo down or nothing found both return the
# same falsy shape, so a caller in the chat path never needs a special case.
def _refresh_name_cache() -> None:
    global _name_cache, _name_cache_at
    if not connect():
        return
    _name_cache = [
        (f"{d.get('_name_key', '')} {d.get('_symbol_key', '')}".strip(), d["co_code"])
        for d in _db.company_master.find({}, {"co_code": 1, "_name_key": 1, "_symbol_key": 1})
    ]
    _name_cache_at = time.time()


def get_company(text: str) -> dict | None:
    """a name, symbol, bse code or co_code -> the company_master row, or None.

    Tries exact/substring matches mongo can index first; only falls back to a
    fuzzy pass over a cached name list (10 min TTL) for a typo'd or partial name,
    since that's the one case that needs the full list in memory.
    """
    if not connect() or not text:
        return None
    text = text.strip()

    if re.fullmatch(r"\d+", text):
        row = _db.company_master.find_one({"co_code": int(text)})
        if row:
            return row

    key = text.lower()
    row = _db.company_master.find_one({"$or": [{"_symbol_key": key}, {"bsecode": text}]})
    if row:
        return row

    matches = list(_db.company_master.find({"_name_key": {"$regex": re.escape(key)}}).limit(5))
    if len(matches) == 1:
        return matches[0]

    if time.time() - _name_cache_at > _NAME_CACHE_TTL_S or not _name_cache:
        _refresh_name_cache()
    close = difflib.get_close_matches(key, [n for n, _ in _name_cache], n=1, cutoff=0.6)
    if close:
        co_code = next(co for n, co in _name_cache if n == close[0])
        return _db.company_master.find_one({"co_code": co_code})

    return matches[0] if matches else None


def active_company_codes() -> list[int]:
    """every co_code listed on BSE or NSE, per the last company_master sync --
    the universe the scheduler's per-company loop iterates over."""
    if not connect():
        return []
    rows = _db.company_master.find(
        {"$or": [{"bselistedflag": "Y"}, {"nselistedflag": "Y"}]}, {"co_code": 1})
    return [r["co_code"] for r in rows]


def latest_price(co_code: int, date: str | None = None) -> dict | None:
    if not connect():
        return None
    where = {"co_code": co_code} | ({"date": date} if date else {})
    return _db.prices_eod.find_one(where, sort=[("date", -1)])


def latest_keystats(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.keystats.find_one({"co_code": co_code})


def latest_ratios(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.financial_ratios.find_one({"co_code": co_code}, sort=[("yrc", -1)])


def peer_financials(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.key_financials.find_one({"co_code": co_code})


def latest_results_quarterly(co_code: int, basis: str = "C") -> dict | None:
    if not connect():
        return None
    row = _db.results_quarterly.find_one({"co_code": co_code, "basis": basis},
                                          sort=[("YRC", -1)])
    return row or _db.results_quarterly.find_one({"co_code": co_code}, sort=[("YRC", -1)])


def latest_results_yearly(co_code: int, basis: str = "C") -> dict | None:
    if not connect():
        return None
    row = _db.results_yearly.find_one({"co_code": co_code, "basis": basis}, sort=[("YRC", -1)])
    return row or _db.results_yearly.find_one({"co_code": co_code}, sort=[("YRC", -1)])


def latest_balance_sheet(co_code: int, basis: str = "C") -> dict | None:
    if not connect():
        return None
    row = _db.balance_sheet_yearly.find_one({"co_code": co_code, "basis": basis},
                                             sort=[("YRC", -1)])
    return row or _db.balance_sheet_yearly.find_one({"co_code": co_code}, sort=[("YRC", -1)])


def latest_fii_dii() -> dict | None:
    if not connect():
        return None
    return _db.fii_dii_activity.find_one({}, sort=[("Date", -1)])


def world_index(name: str) -> dict | None:
    if not connect():
        return None
    return _db.world_indices.find_one({"indexname": {"$regex": re.escape(name), "$options": "i"}},
                                       sort=[("date", -1)])


def get_profile(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.company_profile.find_one({"co_code": co_code})


def latest_shareholding(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.shareholding_pattern.find_one({"co_code": co_code}, sort=[("YRC", -1)])


def corporate_actions_for(co_code: int, kind: str | None = None, limit: int = 10) -> list[dict]:
    if not connect():
        return []
    where = {"co_code": co_code} | ({"CorpType": kind} if kind else {})
    return list(_db.corporate_actions.find(where).sort("CorpDate", -1).limit(max(1, limit)))


def news_for(co_code: int | None = None, limit: int = 10) -> list[dict]:
    if not connect():
        return []
    where = {"co_code": co_code} if co_code else {}
    return list(_db.news.find(where).sort("Date", -1).limit(max(1, limit)))


# -------------------------------------------------------------------- mutual funds
def active_mf_schcodes() -> list[int]:
    """every mf_schcode in the last scheme-master sync -- the universe the
    scheduler's per-scheme loops (peer comparison, NAV history) iterate over."""
    if not connect():
        return []
    return [r["mf_schcode"] for r in _db.mf_scheme_master.find({}, {"mf_schcode": 1})]


def get_mf_scheme(text: str) -> dict | None:
    """a scheme name (fuzzy), ISIN, or mf_schcode -> the mf_scheme_master row.
    Same three-tier approach as `get_company`: exact/indexed match first, a
    fuzzy pass over cached names only if that comes up empty."""
    if not connect() or not text:
        return None
    text = text.strip()

    if re.fullmatch(r"\d+", text):
        row = _db.mf_scheme_master.find_one({"mf_schcode": int(text)})
        if row:
            return row

    row = _db.mf_scheme_master.find_one({"isin": text})
    if row:
        return row

    key = text.lower()
    matches = list(_db.mf_scheme_master.find({"_name_key": {"$regex": re.escape(key)}}).limit(5))
    if len(matches) == 1:
        return matches[0]

    names = [(d.get("_name_key", ""), d["mf_schcode"])
             for d in _db.mf_scheme_master.find({}, {"mf_schcode": 1, "_name_key": 1})]
    close = difflib.get_close_matches(key, [n for n, _ in names], n=1, cutoff=0.6)
    if close:
        schcode = next(sch for n, sch in names if n == close[0])
        return _db.mf_scheme_master.find_one({"mf_schcode": schcode})

    return matches[0] if matches else None


def latest_mf_returns(mf_schcode: int) -> dict | None:
    if not connect():
        return None
    return _db.mf_scheme_returns.find_one({"mf_schcode": mf_schcode})


def latest_mf_risk(mf_schcode: int) -> dict | None:
    if not connect():
        return None
    return _db.mf_risk_factors.find_one({"mf_schcode": mf_schcode})


def mf_dividends_for(mf_schcode: int, limit: int = 10) -> list[dict]:
    if not connect():
        return []
    return list(_db.mf_dividends.find({"mf_schcode": mf_schcode})
                .sort("DivDate", -1).limit(max(1, limit)))


def latest_mf_aum(mf_schcode: int) -> dict | None:
    if not connect():
        return None
    return _db.mf_aum_history.find_one({"mf_schcode": mf_schcode}, sort=[("AUMDate", -1)])


def mf_nav_history_for(mf_schcode: int, limit: int = 30) -> list[dict]:
    if not connect():
        return []
    return list(_db.mf_nav_history.find({"mf_schcode": mf_schcode})
                .sort("NAVDATE", -1).limit(max(1, limit)))


def mf_peer(mf_schcode: int) -> dict | None:
    if not connect():
        return None
    return _db.mf_peer_comparison.find_one({"mf_schcode": mf_schcode})


def funds_holding_stock(co_code: int, limit: int = 10) -> list[dict]:
    """which mutual fund schemes hold this stock -- the equity <-> MF cross-link."""
    if not connect():
        return []
    return list(_db.mf_stock_holders.find({"Co_Code": co_code})
                .sort("Perc_Hold", -1).limit(max(1, limit)))


# -------------------------------------------------------------------------- ipo
def active_ipo_codes() -> list[int]:
    """every co_code in the last ipo_master sync -- the universe
    sync_ipo_per_company iterates over."""
    if not connect():
        return []
    return [r["co_code"] for r in _db.ipo_master.find({}, {"co_code": 1})]


def get_ipo(text: str) -> dict | None:
    """a company name (fuzzy), ISIN, or co_code -> the ipo_master row. Same
    three-tier approach as `get_company`/`get_mf_scheme`."""
    if not connect() or not text:
        return None
    text = text.strip()

    if re.fullmatch(r"\d+", text):
        row = _db.ipo_master.find_one({"co_code": int(text)})
        if row:
            return row

    row = _db.ipo_master.find_one({"isin": text})
    if row:
        return row

    key = text.lower()
    matches = list(_db.ipo_master.find({"_name_key": {"$regex": re.escape(key)}}).limit(5))
    if len(matches) == 1:
        return matches[0]

    names = [(d.get("_name_key", ""), d["co_code"])
             for d in _db.ipo_master.find({}, {"co_code": 1, "_name_key": 1})]
    close = difflib.get_close_matches(key, [n for n, _ in names], n=1, cutoff=0.6)
    if close:
        co = next(c for n, c in names if n == close[0])
        return _db.ipo_master.find_one({"co_code": co})

    return matches[0] if matches else None


def ipo_calendar_entry(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.ipo_calendar.find_one({"co_code": co_code})


def ipo_listed_performance(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.ipo_listed_performance.find_one({"co_code": co_code})


def ipo_details(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.ipo_details.find_one({"co_code": co_code})


def ipo_financials_for(co_code: int, limit: int = 5) -> list[dict]:
    if not connect():
        return []
    return list(_db.ipo_financials.find({"co_code": co_code}).sort("yrc", -1).limit(max(1, limit)))


def ipo_synopsis(co_code: int) -> dict | None:
    if not connect():
        return None
    return _db.ipo_synopsis.find_one({"co_code": co_code})


def ipo_strengths_for(co_code: int) -> list[dict]:
    if not connect():
        return []
    return list(_db.ipo_strengths.find({"co_code": co_code}).sort("sno", 1))


def ipo_risks_for(co_code: int) -> list[dict]:
    if not connect():
        return []
    return list(_db.ipo_risks.find({"co_code": co_code}).sort("sno", 1))


def ipo_peers_for(co_code: int) -> list[dict]:
    if not connect():
        return []
    return list(_db.ipo_peers.find({"co_code": co_code}).sort("SerialNo", 1))
