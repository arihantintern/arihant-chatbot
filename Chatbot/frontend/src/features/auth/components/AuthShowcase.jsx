import './AuthShowcase.css';

import { Logo } from '@/components/brand';
import { Icon } from '@/components/ui';

/** What the assistant can actually reach — the four lanes model/chain.py routes between. */
const CAPABILITIES = [
  {
    icon: 'fileText',
    title: 'Research, read for you',
    body: 'Answers grounded in Arihant’s own notes and reports, with the PDF they came from named.',
  },
  {
    icon: 'trendingUp',
    title: 'Live market data',
    body: 'Prices, funds, IPOs and results, pulled at the moment you ask rather than remembered.',
  },
  {
    icon: 'globe',
    title: 'The open web, when it helps',
    body: 'It searches only when the documents cannot answer, and it tells you when it did.',
  },
  {
    icon: 'shieldCheck',
    title: 'Your questions stay yours',
    body: 'Every conversation is filed against your account and searchable — by you.',
  },
];

/**
 * The brand half of the auth screen.
 *
 * Hidden below 1024px rather than stacked. On a phone it would push the form
 * — the only thing anyone came here to use — a full screen down, and a
 * marketing panel you have to scroll past to sign in is worse than no panel.
 */
export function AuthShowcase() {
  return (
    <section className="auth-showcase" aria-labelledby="auth-showcase-title">
      {/* Decoration, painted behind everything and inert to the pointer. */}
      <span className="auth-showcase__aurora" aria-hidden="true" />
      <span className="auth-showcase__grid" aria-hidden="true" />

      <div className="auth-showcase__inner">
        <Logo variant="lockup" height={34} className="auth-showcase__logo" />

        <div className="auth-showcase__lede">
          <p className="t-eyebrow auth-showcase__eyebrow">
            <span className="auth-showcase__eyebrow-dot" aria-hidden="true" />
            Research assistant
          </p>

          <h2 id="auth-showcase-title" className="t-display-sm auth-showcase__title">
            Ask the desk anything.{' '}
            <span className="u-text-gradient">See where the answer came from.</span>
          </h2>

          <p className="t-lead auth-showcase__body">
            A single place to ask about markets, funds and filings — answered from
            Arihant’s research, live data and the web, with every source shown.
          </p>
        </div>

        <ul className="auth-showcase__list" role="list">
          {CAPABILITIES.map(({ icon, title, body }, index) => (
            <li
              key={title}
              className="auth-showcase__item a-fade-in-up a-stagger"
              /* Each row arrives a beat after the one above it. The cap in
                 tokens/motion.css keeps the last one from feeling late. */
              style={{ '--stagger-index': index + 2 }}
            >
              <span className="auth-showcase__item-icon" aria-hidden="true">
                <Icon name={icon} size="md" />
              </span>
              <div>
                <p className="auth-showcase__item-title">{title}</p>
                <p className="auth-showcase__item-body">{body}</p>
              </div>
            </li>
          ))}
        </ul>

        {/*
          A still of the product, so the promise above has something to stand
          on. Entirely decorative — `aria-hidden` because a screen reader
          reading out a fabricated question and answer as though it were real
          content would be actively misleading.
        */}
        <figure className="auth-showcase__proof" aria-hidden="true">
          <div className="auth-showcase__bubble auth-showcase__bubble--ask">
            How did the IT pack do last quarter?
          </div>

          <div className="auth-showcase__bubble auth-showcase__bubble--answer">
            <p>
              Sector revenue growth cooled to low single digits, with margins holding
              through cost discipline…
            </p>
            <div className="auth-showcase__chips">
              <span className="auth-showcase__chip">
                <Icon name="trendingUp" size="xs" />
                Live data
              </span>
              <span className="auth-showcase__chip">
                <Icon name="fileText" size="xs" />
                3 reports
              </span>
            </div>
          </div>
        </figure>
      </div>
    </section>
  );
}
