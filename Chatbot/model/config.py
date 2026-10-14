"""every knob: paths, models, numbers, prompts, patterns and canned text.

The chain wires these, it does not author them. A prompt and a keyword list are the
most edited things in a rag pipeline and the worst to go hunting for.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent

# the key lives in MyBot/.env, one level up. This folder is a copy and the key is
# not something to copy with it, so it is read from there -- or from a .env in this
# folder, if this one ever moves out on its own.
load_dotenv(HERE.parent / ".env")
load_dotenv(HERE / ".env", override=True)

DOCS_DIR = HERE / "pdfs"              # drop pdfs here, subfolders included
INDEX_DIR = HERE / "index"            # delete to force a rebuild
CACHE_FILE = HERE / ".cache" / "elements.pkl"

# models. The writing and the errands are openai now -- llama3.2:3b read "20g" out
# of a table and called it a price, and no prompt fixes a 3B model's arithmetic.
CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")     # the writing
SMALL_MODEL = os.getenv("OPENAI_SMALL_MODEL", CHAT_MODEL)  # autocorrect, scope
CHAT_TEMPERATURE = 0.2

# embeddings stay on ollama: the index on disk was built with nomic and the vectors
# have to come from the same model that made them. Point this at an openai model
# and `python build.py` has to be run again before anything can be searched.
EMBED_MODEL = "nomic-embed-text"

# chat history. One shared database, but no longer one shared transcript: a
# conversation belongs to the account that opened it and is read back by its owner
# (see auth.py, history.py). The uri is a secret and it stays in .env. No uri ->
# history.py turns itself off and the bot answers exactly as it did before.
MONGO_URI = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI", "")
MONGO_DB = os.getenv("MONGODB_DB", "abot")
MONGO_TIMEOUT_MS = int(os.getenv("MONGODB_TIMEOUT_MS", "3000"))  # a dead cluster
#                       costs this once, not on every question -- see history.py


# ---------------------------------------------------------------------- auth
# who is asking. A turn belongs to an account now, not to whoever happened to be
# logged into the machine that asked it -- see auth.py for the accounts and api.py
# for the tokens.
#
# The signing key is the whole of the security here: anyone holding it can mint a
# token for any account, admin included. It stays in .env and never in git. When
# it is missing the process invents one at import, so every token dies with the
# process -- a restart logging you out is a nuisance, a default key shipped to
# production and shared by every install is a break-in.
JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
JWT_EPHEMERAL = not os.getenv("JWT_SECRET")   # api.py says so once, at startup
JWT_ALGORITHM = "HS256"
JWT_TTL_MIN = int(os.getenv("JWT_TTL_MIN", "720"))       # 12h, then log in again

# bcrypt's own cost parameter. 12 is ~250ms per verify on this hardware, which is
# the point -- it is what makes a stolen hash expensive to run a wordlist against.
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))
PASSWORD_MIN_LEN = 8
ROLES = ("user", "admin")     # user reads its own chats, admin reads everyone's


# --------------------------------------------------------------------- cmots
# Arihant's own market-data feed. IP-whitelisted, no key -- see cmots.py. Its own
# Mongo database, and its own connection: MONGO_URI above is this bot's chat
# history and stays empty until .env names a real cluster, but cmots data
# shouldn't wait on that, so it falls back to the local mongod that already holds
# it rather than inheriting an empty string.
CMOTS_BASE_URL = "https://cmotsnew.arihantcapital.com"
CMOTS_MONGO_URI = os.getenv("CMOTS_MONGO_URI") or MONGO_URI or "mongodb://localhost:27017"
CMOTS_DB = os.getenv("CMOTS_DB", "cmots")

CMOTS_TIMEOUT_S = 20
CMOTS_RETRIES = 3
CMOTS_RETRY_BACKOFF_S = 2       # doubles each retry: 2s, 4s, 8s

# per-company loop (keystats/ratios/key-financials/profile/shareholding) -- no
# documented rate limit, so this starts conservative.
CMOTS_WORKERS = 10

# cron schedules the scheduler reads, in APScheduler's (hour, minute) form. Bulk
# EOD jobs run after CMOTS's own 11:30PM refresh; the per-company loop follows
# the company-master sync it depends on.
CMOTS_BULK_EOD_CRON = {"hour": 23, "minute": 45}
CMOTS_PER_COMPANY_CRON = {"hour": 0, "minute": 30}
CMOTS_MF_PER_SCHEME_CRON = {"hour": 1, "minute": 0}   # offset from the equity loop above,
#                            so the two thread pools don't both run at once
CMOTS_NEWS_CRON_MINUTES = 20     # "as and when updated" -- polled, not pushed

# world_index names its index inline ("what is the nasdaq level") rather than
# needing the of/for/on extraction the company-based metrics use. Maps what a
# person actually says to a substring of what CMOTS actually calls it --
# confirmed live that "Dow Jones"/"Nasdaq" aren't the real stored names at all
# (they're "DJIA"/"US Tech 100"), so a plain substring match on the spoken name
# would silently return nothing.
CMOTS_WORLD_INDEX_ALIASES = {
    "sensex": "BSE Sensex", "nifty": "Nifty", "dow jones": "DJIA", "dow": "DJIA",
    "nasdaq": "US Tech 100", "ftse": "FTSE 100", "nikkei": "Nikkei 225",
    "hang seng": "Hang Seng", "s&p 500": "S&P 500", "s&p": "S&P 500", "dax": "DAX",
    "kospi": "KOSPI",
}

# the field vocabulary the AI-driven cmots tier (cmots_ai.py) can request. One
# place, reused for (a) the query_cmots tool's argument description, (b) the
# planner prompt's list of what it may ask for, (c) server-side validation of
# what the model actually sent. Same names as the old CMOTS_METRICS labels above
# -- no new taxonomy invented, just no longer limited to matching one at a time.
CMOTS_FIELDS = (
    ("price", "last closing price"),
    ("pe", "P/E ratio"),
    ("market_cap", "market capitalisation"),
    ("eps", "earnings per share"),
    ("book_value", "book value per share"),
    ("roe", "return on equity, TTM"),
    ("roce", "return on capital employed, TTM"),
    ("revenue", "total income / net sales, latest reported period"),
    ("net_profit", "net profit / PAT, latest reported period"),
    ("total_assets", "total assets, latest balance sheet"),
    ("dividend", "most recent dividend corporate action"),
    ("bonus", "most recent bonus issue"),
    ("split", "most recent stock split"),
    ("buyback", "most recent buyback"),
    ("merger", "most recent merger/demerger"),
    ("shareholding", "promoter/FII/mutual fund/public/pledged holding %"),
    ("fund_holders", "which mutual fund schemes hold this stock"),
    ("chairman", "chairman/CEO/managing director name"),
    ("board", "board of directors"),
    ("about", "company business description"),
    ("news", "recent company news headlines"),
    ("world_index", "a world market index level -- Sensex, Nifty, Dow, Nasdaq, "
                    "FTSE, Nikkei, Hang Seng, S&P 500, DAX, KOSPI. `company` "
                    "names the index, not a company."),
    ("fii_dii_flow", "FII/DII net cash-market activity. `company` is ignored."),
    ("ipo_status", "IPO status, open/close/allotment/listing dates"),
    ("ipo_price", "IPO issue price band / allotment price"),
    ("ipo_subscription", "IPO subscription multiple"),
    ("ipo_listing_gain", "IPO listing-day gain %"),
    ("ipo_risks", "IPO risk factors"),
    ("ipo_strengths", "IPO strengths"),
    ("mf_nav", "mutual fund scheme NAV"),
    ("mf_returns", "mutual fund scheme returns (1mo/1yr/3yr)"),
    ("mf_risk", "mutual fund scheme risk stats (Sharpe/Alpha/Beta/Sortino)"),
    ("mf_aum", "mutual fund scheme AUM"),
)
CMOTS_FIELD_NAMES = frozenset(name for name, _ in CMOTS_FIELDS)
CMOTS_FIELD_VOCAB = "\n".join(f"- {n}: {d}" for n, d in CMOTS_FIELDS)  # for the prompt

# a fresh cmots-ai answer costs a planner call plus a writer call. Cache both
# away: pure query_cmots answers are only ever as fresh as the next scheduler
# sync anyway (see cmots_scheduler.py / CMOTS_*_CRON above), so they live until
# then; anything that touched the web gets a short TTL instead, matching how
# often news itself is polled.
CMOTS_AI_WEB_CACHE_TTL_S = CMOTS_NEWS_CRON_MINUTES * 60   # 20 min

# the writer's way of saying "the data i was handed does not answer this" --
# same shape as NOT_IN_DOCS/NOT_ON_WEB above, read only by cmots_ai.py.
NOT_ON_CMOTS = "NO CMOTS ANSWER"

# cmots_ai.py treats "the planner called no tool" as "not this tier", full stop
# -- it never lets the planner answer from its own knowledge, however
# reasonable-sounding, because that would mean trusting a small model's word
# choice to gate scope instead of the dedicated, tested in_scope() classifier
# that already runs right after this tier in chain.py. A finance definition
# ("what does P/E mean") costs one extra hop through that pipeline instead of
# being answered here directly -- a fine trade for never risking this tier
# answering something wildly out of scope on its own say-so.
CMOTS_AI_PLANNER_TURNS = [
    ("system",
     "You are a router with two tools.\n"
     "query_cmots looks up ONE company, mutual fund scheme, IPO, or market index in "
     "Arihant's own live market-data feed. Name the company/scheme/index and every "
     "field the question needs, choosing only from this exact set:\n"
     f"{CMOTS_FIELD_VOCAB}\n\n"
     "web_search searches the open web -- use it only for something query_cmots "
     "cannot supply (recent commentary/opinion beyond its own news feed, general "
     "context for a broad 'review'). Never use it for a fact query_cmots can answer.\n"
     "For a question naming two companies (a comparison), call query_cmots twice, "
     "once per company, in the same turn.\n"
     "If neither tool is needed -- a definition, something about Arihant's own "
     "research report, or anything not about live company/market data -- call no "
     "tool at all. Someone else answers those; do not write anything yourself."),
    ("human", "{question}"),
]

CMOTS_AI_WRITER_PROMPT = """Answer the question using the data below. It comes from
Arihant's own live market-data feed (CMOTS) and, if present, a web search -- not from
a retrieved document, so do not ask for citation numbers.
Write naturally, in full sentences, and round numbers sensibly. If a value is
null/missing, do not mention it unless the question named that exact figure, in
which case say plainly it is not available.
Write currency as "Rs", never the rupee sign character -- it breaks on some terminals.
If NOTHING below answers the question at all, reply with exactly: {sentinel}

