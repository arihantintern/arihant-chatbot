"""the standalone process that keeps `cmots` mongo data fresh.

Runs independently of the bot -- `cli.py` only ever reads what's here via
`cmots_store.py`'s lookup functions, so this can be killed, restarted, or moved
to another machine without touching the chat pipeline. Each job is wrapped in
`_run` so one job's exception is logged and skipped rather than taking the whole
process down; a job that mostly succeeds (per-company loop, one bad company)
still counts and reports its own partial failures.

    python cmots_scheduler.py             start the real cron schedule
    python cmots_scheduler.py --once      run every job once, immediately, then exit
    python cmots_scheduler.py --backfill-prices [days]   one-time price history pull
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import cmots
import cmots_ipo
import cmots_mf
import cmots_store
from config import (
    CMOTS_BULK_EOD_CRON, CMOTS_MF_PER_SCHEME_CRON, CMOTS_NEWS_CRON_MINUTES,
    CMOTS_PER_COMPANY_CRON, CMOTS_WORKERS,
)


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _run(name: str, fn) -> None:
    started = datetime.now()
    try:
        result = fn()
        _log(f"{name}: ok, {result} ({datetime.now() - started})")
    except Exception as e:
        _log(f"{name}: FAILED -- {type(e).__name__}: {e}")


# ------------------------------------------------------------------------- bulk jobs
def sync_company_master() -> str:
    rows = cmots.fetch_company_master()
    n = cmots_store.upsert_company_master(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_prices() -> str:
    total_fetched = total_written = 0
    for exchange in ("nse", "bse"):
        rows = cmots.fetch_bhav_copy(exchange)
        total_fetched += len(rows)
        total_written += cmots_store.upsert_prices_eod(rows)
    return f"{total_fetched} fetched, {total_written} written"


def sync_corporate_actions() -> str:
    # 30Day, not Today -- dividends/bonuses/splits are rare enough that "today" is
    # empty for almost every company almost every day. A rolling 30-day window
    # upserted daily gives corporate_actions_for() enough history to actually
    # answer "when did X last pay a dividend" without a separate backfill job.
    rows = cmots.fetch_corporate_actions("30Day")
    n = cmots_store.upsert_corporate_actions(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_results_calendar() -> str:
    rows = cmots.fetch_results_calendar("week")
    n = cmots_store.upsert_results_calendar(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_fii_dii() -> str:
    """FIICash and DIICash come from two separate calls -- merged by Date here
    so a lookup gets one row with both, not two half-rows."""
    merged: dict[str, dict] = {}
    for category in ("FIICash", "DIICash"):
        for row in cmots.fetch_fii_dii(category):
            date = row.get("Date")
            if date:
                merged.setdefault(date, {}).update(row)
    n = cmots_store.upsert_fii_dii(list(merged.values()))
    return f"{len(merged)} fetched, {n} written"


def sync_world_indices() -> str:
    rows = cmots.fetch_world_indices()
    n = cmots_store.upsert_world_indices(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_announcements_and_news() -> str:
    """the archive endpoints (fetch_news_archive/fetch_stock_alert_archive), not
    fetch_market_news/fetch_daily_announcements/fetch_result_announcements --
    those were confirmed live to carry an empty co_code on nearly every row,
    which made the resulting news undiscoverable by company. A 30-day window,
    same reasoning as sync_corporate_actions: re-synced daily, upserted by Sno,
    so it's both idempotent and self-healing if a day's run is missed.
    """
    total_fetched = total_written = 0
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    start_s, end_s = start.strftime("%d-%b-%Y"), end.strftime("%d-%b-%Y")

    for section in cmots.NEWS_ARCHIVE_SECTIONS:
        rows = cmots.fetch_news_archive(section, start_s, end_s)
        total_fetched += len(rows)
        total_written += cmots_store.upsert_news(rows, feed=section)

    rows = cmots.fetch_stock_alert_archive(start_s, end_s)
    total_fetched += len(rows)
    total_written += cmots_store.upsert_news(rows, feed="stock_alert")

    return f"{total_fetched} fetched, {total_written} written"


def sync_stock_wise_news() -> str:
    """LatestStockWiseNews, batched 10 companies per call -- the most reliable
    link there is, since it's fetched BY company rather than hoping an archive
    row got tagged correctly. ~660 calls for the full equity universe, same
    order of magnitude as the other per-company loops.
    """
    co_codes = cmots_store.active_company_codes()
    if not co_codes:
        raise RuntimeError("no companies in company_master -- run sync_company_master first")
    batches = [co_codes[i:i + 10] for i in range(0, len(co_codes), 10)]
    _log(f"sync_stock_wise_news: {len(co_codes)} companies, {len(batches)} batches")

    written = failed = 0

    def _one(batch):
        return cmots_store.upsert_news(cmots.fetch_stock_wise_news(batch), feed="stock_wise")

    with ThreadPoolExecutor(max_workers=CMOTS_WORKERS) as pool:
        futures = {pool.submit(_one, b): b for b in batches}
        for future in as_completed(futures):
            try:
                written += future.result()
            except Exception:
                failed += 1

    return f"{written} written, {failed} batches failed"


# ------------------------------------------------------------------- per-company loop
def _one_profile(co: int) -> int:
    """CompProfile + BoardofDirectors + AboutCompany, merged into one doc -- these
    three only make sense together (a profile with no board or bio is half a
    profile), so they're fetched and written as a unit, not three separate
    collections like the others below."""
    profile = cmots.fetch_company_profile(co)
    if not profile:
        return 0
    directors = cmots.fetch_board_of_directors(co)
    about = cmots.fetch_about_company(co)
    doc = {**profile, "co_code": co, "directors": directors,
           "about_company": (about or {}).get("CompanyBackground")}
    return cmots_store.upsert_company_profile([doc])


def _one_shareholding(co: int) -> int:
    """ShareholdingData + ShareHoldingPatternEquity report the same quarters from
    two different cuts (one has Pledged_Per, the other a cleaner DII breakdown) --
    merged here by YRC so a lookup doesn't need to know there were ever two calls."""
    merged: dict[int, dict] = {}
    for rows in (cmots.fetch_shareholding_data(co), cmots.fetch_shareholding_pattern(co)):
        for row in rows:
            yrc = row.get("YRC")
            if yrc is not None:
                merged.setdefault(yrc, {}).update(row)
    return cmots_store.upsert_shareholding_pattern(list(merged.values())) if merged else 0


