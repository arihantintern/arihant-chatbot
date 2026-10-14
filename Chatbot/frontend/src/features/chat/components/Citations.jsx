import './Citations.css';

import { forwardRef, useState } from 'react';

import { Icon } from '@/components/ui';

/**
 * What an answer actually read: the documents, and the pages.
 *
 * TWO DELIBERATE ABSENCES.
 *
 * The pdfs are not links. `pdfs` is a list of filenames from
 * `d.metadata["source"]`, and there is no route on model/api.py that serves a
 * document — so an anchor here would be a dead one. They are shown as what
 * they are: the names of files somebody with access to the corpus can go and
 * open, with a copy button so the name can be pasted somewhere that can.
 *
 * They are not numbered. The `[1]` markers in an answer count retrieved
 * *chunks*, while this list is a deduplicated, alphabetically sorted set of
 * files — so "1" here would not be the same "1" as in the prose. Numbering
 * them would be a claim the data does not support.
 *
 * @param {object} props
 * @param {string[]} props.pdfs
 * @param {string[]} props.urls
 * @param {boolean} [props.flash]  briefly draw attention, after a `[3]` click
 */
export const Citations = forwardRef(function Citations({ pdfs, urls, flash }, ref) {
  const total = pdfs.length + urls.length;
  if (total === 0) return null;

  return (
    <div className="cites" ref={ref} data-flash={flash || undefined}>
      <p className="cites__label">
        <Icon name="fileText" size="xs" />
        {total === 1 ? 'One source' : `${total} sources`}
      </p>

      <ul className="cites__list">
        {pdfs.map((name) => (
          <li key={`pdf:${name}`}>
            <DocumentPill name={name} />
          </li>
        ))}

        {urls.map((url) => (
          <li key={`url:${url}`}>
            <a
              className="cites__pill cites__pill--link"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              title={url}
            >
              <Icon name="globe" size="xs" className="cites__icon" />
              <span className="cites__text">{hostOf(url)}</span>
              <Icon name="arrowRight" size="xs" className="cites__go" />
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
});

/**
 * One document. Pressing it copies the filename.
 *
 * The confirmation replaces the icon rather than the label, so the pill does
 * not change width and the row of them does not reflow under the pointer.
 */
function DocumentPill({ name }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(name);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* Denied permission, or an insecure origin. Nothing to recover: the
         filename is on screen and can be selected by hand. */
    }
  };

  return (
    <button
      type="button"
      className="cites__pill"
      onClick={copy}
      title={`${name} — click to copy the filename`}
    >
      <Icon
        name={copied ? 'check' : 'fileText'}
        size="xs"
        className={`cites__icon ${copied ? 'cites__icon--done' : ''}`.trim()}
      />
      <span className="cites__text">{tidyName(name)}</span>
    </button>
  );
}

/**
 * `Bandhan_Bank_Q1FY26_Result_Update.pdf` → `Bandhan Bank Q1FY26 Result Update`.
 *
 * The extension and the underscores are an artefact of how the corpus is
 * stored, not information. The full original is in the `title`, so nothing is
 * hidden — and it is the original that gets copied.
 */
function tidyName(name) {
  return name
    .replace(/^.*[\\/]/, '')
    .replace(/\.(pdf|txt|md|docx?)$/i, '')
    .replace(/[_+]+/g, ' ')
    .trim();
}

/** `https://www.moneycontrol.com/news/x` → `moneycontrol.com`. */
function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}