cmots data -> {cmots_data}

web extracts -> {web_data}

question -> {asked}"""

STRATEGY = "hi_res"                   # "fast" produces no usable tables
JUNK = {"Header", "Footer", "PageNumber"}
CHUNK_SIZE, CHUNK_OVERLAP = 1000, 200
EMBED_TOKEN_LIMIT = 2048              # nomic truncates past this, silently
TOKENIZER = "cl100k_base"

# how much of the conversation a follow-up is allowed to see. Four turns because the
# thing being referred to is nearly always the last one or two, and a long transcript
# in the prompt makes the small model resolve "it" to the wrong company. The answers
# are cut short: the referent is in the first line or two, the rest is filler.
HISTORY_TURNS = 4
HISTORY_ANSWER_CHARS = 300

TOP_K = 4
RESCUE_K = 2                          # literal-match chunks added on top of TOP_K
WEB_RESULTS, WEB_CHARS = 3, 2000

# the exact strings a branch emits when it has nothing. only the router reads them
NOT_IN_DOCS = "NOT IN THE DOCUMENTS"
NOT_ON_WEB = "NO ANSWER ON THE WEB"


# ------------------------------------------------------------------- prompts
DOC_PROMPT = """Answer the question using only the context below.
Write 2 to 4 full sentences, a bare phrase is not an answer.
The context is Arihant Capital's own research. If it carries Arihant's call,
rating or target price, lead with that and say it is Arihant's view.
Tables are given as rows of `a | b | c`, the first line naming the columns.
Read the value from the row whose first cell names the thing asked about.
A row of prices, targets, ratings or returns is a company's numbers on one day.
It is not a description of the company, its business or its history. If the
question asks what something IS and the context holds only its numbers, you do
not have the answer: reply with exactly {sentinel} rather than describing the
company as its own table row.
If the context does not answer the question, reply with exactly: {sentinel}
Otherwise end with the numbers of the pieces you used, like [1][3].

