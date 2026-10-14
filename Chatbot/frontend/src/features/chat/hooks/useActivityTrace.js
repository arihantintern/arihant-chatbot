import { useEffect, useState } from 'react';

/**
 * The stages of a question, while one is out.
 *
 * WHY THIS IS CLIENT-SIDE, AND WHAT THAT COSTS.
 *
 * `POST /chat` is one blocking request. model/api.py has no streaming
 * endpoint, no SSE, no progress channel — the chain runs in fastapi's
 * threadpool and the first byte the browser sees is the finished answer. So
 * there is genuinely nothing to report, and the choice is between a spinner
 * that says nothing for up to a minute, or a trace that says what the
 * assistant is doing without claiming to know how far along it is.
 *
 * The stages below are real: they are the pipeline model/chain.py draws in its
 * own module docstring, in the order it runs them, including the fact that the
 * document lane and the web lane start together rather than one after the
 * other. The *timings* are estimates, and the UI says so — see the caption in
 * ActivityTrace. What is not an estimate is the single line that replaces all
 * of this when the answer lands: `source` names the lane that actually
 * answered, and that is the only provenance claim this app makes.
 *
 * Driven by elapsed time rather than by chained setTimeouts, which matters for
 * one specific reason: a backgrounded tab throttles timers, and a chain of
 * them would come back in the wrong place. Comparing a clock to a table of
 * thresholds is right whenever it is read.
 */

/** Cumulative, in ms: the point at which each stage starts. */
const STAGES = [
  {
    at: 0,
    label: 'Reading your question',
    icon: 'sparkles',
    detail: 'A small model spellchecks it; greetings are answered from a table.',
  },
  {
    at: 700,
    label: 'Working out what it’s asking',
    icon: 'refresh',
    detail: '“And its rating?” becomes a question that stands on its own.',
  },
  {
    at: 2200,
    label: 'Checking the subject',
    icon: 'shieldCheck',
    detail: 'Arihant’s rating scale and the live market-data feed get first refusal.',
  },
  {
    at: 4200,
    label: 'Searching the research and the web',
    icon: 'fileText',
    detail: 'Both at once — the documents and DuckDuckGo, in parallel.',
  },
  {
    at: 9200,
    label: 'Writing the answer',
    icon: 'message',
    detail: 'Crafting',
  },
];

/** Past this, saying nothing more would read as a hang. */
const SLOW_AFTER_MS = 22_000;

/**
 * Past this it is almost certainly the cold start: model/api.py warms `import
 * chain` on a background thread, and a question that arrives during those ~80
 * seconds waits for the same import to finish.
 */
const COLD_AFTER_MS = 45_000;

const TICK_MS = 500;

/**
 * @returns {{
 *   stages: Array<{label: string, icon: string, detail: string, state: 'done'|'active'|'waiting'}>,
 *   elapsed: number,
 *   note: string|null,
 * }}
 */
export function useActivityTrace() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Date.now() - started), TICK_MS);

    return () => clearInterval(timer);
  }, []);

  /* The last stage whose start time has passed. It never goes backwards and
     never runs off the end — the final stage holds, because the honest thing
     to say after ten seconds is "still writing", not a sixth invented step. */
  const active = STAGES.reduce(
    (found, stage, index) => (elapsed >= stage.at ? index : found),
    0,
  );

  return {
    stages: STAGES.map((stage, index) => ({
      label: stage.label,
      icon: stage.icon,
      detail: stage.detail,
      state: index < active ? 'done' : index === active ? 'active' : 'waiting',
    })),
    elapsed,
    note: noteFor(elapsed),
  };
}

function noteFor(elapsed) {
  if (elapsed >= COLD_AFTER_MS) {
    return 'This is the first question since the backend started, so it is also loading the search index — around a minute, once.';
  }
  if (elapsed >= SLOW_AFTER_MS) {
    return 'Still going. A question that needs the web or the live feed takes longer than one the documents can answer.';
  }
  return null;
}
