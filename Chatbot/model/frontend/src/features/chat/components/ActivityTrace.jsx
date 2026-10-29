import './ActivityTrace.css';

import { Icon } from '@/components/ui';

import { useActivityTrace } from '../hooks/useActivityTrace';

/**
 * What the assistant is doing, while it does it.
 *
 * The caption at the bottom is not an apology, it is the point: this app is
 * honest about which of the two things on screen is measured. The steps are
 * real — they are model/chain.py's own pipeline, in its own order — and the
 * position within them is a good guess, because a single blocking POST gives
 * the browser nothing to measure. Saying so costs one line and is the
 * difference between a progress indicator and a progress *claim*.
 *
 * @param {object} props
 * @param {() => void} props.onStop
 */
export function ActivityTrace({ onStop }) {
  const { stages, elapsed, note } = useActivityTrace();

  return (
    <section className="trace" aria-label="Working on your question">
      <header className="trace__head">
        <span className="trace__dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>

        {/* The only live region here. Announcing every stage change would
            interrupt a screen-reader user five times per question; the elapsed
            time, read politely, is what they actually need. */}
        <p className="trace__title" role="status" aria-live="polite">
          Working on it
          <span className="trace__elapsed">{seconds(elapsed)}</span>
        </p>

        <button type="button" className="trace__stop" onClick={onStop}>
          <Icon name="stop" size="sm" />
          Stop
        </button>
      </header>

      <ol className="trace__stages">
        {stages.map((stage) => (
          <li className="trace__stage" key={stage.label} data-state={stage.state}>
            <span className="trace__marker" aria-hidden="true">
              {stage.state === 'done' ? (
                <Icon name="check" size="xs" />
              ) : (
                <Icon name={stage.icon} size="xs" />
              )}
            </span>

            <span className="trace__text">
              <span className="trace__label">{stage.label}</span>
              {/* Only the running stage explains itself. All five detail lines
                  at once is a paragraph, not a status. */}
              {stage.state === 'active' ? (
                <span className="trace__detail">{stage.detail}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>

      {note ? (
        <p className="trace__note">
          <Icon name="info" size="xs" />
          {note}
        </p>
      ) : null}
    </section>
  );
}

/** "0:07". Minutes appear only once there are any. */
function seconds(elapsed) {
  const total = Math.floor(elapsed / 1000);
  if (total < 60) return `${total}s`;

  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`;
}