context -> {context}

question -> {asked}"""

WEB_PROMPT = """Answer the question using only the web extracts below.
Write 2 to 4 full sentences and end with the numbers you used, like [1][2].
If the extracts do not answer the question, reply with exactly: {sentinel}

extracts -> {context}

question -> {asked}"""

GENERAL_PROMPT = """Reply to the user in two or three short lines from your own knowledge.
You sit next to a small set of PDFs and this question is not covered by them.
Do not pretend to quote any document. Do not mention the user's spelling.

user -> {asked}"""

BRIEF_PROMPT = """Answer in ONE short sentence, plainly. If you do not know, say so in one
sentence. No preamble, no list, nothing after the sentence.

question -> {asked}"""

# real human/ai turns, not one instruction. a chat model believes turns; as one
# block a small model just echoes the examples back
FIX_TURNS = [
    ("system", "You fix spelling and punctuation. The user sends one line. Reply with "
               "that line corrected and nothing else. Never answer it, never explain."),
    ("human", "wat is the sensx close"), ("ai", "What is the Sensex close?"),
    ("human", "{question}"),
]

# "and its rating?" is not a question anything can search for. This rewrites it into
# one, from the turns before it, and everything downstream searches the rewrite.
#
# Turns again, not one block, and for the same reason FIX_TURNS is: shown the shape
# twice -- once resolving a pronoun, once leaving an already-complete question alone
# -- the model copies the shape. Told it in prose, it answers the question instead.
# The second example is the one that earns its place: without a "changed nothing"
# case the model rewrites everything it is given, and a question that already stood
# alone comes back stuffed with the last company anyone mentioned.
FOLLOWUP_TURNS = [
    ("system", "You rewrite a follow-up into a question that stands on its own.\n"
               "You are given the conversation so far and the user's new line. If the "
               "new line leans on the conversation -- 'it', 'its', 'that', 'the "
               "company', a bare 'and the rating?' -- put the words it is leaning on "
               "back in and output the whole question.\n"
               "If the new line already stands on its own, output it EXACTLY as it is.\n"
               "Never answer it. Never explain. Output one question and nothing else."),
    ("human", "conversation:\nyou> what is bandhan bank's target price\n"
              "bot> Arihant's target price for Bandhan Bank is Rs 240.\n\n"
              "new line: and its rating?"),
    ("ai", "What is Arihant's rating on Bandhan Bank?"),
    ("human", "conversation:\nyou> what is bandhan bank's target price\n"
              "bot> Arihant's target price for Bandhan Bank is Rs 240.\n\n"
              "new line: what was the sensex close on 10 may 2022"),
    ("ai", "What was the Sensex close on 10 May 2022?"),
    ("human", "conversation:\n{history}\n\nnew line: {question}"),
]

# what makes a line look like it is leaning on the one before it. This gate is only
# here to keep a model call off questions that plainly stand alone -- a false hit
# costs one small call and comes back unchanged, a false miss costs the follow-up.
# So it is written loose on purpose.
FOLLOWUP_Q = (r"^\s*(?:and|but|so|then|also|what|how)\s+about\b"
              r"|^\s*(?:and|but|so|then|also|why|more|again|explain|elaborate)\b"
              r"|\b(?:it|its|it'?s|that|this|those|these|they|them|their|there|"
              r"he|him|his|she|her|hers|theirs)\b"
              r"|\bthe\s+(?:company|stock|share|firm|bank|report|note|same|above)\b")

# No keyword list. A hardcoded vocabulary is unbounded -- every question finds a
# word nobody thought of -- so the judgement is the small model's, and the prompt is
# what makes it reliable. Measured on 12 finance + 8 other questions: the vague
# version of this prompt got 6 wrong, this one gets 2. What fixed it was naming the
# OTHER categories out loud and forbidding an answer, not more examples.
SCOPE_TURNS = [
    ("system", "You are a router. You do NOT answer questions. You output one word.\n"
               "Output FINANCE if the question is about money, markets, companies, "
               "business, the economy, an investing idea or concept, or a company "
               "person (CEO, chairman, founder).\n"
               "Output OTHER for anything else: sport, food, travel, geography, "
               "language, science, software, art, or a request to write something.\n"
               "Never answer the question. Never explain. Output exactly one word."),
    ("human", "what was the nifty close"), ("ai", "FINANCE"),
    ("human", "who won the 2018 world cup"), ("ai", "OTHER"),
    ("human", "what is the capital of australia"), ("ai", "OTHER"),
    ("human", "who is the ceo of infosys"), ("ai", "FINANCE"),
    ("human", "what is volatility"), ("ai", "FINANCE"),
    ("human", "write me a haiku"), ("ai", "OTHER"),
    ("human", "summarise the management meet note"), ("ai", "FINANCE"),
    ("human", "{question}"),
]


# ------------------------------------------------------------------ patterns
# small talk. fullmatch means the whole line must be the pleasantry, so "hi, what is
# the sensex" does not match and goes to the documents where it belongs.
TALK = [
    (r"who\s+are\s+(?:you|u)|what\s+are\s+you|what(?:'?s| is)\s+(?:this|your\s+name)"
     r"|what\s+(?:can|do)\s+you\s+do|what\s+(?:can|do|are)\s+(?:you|u)\s+help(?:ing)?"
     r"\s*(?:me\s+)?with|what\s+(?:documents|pdfs|files)\s+(?:do\s+)?(?:you\s+)?have"
     r"|help|how\s+do\s+i\s+use\s+(?:you|this)|introduce\s+yourself", "id"),
    (r"hi|hey+|hell?o+|yo|hiya|howdy|greetings|good\s*(?:morning|afternoon|evening|day)"
     r"|how\s+(?:are|r)\s+(?:you|u)|how(?:'?s| is)\s+it\s+going|what(?:'?s| is)\s+up"
     r"|sup|wass?up", "hi"),
    (r"thank\s*(?:you|u)|thanks|thx|ty|appreciate\s+it|cheers", "ta"),
    (r"bye|goodbye|good\s*night|see\s+(?:you|ya)|cya|that'?s\s+all", "bye"),
    (r"ok(?:ay)?|cool|nice|great|perfect|got\s+it|i\s+see|sure|alright", "ack"),
]

REPLIES = {
    "hi": "hi. {corpus}.\nask me anything from them -- i'll answer with the pieces i "
          "used, and say so if i had to look elsewhere.",
    "id": "i'm a finance assistant over arihant's research pdfs. {corpus}.\ni search "
          "them first, fall back to the web, and label every answer with where it "
          "came from.",
    "ta": "anytime. ask me another.",
    "bye": "bye.",
    "ack": "ok -- ask away whenever you're ready.",
}

RATINGS = ("BUY", "ACCUMULATE", "HOLD", "NEUTRAL", "REDUCE", "SELL")
RATING_Q = (rf"rating\s+scale|stock\s+rating|\bratings?\b[^?]*\b(?:mean|means|scale|"
            rf"system|bands?)\b|\b(?:{'|'.join(RATINGS)})\b[^?]*\b(?:mean|means|"
            rf"defined?|requires?|threshold|bands?|range)\b")
# narrow -- "what is arihant capital" is a description question and belongs to the
# documents and the web, not to three lines of footer boilerplate
FIRM_Q = (r"\b(?:registration|research\s+analyst)\s+(?:no|number)\b"
          r"|\barihant\b[^?]*\b(?:registration|sebi\s+reg|website|email)\b")

# "what is bandhan bank" and "what is bandhan bank's target price" open with the
# same three words and want completely different things -- one wants the company
# described, the other wants a cell out of a table. The metric words are what tell
# them apart, so a question carrying any of them is not a description question.
DESCRIBE_Q = (r"^\s*(?:what|who)(?:'?s|\s+is|\s+are)\s+"
              r"|^\s*(?:tell\s+me\s+about|describe|explain|introduce)\b")
METRIC_Q = (r"\bprices?\b|\btargets?\b|\bratings?\b|\breco\b|\brecommend|\bcalls?\b"
            r"|\bupside\b|\bdownside\b|\breturns?\b|\bclos(?:e|ed|ing)\b|\bopen(?:ed|ing)?\b"
            r"|\bhigh\b|\blow\b|\bvolume\b|\bmarket\s*cap\b|\bp/?e\b|\byield\b"
            r"|\bchange\b|\bpercent\b|%|\bvalues?\b|\blevels?\b|\bquote\b|\bworth\b")

# A refusal the model phrases as an observation ("I don't see Axis Bank's
# information") still passed as `source: documents`, the one label that must never
# be wrong -- hence the second half of this list.
HEDGES = ("i don't know", "i do not know", "the context does not", "no information",
          "not mentioned", "cannot answer", "can't answer", "i don't see",
          "i do not see", "i couldn't find", "i could not find", "i can't find",
          "there is no mention", "does not appear in", "unable to verify",
          "i'm unable to", "i am unable to",
          # a better model hedges more politely, which is harder to catch, not
          # easier: "Arihant Capital Markets Ltd. is identified in the documents,
          # but no further description of what it is is provided" was passing as a
          # cited document answer while saying outright that it had not answered.
          "no further description", "no description", "does not describe",
          "is not described", "no further detail", "no details", "only mentioned",
          "is merely mentioned", "is only referenced", "beyond the name")


# ---------------------------------------------------------------- canned text
DISCLAIMER = ("\n\n(not from the documents i was given, and i could not look it up -- "
              "treat this as general knowledge and check it)")
HEAD = ("that's outside what i do -- i'm a finance assistant sitting on arihant's "
        "market research pdfs. briefly, though:")
TAIL = ("ask me about a market, a company, a rating call or one of the reports and "
        "i'll answer it properly, with sources.")
