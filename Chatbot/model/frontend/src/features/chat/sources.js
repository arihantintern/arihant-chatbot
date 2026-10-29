/**
 * sources.js — what `source` means, in one table.
 *
 * `POST /chat` returns a `source` string naming which lane of model/chain.py
 * answered. It is the single most useful field in the response and the only
 * *verified* thing the UI can say about where an answer came from: the activity
 * trace beside it is a client-side estimate of what the backend is doing,
 * because a blocking POST has nothing to stream. This is the fact; that is the
 * illustration.
 *
 * The values are exactly the strings `model/chain.py` emits — `take(…)` and
 * `settled(…)` are where they are written — and nothing else should be
 * inventing them:
 *
 *   documents     the pdfs answered, cited            (TIER 2)
 *   web           duckduckgo answered, cited          (TIER 3)
 *   arihant       the rating scale, parsed not read   (TIER 1)
 *   cmots-ai      live market data via the planner    (TIER 1b)
 *   general       the model's own knowledge           (TIER 4)
 *   small talk    a greeting, from a table
 *   out of scope  one line, then back to the subject
 *
 * `general` is the one that gets a warning tone, and that is the whole reason
 * this file exists rather than a `switch` in a component. TIER 4 is the
 * ungrounded fallback — no document, no page, no feed behind it. Rendering it
 * identically to a cited answer would make a research tool quietly untrustworthy,
 * which is a worse failure than any layout bug in this app.
 */

/**
 * @typedef  {object} SourceMeta
 * @property {string} label     short, for a chip
 * @property {string} sentence  what it means, for the answer's footer
 * @property {import('@/components/ui/icons').IconName} icon
 * @property {'brand'|'info'|'accent'|'warning'|'neutral'} tone
 * @property {boolean} grounded whether a real document, page or feed backs it
 * @property {boolean} quiet    true when the answer needs no provenance at all
 */

/** @type {Record<string, SourceMeta>} */
const SOURCES = {
  documents: {
    label: 'Arihant research',
    sentence: 'Answered from Arihant’s own research documents',
    icon: 'fileText',
    tone: 'brand',
    grounded: true,
    quiet: false,
  },
  web: {
    label: 'Web',
    sentence: 'Answered from pages found on the web',
    icon: 'globe',
    tone: 'info',
    grounded: true,
    quiet: false,
  },
  arihant: {
    label: 'Arihant rating scale',
    sentence: 'Read from Arihant’s published rating scale',
    icon: 'shieldCheck',
    tone: 'brand',
    grounded: true,
    quiet: false,
  },
  'cmots-ai': {
    label: 'CMOTS live data',
    sentence: 'Answered from Arihant’s live market-data feed',
    icon: 'database',
    tone: 'accent',
    grounded: true,
    quiet: false,
  },
  general: {
    label: 'General knowledge',
    sentence: 'Not from Arihant research — the model’s own knowledge, so check it',
    icon: 'alertTriangle',
    tone: 'warning',
    grounded: false,
    quiet: false,
  },
  'small talk': {
    label: 'Small talk',
    sentence: '',
    icon: 'sparkles',
    tone: 'neutral',
    grounded: false,
    /* A greeting has no provenance to report, and a chip under "Hello" saying
       so is noise pretending to be rigour. */
    quiet: true,
  },
  'out of scope': {
    label: 'Off topic',
    sentence: 'Outside what this assistant covers',
    icon: 'info',
    tone: 'neutral',
    grounded: false,
    quiet: false,
  },
};

/** When the backend sends a source this build has not been told about. */
const UNKNOWN = {
  label: 'Unattributed',
  sentence: 'The assistant did not say where this came from',
  icon: 'info',
  tone: 'neutral',
  grounded: false,
  quiet: false,
};

/**
 * @param {string|null|undefined} source
 * @returns {SourceMeta}
 */
export function sourceMeta(source) {
  if (!source) return UNKNOWN;
  return SOURCES[source] ?? { ...UNKNOWN, label: source };
}

/**
 * The footer sentence, with the counts that make it concrete.
 *
 * "Answered from Arihant's own research documents · 3 documents" is a claim
 * with something behind it; the same sentence with no count is a slogan. The
 * counts are only added when the citations are actually in hand — a reopened
 * conversation has none (the transcript route does not carry them), and it
 * should say less rather than imply more.
 */
export function sourceSentence(source, { pdfs = [], urls = [] } = {}) {
  const meta = sourceMeta(source);
  if (!meta.sentence) return '';

  const counts = [];
  if (pdfs.length) counts.push(`${pdfs.length} document${pdfs.length === 1 ? '' : 's'}`);
  if (urls.length) counts.push(`${urls.length} page${urls.length === 1 ? '' : 's'}`);

  return counts.length ? `${meta.sentence} · ${counts.join(', ')}` : meta.sentence;
}
