import './EmptyState.css';

import { Logo } from '@/components/brand';
import { Icon } from '@/components/ui';
import { useAuth } from '@/context/auth';

/**
 * The first thing an empty conversation shows.
 *
 * The four starters are not decoration and they are not random. Each one is a
 * *different kind* of question, chosen so that whichever a person clicks
 * first, the answer demonstrates a different part of what is behind this: the
 * research corpus, the published rating scale, the live market-data feed, and
 * something recent enough that only the web can have it.
 *
 * They deliberately do not claim which source will answer. model/chain.py
 * decides that at request time — the documents win when they are grounded,
 * whatever the web found — and a label promising "this one uses CMOTS" would
 * be wrong often enough to be worse than nothing. What the answer actually
 * used is shown above the answer, where it is a fact rather than a guess.
 *
 * @param {object} props
 * @param {(question: string) => void} props.onPick
 */
export function EmptyState({ onPick }) {
  const { user } = useAuth();

  return (
    <div className="empty">
      <div className="empty__glow" aria-hidden="true" />

      <header className="empty__head">
        <Logo variant="mark" height={40} className="empty__mark" title={null} />

        <h1 className="empty__title">
          {firstName(user.name)}, what would you like to know?
        </h1>
        <p className="empty__lead">
          Ask about a company, a rating, a number or the market. Every answer
          says where it came from — and says so when it came from nowhere in
          particular.
        </p>
      </header>

      <ul className="empty__starters">
        {STARTERS.map((starter, index) => (
          <li key={starter.question} style={{ '--stagger-index': index }}>
            <button type="button" className="empty__starter" onClick={() => onPick(starter.question)}>
              <span className="empty__starter-icon">
                <Icon name={starter.icon} size="sm" />
              </span>

              <span className="empty__starter-text">
                <span className="empty__starter-kind">{starter.kind}</span>
                <span className="empty__starter-question">{starter.question}</span>
              </span>

              <Icon name="arrowRight" size="sm" className="empty__starter-go" />
            </button>
          </li>
        ))}
      </ul>

      <p className="empty__foot">
        <Icon name="info" size="xs" />
        Answers are generated. Check anything you are going to act on.
      </p>
    </div>
  );
}

/**
 * ASCII apostrophes in the `question` strings, deliberately.
 *
 * These strings are not display copy — they are sent verbatim as the question.
 * A typographic ’ would make a starter byte-different from the same question
 * typed by hand or asked from `model/cli.py`, and the backend's answer cache
 * (`cmots_ai._normalize_question`) lowercases and trims but does not fold
 * quote characters. So the curly version is a guaranteed cache miss against
 * every other way of asking the same thing, for no gain at all.
 */
const STARTERS = [
  {
    kind: 'A company',
    question: "What is Arihant's view on Bandhan Bank?",
    icon: 'fileText',
  },
  {
    kind: 'The rating scale',
    question: 'What does an ACCUMULATE rating mean?',
    icon: 'shieldCheck',
  },
  {
    kind: 'A live number',
    question: 'What is Infosys trading at right now?',
    icon: 'database',
  },
  {
    kind: 'The market',
    question: 'What is happening in the IPO market this week?',
    icon: 'trendingUp',
  },
];

function firstName(name) {
  return String(name || '').trim().split(/\s+/)[0] || 'Hello';
}
