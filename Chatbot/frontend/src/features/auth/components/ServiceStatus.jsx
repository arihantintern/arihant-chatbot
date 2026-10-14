import './ServiceStatus.css';

import { Icon } from '@/components/ui';

import { SERVICE_STATE, useServiceHealth } from '../hooks/useServiceHealth';

const PRESENTATION = {
  [SERVICE_STATE.CHECKING]: {
    label: 'Checking the service…',
    detail: null,
  },
  [SERVICE_STATE.READY]: {
    label: 'Assistant online',
    detail: null,
  },
  [SERVICE_STATE.DEGRADED]: {
    label: 'Accounts unavailable',
    detail: 'The assistant is up, but it cannot reach the account store — sign-in will fail.',
  },
  [SERVICE_STATE.OFFLINE]: {
    label: 'Assistant offline',
    detail: 'Nothing is answering at the API address. Start the backend, then retry.',
  },
};

/**
 * A quiet line saying whether signing in can work at all.
 *
 * Not decoration: a 503 from a login form is indistinguishable from a bug
 * unless something tells you the account store is unreachable, and "start the
 * backend" is a fix the person can actually apply. When everything is fine
 * this is one small green dot and four words, which is all it should be.
 */
export function ServiceStatus({ className = '' }) {
  const { status, recheck } = useServiceHealth();
  const { label, detail } = PRESENTATION[status];
  const broken = status === SERVICE_STATE.OFFLINE || status === SERVICE_STATE.DEGRADED;

  return (
    <div
      className={`service-status ${className}`.trim()}
      data-status={status}
      /* Polite, and only ever one short sentence: the status changing from
         offline to online while someone waits is worth hearing. */
      aria-live="polite"
    >
      <span className="service-status__row">
        <span className="service-status__dot" aria-hidden="true" />
        <span className="service-status__label">{label}</span>

        {broken ? (
          <button type="button" className="service-status__retry" onClick={recheck}>
            <Icon name="clock" size="xs" />
            Retry
          </button>
        ) : null}
      </span>

      {detail ? <span className="service-status__detail">{detail}</span> : null}
    </div>
  );
}