def sync_fundamentals() -> str:
    """keystats/ratios/peer-financials/profile/shareholding for every actively-
    listed company.

    One thread pool per fetch type (not one pool doing all five per company)
    keeps a slow/failing endpoint from head-of-line blocking the others.
    """
    co_codes = cmots_store.active_company_codes()
    if not co_codes:
        raise RuntimeError("no companies in company_master -- run sync_company_master first")
    _log(f"sync_fundamentals: {len(co_codes)} companies")

    labels = ("keystats", "financial_ratios", "key_financials", "company_profile",
              "shareholding_pattern")
    written = {label: 0 for label in labels}
    failed = {label: 0 for label in labels}

    def _one_keystats(co):
        row = cmots.fetch_keystats(co)
        return cmots_store.upsert_keystats([row]) if row else 0

    def _one_ratios(co):
        return cmots_store.upsert_financial_ratios(cmots.fetch_financial_ratios(co))

    def _one_key_financials(co):
        return cmots_store.upsert_key_financials(cmots.fetch_key_financials(co))

    def _one_results_quarterly(co):
        total = 0
        for basis in ("S", "C"):
            total += cmots_store.upsert_results_quarterly(
                cmots.fetch_results_quarterly(co, basis), basis)
        return total

    def _one_results_yearly(co):
        total = 0
        for basis in ("S", "C"):
            total += cmots_store.upsert_results_yearly(
                cmots.fetch_results_yearly(co, basis), basis)
        return total

    def _one_balance_sheet(co):
        total = 0
        for basis in ("S", "C"):
            total += cmots_store.upsert_balance_sheet_yearly(
                cmots.fetch_balance_sheet_yearly(co, basis), basis)
        return total

    labels = labels + ("results_quarterly", "results_yearly", "balance_sheet_yearly")
    written.update({label: 0 for label in labels[-3:]})
    failed.update({label: 0 for label in labels[-3:]})

    for label, fn in (("keystats", _one_keystats), ("financial_ratios", _one_ratios),
                      ("key_financials", _one_key_financials),
                      ("company_profile", _one_profile),
                      ("shareholding_pattern", _one_shareholding),
                      ("results_quarterly", _one_results_quarterly),
                      ("results_yearly", _one_results_yearly),
                      ("balance_sheet_yearly", _one_balance_sheet)):
        with ThreadPoolExecutor(max_workers=CMOTS_WORKERS) as pool:
            futures = {pool.submit(fn, co): co for co in co_codes}
            for future in as_completed(futures):
                try:
                    written[label] += future.result()
                except Exception:
                    failed[label] += 1
        _log(f"  {label}: {written[label]} written, {failed[label]} failed")

    return f"written={written} failed={failed}"


