"""the AI-driven replacement for the old regex cmots_answer in chain.py.

One small-model "planner" call reads the question and decides which tool(s) it
needs -- query_cmots (Arihant's own market-data feed), web_search (anything
CMOTS doesn't track), both, or neither (a plain definition it already knows).
Whatever it asked for actually gets fetched, then one CHAT_MODEL "writer" call
turns the question plus whatever came back into one answer.

This is what lets "PE and P/B and description of TCS" answer all three in one
go, and what a "fundamental report" or "review" actually is underneath -- there
is no separate report/review code path, just a planner that decided to ask for
a lot of fields (report) or fields plus a web search (review).

Same position in chain.py's router as the old tier: cmots_ai_answer() returning
None means "not this tier", not "no data" -- arihant/pdf/web/general still get
a turn at a question this doesn't resolve.

A cache sits in front of the model calls, checked before either one runs. A
CMOTS-only answer is cached until the next scheduler sync (see config.py's
CMOTS_*_CRON) -- it is never any staler than the data it was built from. An
answer that touched the web is cached for a short while instead, matching how
often news itself is polled.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

import cmots_store
import web
from config import (
    CHAT_MODEL, CHAT_TEMPERATURE, CMOTS_AI_PLANNER_TURNS, CMOTS_AI_WEB_CACHE_TTL_S,
    CMOTS_AI_WRITER_PROMPT, CMOTS_BULK_EOD_CRON, CMOTS_FIELD_NAMES,
    CMOTS_MF_PER_SCHEME_CRON, CMOTS_PER_COMPANY_CRON, CMOTS_WORLD_INDEX_ALIASES,
    NOT_ON_CMOTS, SMALL_MODEL,
)


# gpt-5.6-luna (and reasoning models generally) reject tool calls made together
# with its default reasoning_effort on the chat-completions endpoint langchain
# uses -- "Function tools with reasoning_effort are not supported ... set
# reasoning_effort to 'none'" is the API's own suggested fix. Only the planner
# calls tools, so only it needs this; the writer is unaffected.
small = ChatOpenAI(model=SMALL_MODEL, temperature=0, reasoning_effort="none")
model = ChatOpenAI(model=CHAT_MODEL, temperature=CHAT_TEMPERATURE)


# ------------------------------------------------------------------- the tools
# these exist only to hand bind_tools() a name + schema. When a call is actually
# executed we call the underlying implementation directly (_resolve_fields,
# web.search) rather than .invoke()-ing the decorated tool, so results stay rich
# python objects instead of being squeezed through the string-only tool-message
# protocol -- there is no multi-turn agent loop here to require that.
@tool
def query_cmots(company: str, fields: list[str]) -> dict:
    """Look up a company, mutual fund scheme, IPO, or market index in Arihant's
    CMOTS market-data feed. `company` names what to resolve (blank for
    fii_dii_flow); `fields` is one or more field names from the documented set.
    Returns {field: value_or_None}."""
    return _resolve_fields(company, fields)


@tool
def web_search(query: str) -> str:
    """Search the web for something Arihant's CMOTS feed cannot supply -- recent
    commentary/opinion beyond its own news feed, or general context for a
    review. Do not use for facts query_cmots can already answer."""
    return web.format_pages(web.search(query))


# ------------------------------------------------ field dispatch (the fetching)
# a straight port of the old cmots_answer's dispatch logic, restructured to take
# a set of fields instead of one metric, and to return raw values instead of a
# pre-formatted sentence -- the writer model does the phrasing now.
_MF_FIELDS = {"mf_nav", "mf_returns", "mf_risk", "mf_aum"}
_IPO_FIELDS = {"ipo_status", "ipo_price", "ipo_subscription", "ipo_listing_gain",
               "ipo_risks", "ipo_strengths"}
_KEYSTATS_FIELD = {"pe": "PE", "market_cap": "MCAP", "eps": "EPS",
                   "book_value": "BookValue", "roe": "ROE_TTM", "roce": "ROCE_TTM"}
_ACTION_KIND = {"dividend": "Dividend", "bonus": "Bonus", "split": "Split",
                "buyback": "Buyback", "merger": "Merger"}
_PL_FIELD = {"revenue": "total_income", "net_profit": "net_profit"}


def _resolve_fields(company: str, fields: list[str]) -> dict:
    """company/scheme/index name + requested field names -> {field: value}.

    Fields the model asked for that aren't in the documented set are dropped
    rather than raised on -- a hallucinated field name should cost that one
    fact, not the whole answer.
    """
    fields = [f for f in dict.fromkeys(fields) if f in CMOTS_FIELD_NAMES]
    out: dict = {}
    remaining = set(fields)

    if "fii_dii_flow" in remaining:
        out["fii_dii_flow"] = cmots_store.latest_fii_dii()
        remaining.discard("fii_dii_flow")

    if "world_index" in remaining:
        alias = next((v for k, v in CMOTS_WORLD_INDEX_ALIASES.items()
                      if k in (company or "").lower()), None)
        out["world_index"] = cmots_store.world_index(alias) if alias else None
        remaining.discard("world_index")

    if not remaining:
        return out

    ipo_fields = remaining & _IPO_FIELDS
    mf_fields = remaining & _MF_FIELDS
    fund_holders = "fund_holders" in remaining
    equity_fields = remaining - _IPO_FIELDS - _MF_FIELDS - {"fund_holders"}

    # an IPO question resolves against ipo_master, not company_master -- a
    # pre-listing company usually isn't in company_master at all yet.
    if ipo_fields:
        ipo = cmots_store.get_ipo(company)
        if not ipo:
            out.update({f: None for f in ipo_fields})
        else:
            co, iname = ipo["co_code"], ipo.get("companyname", company)
            out["_resolved"] = iname
            if "ipo_status" in ipo_fields:
                out["ipo_status"] = cmots_store.ipo_calendar_entry(co) \
                    or cmots_store.ipo_details(co)
            if "ipo_price" in ipo_fields:
                out["ipo_price"] = cmots_store.ipo_calendar_entry(co)
            if "ipo_subscription" in ipo_fields:
                out["ipo_subscription"] = cmots_store.ipo_calendar_entry(co)
            if "ipo_listing_gain" in ipo_fields:
                out["ipo_listing_gain"] = cmots_store.ipo_listed_performance(co)
            if "ipo_risks" in ipo_fields:
                out["ipo_risks"] = cmots_store.ipo_risks_for(co)[:5]
            if "ipo_strengths" in ipo_fields:
                out["ipo_strengths"] = cmots_store.ipo_strengths_for(co)

    # a fund question resolves against scheme names, not company names -- "NAV
    # of X" means nothing as a stock lookup.
    if mf_fields:
        scheme = cmots_store.get_mf_scheme(company)
        if not scheme:
            out.update({f: None for f in mf_fields})
        else:
            sch, sname = scheme["mf_schcode"], scheme.get("sch_name", company)
            out["_resolved"] = sname
            if "mf_nav" in mf_fields:
                out["mf_nav"] = {"nav": scheme.get("navrs"), "as_of": scheme.get("navdate")}
            if "mf_returns" in mf_fields:
                r = cmots_store.latest_mf_returns(sch) or {}
                out["mf_returns"] = {"1yr": scheme.get("1YEAR"), "3yr": scheme.get("3YEAR"),
                                      "1mo": r.get("1MONTH")}
            if "mf_risk" in mf_fields:
                out["mf_risk"] = cmots_store.latest_mf_risk(sch)
            if "mf_aum" in mf_fields:
                out["mf_aum"] = cmots_store.latest_mf_aum(sch)

    if equity_fields or fund_holders:
        stock = cmots_store.get_company(company)
        if not stock:
            out.update({f: None for f in equity_fields | ({"fund_holders"} if fund_holders else set())})
            return out
        co, cname = stock["co_code"], stock.get("companyname", company)
        out["_resolved"] = cname

        if fund_holders:
            out["fund_holders"] = cmots_store.funds_holding_stock(co, limit=5)

        if "price" in equity_fields:
            out["price"] = cmots_store.latest_price(co)

        hit = equity_fields & _KEYSTATS_FIELD.keys()
        if hit:
            ks = cmots_store.latest_keystats(co) or {}
            out.update({f: ks.get(_KEYSTATS_FIELD[f]) for f in hit})

        hit = equity_fields & _PL_FIELD.keys()
        if hit:
            row = cmots_store.latest_results_yearly(co) \
                or cmots_store.latest_results_quarterly(co) or {}
            out.update({f: row.get(_PL_FIELD[f]) for f in hit})

        if "total_assets" in equity_fields:
            row = cmots_store.latest_balance_sheet(co)
            out["total_assets"] = row and row.get("TotalAssets")

        hit = equity_fields & _ACTION_KIND.keys()
        if hit:
            acts = cmots_store.corporate_actions_for(co, limit=10)
            for f in hit:
                kind = _ACTION_KIND[f].lower()
                matches = [a for a in acts if kind in (a.get("CorpType") or "").lower()]
                out[f] = matches[0] if matches else None

        if "news" in equity_fields:
            out["news"] = cmots_store.news_for(co, limit=5)

        if equity_fields & {"chairman", "board", "about"}:
            profile = cmots_store.get_profile(co) or {}
            if "chairman" in equity_fields:
                out["chairman"] = profile.get("CHAIRMAN")
            if "board" in equity_fields:
                out["board"] = profile.get("directors")
            if "about" in equity_fields:
                about = profile.get("about_company")
                out["about"] = about.split("\r\n\r\n")[0].strip() if about else None

        if "shareholding" in equity_fields:
            out["shareholding"] = cmots_store.latest_shareholding(co)

    return out


# ------------------------------------------------------------------- the cache
# in-process, expiry-checked-on-read. Two tiers, so a literal repeat costs zero
# model calls and a paraphrase of the same fact costs only the cheap planner
# call needed to work out that it means the same thing.
#
#   _answers[semantic_key] -> {"value": str, "expires_at": epoch}
#   _aliases[normalized_question_text] -> semantic_key
_answers: dict[tuple, dict] = {}
_aliases: dict[str, tuple] = {}


def _normalize_question(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower()).rstrip("?.! ")


def _next_sync_epoch() -> float:
    """the next of the three daily cmots sync jobs, whichever comes first -- a
    correct-by-construction TTL for a pure query_cmots answer: it is stale no
    later than the moment its underlying collection actually refreshes."""
    now = datetime.now()
    candidates = []
    for cron in (CMOTS_BULK_EOD_CRON, CMOTS_PER_COMPANY_CRON, CMOTS_MF_PER_SCHEME_CRON):
        t = now.replace(hour=cron["hour"], minute=cron["minute"], second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        candidates.append(t)
    return min(candidates).timestamp()


def _cache_get(key: tuple | None) -> str | None:
    if key is None:
        return None
    entry = _answers.get(key)
    if entry is None:
        return None
    if entry["expires_at"] < time.time():
        _answers.pop(key, None)
        return None
    return entry["value"]


def _cache_get_by_text(question: str) -> str | None:
    return _cache_get(_aliases.get(_normalize_question(question)))


def _cache_set(key: tuple, value: str, used_web: bool, question: str) -> None:
    expires = time.time() + CMOTS_AI_WEB_CACHE_TTL_S if used_web else _next_sync_epoch()
    _answers[key] = {"value": value, "expires_at": expires}
    _aliases[_normalize_question(question)] = key


# --------------------------------------------------------- planner and writer
planner = ChatPromptTemplate.from_messages(CMOTS_AI_PLANNER_TURNS) \
    | small.bind_tools([query_cmots, web_search])

writer = PromptTemplate.from_template(CMOTS_AI_WRITER_PROMPT) | model


def _write(question: str, cmots_data: dict, web_data: str | None) -> str | None:
    try:
        draft = writer.invoke({
            "asked": question,
            "cmots_data": json.dumps(cmots_data, default=str) if cmots_data else "(none requested)",
            "web_data": web_data or "(none requested)",
            "sentinel": NOT_ON_CMOTS,
        }).content.strip()
    except Exception as e:
        print("  [cmots-ai writer failed]", type(e).__name__, e)
        return None
    return draft if draft and NOT_ON_CMOTS.lower() not in draft.lower() else None


def cmots_ai_answer(question: str) -> str | None:
    """None means "not this tier" -- a PDF/rating question, something out of
    scope, or a fetch that came back empty. Everything else in chain.py's
    router still gets a turn at a question this doesn't resolve."""
    cached = _cache_get_by_text(question)
    if cached is not None:
        return cached                      # zero model calls -- exact-text repeat

    try:
        msg = planner.invoke({"question": question})
    except Exception as e:
        print("  [cmots-ai planner failed]", type(e).__name__, e)
        return None                        # fail-open, same as a dead ollama today

    if not msg.tool_calls:
        # never let this tier answer on the planner's unchecked say-so -- no
        # tool call means "not this tier", always, so in_scope()'s dedicated
        # classifier (which runs right after this in chain.py) is the one that
        # decides whether the question gets refused or handed to web/general.
        return None

    cmots_calls = [tc for tc in msg.tool_calls if tc["name"] == "query_cmots"]
    web_calls = [tc for tc in msg.tool_calls if tc["name"] == "web_search"]

    companies = tuple(sorted({(tc["args"].get("company") or "").strip().lower()
                              for tc in cmots_calls}))
    fields = tuple(sorted({f for tc in cmots_calls for f in tc["args"].get("fields", [])}))
    web_query = web_calls[0]["args"].get("query") if web_calls else None
    # the web query itself goes into the key, not just "did it use the web" --
    # otherwise two differently-intentioned web-backed questions about the same
    # company with the same field set could return each other's web content.
    key = (companies, fields, bool(web_calls), web_query)

    cached = _cache_get(key)
    if cached is not None:
        _aliases[_normalize_question(question)] = key
        return cached

    cmots_data = {tc["args"].get("company", ""): _resolve_fields(
        tc["args"].get("company", ""), tc["args"].get("fields", [])) for tc in cmots_calls}
    web_data = web.format_pages(web.search(web_query)) if web_query else None

    answer = _write(question, cmots_data, web_data)
    if answer:
        _cache_set(key, answer, bool(web_calls), question)
    return answer