# ------------------------------------------------------------------- historical backfill
def backfill_prices(days: int = 365) -> str:
    """one-time per-company history via CompanyChart. Ongoing history builds up
    incrementally from the daily bulk EOD-Bhav-Copy job after this runs once."""
    co_codes = cmots_store.active_company_codes()
    if not co_codes:
        raise RuntimeError("no companies in company_master -- run sync_company_master first")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    start_s, end_s = start.strftime("%d-%b-%Y"), end.strftime("%d-%b-%Y")
    _log(f"backfill_prices: {len(co_codes)} companies, {start_s} .. {end_s}")

    written = failed = 0

    def _one(co):
        rows = cmots.fetch_historical_price(co, start_s, end_s)
        return cmots_store.upsert_prices_eod(rows)

    with ThreadPoolExecutor(max_workers=CMOTS_WORKERS) as pool:
        futures = {pool.submit(_one, co): co for co in co_codes}
        for future in as_completed(futures):
            try:
                written += future.result()
            except Exception as e:
                failed += 1
                _log(f"  backfill failed for co_code={futures[future]}: {e}")

    return f"{written} written, {failed} failed"


# ------------------------------------------------------------------------ mutual funds
def sync_mf_scheme_master() -> str:
    rows = cmots_mf.fetch_scheme_master()
    n = cmots_store.upsert_mf_scheme_master(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_mf_returns() -> str:
    rows = cmots_mf.fetch_scheme_returns()
    n = cmots_store.upsert_mf_scheme_returns(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_mf_risk_factors() -> str:
    rows = cmots_mf.fetch_risk_factors()
    n = cmots_store.upsert_mf_risk_factors(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_mf_dividends() -> str:
    rows = cmots_mf.fetch_dividend_details()
    n = cmots_store.upsert_mf_dividends(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_mf_aum() -> str:
    rows = cmots_mf.fetch_aum_growth()
    n = cmots_store.upsert_mf_aum_history(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_mf_market_activity() -> str:
    rows = cmots_mf.fetch_market_activity()
    n = cmots_store.upsert_mf_market_activity(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_mf_nfo() -> str:
    rows = cmots_mf.fetch_nfo()
    n = cmots_store.upsert_mf_nfo(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_mf_portfolio_activity() -> str:
    total_fetched = total_written = 0
    for direction in ("In", "Out"):
        rows = cmots_mf.fetch_portfolio_activity(direction)
        total_fetched += len(rows)
        total_written += cmots_store.upsert_mf_portfolio_activity(rows, direction.lower())
    return f"{total_fetched} fetched, {total_written} written"


def sync_mf_category_master() -> str:
    total_fetched = total_written = 0
    for category in cmots_mf.MF_CATEGORIES:
        rows = cmots_mf.fetch_category_master(category)
        total_fetched += len(rows)
        total_written += cmots_store.upsert_mf_category_master(rows)
    return f"{total_fetched} fetched, {total_written} written"


def sync_mf_per_scheme() -> str:
    """peer comparison + NAV history for every scheme (no bulk wildcard exists
    for either -- confirmed by testing), plus stock-holders for every equity
    company already known from company_master. Three different universes, three
    thread pools, same reasoning as sync_fundamentals: one slow endpoint
    shouldn't block the other two.
    """
    schcodes = cmots_store.active_mf_schcodes()
    if not schcodes:
        raise RuntimeError("no schemes in mf_scheme_master -- run sync_mf_scheme_master first")
    co_codes = cmots_store.active_company_codes()
    _log(f"sync_mf_per_scheme: {len(schcodes)} schemes, {len(co_codes)} stocks")

    labels = ("mf_peer_comparison", "mf_nav_history", "mf_stock_holders")
    written = {label: 0 for label in labels}
    failed = {label: 0 for label in labels}

    def _one_peer(sch):
        return cmots_store.upsert_mf_peer_comparison(cmots_mf.fetch_peer_comparison(sch))

    def _one_nav(sch):
        return cmots_store.upsert_mf_nav_history(cmots_mf.fetch_nav_history(sch))

    def _one_holders(co):
        return cmots_store.upsert_mf_stock_holders(cmots_mf.fetch_stock_holders(co))

    for label, fn, universe in (("mf_peer_comparison", _one_peer, schcodes),
                                ("mf_nav_history", _one_nav, schcodes),
                                ("mf_stock_holders", _one_holders, co_codes)):
        with ThreadPoolExecutor(max_workers=CMOTS_WORKERS) as pool:
            futures = {pool.submit(fn, item): item for item in universe}
            for future in as_completed(futures):
                try:
                    written[label] += future.result()
                except Exception:
                    failed[label] += 1
        _log(f"  {label}: {written[label]} written, {failed[label]} failed")

    return f"written={written} failed={failed}"


# ------------------------------------------------------------------------------- ipo
def sync_ipo_master() -> str:
    rows = cmots_ipo.fetch_ipo_master()
    n = cmots_store.upsert_ipo_master(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_ipo_calendar() -> str:
    total_fetched = total_written = 0
    for status in cmots_ipo.CALENDAR_STATUSES:
        rows = cmots_ipo.fetch_calendar(status)
        total_fetched += len(rows)
        total_written += cmots_store.upsert_ipo_calendar(rows, status)
    return f"{total_fetched} fetched, {total_written} written"


def sync_ipo_listed_performance() -> str:
    total_fetched = total_written = 0
    for exchange in ("bse", "nse"):
        rows = cmots_ipo.fetch_recently_listed(exchange)
        total_fetched += len(rows)
        total_written += cmots_store.upsert_ipo_listed_performance(rows, exchange)
    return f"{total_fetched} fetched, {total_written} written"


def sync_ipo_draft_prospectus() -> str:
    rows = cmots_ipo.fetch_draft_prospectus()
    n = cmots_store.upsert_ipo_draft_prospectus(rows)
    return f"{len(rows)} fetched, {n} written"


def sync_ipo_per_company() -> str:
    """details/financials/synopsis/strengths/risks/peers for every IPO in
    ipo_master -- only ~150 companies total, so this finishes in seconds even
    though none of the six have a bulk wildcard."""
    co_codes = cmots_store.active_ipo_codes()
    if not co_codes:
        raise RuntimeError("no IPOs in ipo_master -- run sync_ipo_master first")
    _log(f"sync_ipo_per_company: {len(co_codes)} IPOs")

    labels = ("ipo_details", "ipo_financials", "ipo_synopsis", "ipo_strengths",
              "ipo_risks", "ipo_peers")
    written = {label: 0 for label in labels}
    failed = {label: 0 for label in labels}

    def _one_details(co):
        row = cmots_ipo.fetch_ipo_details(co)
        return cmots_store.upsert_ipo_details([row]) if row else 0

    def _one_financials(co):
        return cmots_store.upsert_ipo_financials(cmots_ipo.fetch_ipo_financials(co))

    def _one_synopsis(co):
        row = cmots_ipo.fetch_ipo_synopsis(co)
        return cmots_store.upsert_ipo_synopsis([row]) if row else 0

    def _one_strengths(co):
        return cmots_store.upsert_ipo_strengths(cmots_ipo.fetch_ipo_strengths(co))

    def _one_risks(co):
        return cmots_store.upsert_ipo_risks(cmots_ipo.fetch_ipo_risks(co))

    def _one_peers(co):
        return cmots_store.upsert_ipo_peers(cmots_ipo.fetch_ipo_peers(co))

    for label, fn in (("ipo_details", _one_details), ("ipo_financials", _one_financials),
                      ("ipo_synopsis", _one_synopsis), ("ipo_strengths", _one_strengths),
                      ("ipo_risks", _one_risks), ("ipo_peers", _one_peers)):
        with ThreadPoolExecutor(max_workers=CMOTS_WORKERS) as pool:
            futures = {pool.submit(fn, co): co for co in co_codes}
            for future in as_completed(futures):
                try:
                    written[label] += future.result()
                except Exception:
                    failed[label] += 1
        _log(f"  {label}: {written[label]} written, {failed[label]} failed")

    return f"written={written} failed={failed}"


# --------------------------------------------------------------------------- wiring
BULK_JOBS = [
    ("sync_company_master", sync_company_master),
    ("sync_prices", sync_prices),
    ("sync_corporate_actions", sync_corporate_actions),
    ("sync_results_calendar", sync_results_calendar),
    # mutual funds -- scheme_master runs here too, since sync_mf_per_scheme (below)
    # needs its scheme universe already synced
    ("sync_mf_scheme_master", sync_mf_scheme_master),
    ("sync_mf_returns", sync_mf_returns),
    ("sync_mf_risk_factors", sync_mf_risk_factors),
    ("sync_mf_dividends", sync_mf_dividends),
    ("sync_mf_aum", sync_mf_aum),
    ("sync_mf_market_activity", sync_mf_market_activity),
    ("sync_mf_nfo", sync_mf_nfo),
    ("sync_mf_portfolio_activity", sync_mf_portfolio_activity),
    ("sync_mf_category_master", sync_mf_category_master),
    # ipo -- master runs here too, since sync_ipo_per_company needs it synced first
    ("sync_ipo_master", sync_ipo_master),
    ("sync_ipo_calendar", sync_ipo_calendar),
    ("sync_ipo_listed_performance", sync_ipo_listed_performance),
    ("sync_ipo_draft_prospectus", sync_ipo_draft_prospectus),
    ("sync_fii_dii", sync_fii_dii),
    ("sync_world_indices", sync_world_indices),
]
NEWS_JOB = ("sync_announcements_and_news", sync_announcements_and_news)
FUNDAMENTALS_JOB = ("sync_fundamentals", sync_fundamentals)
MF_PER_SCHEME_JOB = ("sync_mf_per_scheme", sync_mf_per_scheme)
IPO_PER_COMPANY_JOB = ("sync_ipo_per_company", sync_ipo_per_company)
STOCK_WISE_NEWS_JOB = ("sync_stock_wise_news", sync_stock_wise_news)


def run_once() -> None:
    for name, fn in BULK_JOBS:
        _run(name, fn)
    _run(*NEWS_JOB)
    _run(*FUNDAMENTALS_JOB)
    _run(*MF_PER_SCHEME_JOB)
    _run(*IPO_PER_COMPANY_JOB)
    _run(*STOCK_WISE_NEWS_JOB)


def main() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    for name, fn in BULK_JOBS:
        scheduler.add_job(lambda n=name, f=fn: _run(n, f), "cron", id=name, **CMOTS_BULK_EOD_CRON)
    scheduler.add_job(lambda: _run(*NEWS_JOB), "interval", id=NEWS_JOB[0],
                       minutes=CMOTS_NEWS_CRON_MINUTES)
    scheduler.add_job(lambda: _run(*FUNDAMENTALS_JOB), "cron", id=FUNDAMENTALS_JOB[0],
                       **CMOTS_PER_COMPANY_CRON)
    scheduler.add_job(lambda: _run(*MF_PER_SCHEME_JOB), "cron", id=MF_PER_SCHEME_JOB[0],
                       **CMOTS_MF_PER_SCHEME_CRON)
    # ~150 IPOs total, finishes in seconds -- rides along on the equity per-company
    # slot rather than needing its own offset
    scheduler.add_job(lambda: _run(*IPO_PER_COMPANY_JOB), "cron", id=IPO_PER_COMPANY_JOB[0],
                       **CMOTS_PER_COMPANY_CRON)
    scheduler.add_job(lambda: _run(*STOCK_WISE_NEWS_JOB), "cron", id=STOCK_WISE_NEWS_JOB[0],
                       **CMOTS_PER_COMPANY_CRON)
    _log(f"cmots_scheduler started -- bulk EOD {CMOTS_BULK_EOD_CRON}, "
         f"fundamentals {CMOTS_PER_COMPANY_CRON}, mf per-scheme {CMOTS_MF_PER_SCHEME_CRON}, "
         f"news every {CMOTS_NEWS_CRON_MINUTES}m")
    scheduler.start()


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    elif "--backfill-prices" in sys.argv:
        i = sys.argv.index("--backfill-prices")
        days = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() else 365
        _run("backfill_prices", lambda: backfill_prices(days))
    else:
        main()
