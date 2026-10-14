import './Markdown.css';

import { useMemo } from 'react';

import { parseBlocks, tokenizeInline } from '@/lib/markdown';

/**
 * An answer, rendered.
 *
 * The tree from `@/lib/markdown` becomes React elements here — and *only*
 * React elements. There is no html string in this path and therefore no
 * `dangerouslySetInnerHTML`: text a language model wrote can contain anything,
 * including a `<script>` tag it read off a web page, and the way to be safe
 * from that is to never be in the business of parsing html at all. Everything
 * below is either a known tag or a text node, so a stray angle bracket in an
 * answer renders as an angle bracket.
 *
 * WHAT A `[3]` CAN AND CANNOT DO. model/config.py tells the model to "end
 * with the numbers of the pieces you used" — the pieces being the retrieved
 * *chunks*, numbered in retrieval order. What comes back over the wire is
 * `pdfs`: a sorted, deduplicated set of filenames (see api.py). Several chunks
 * can share one file and the set is reordered, so marker 3 cannot be resolved
 * to one document without inventing a mapping that does not exist.
 *
 * So a citation is a button that takes you to the answer's sources — all of
 * them — and never claims to point at one. Where there are no sources at all,
 * it renders as a plain mark, because a control that does nothing is worse
 * than a label.
 *
 * @param {object} props
 * @param {string} props.text
 * @param {() => void} [props.onCitationClick]
 *   Reveal the answer's sources. Omit it when the answer has none.
 */
export function Markdown({ text, onCitationClick }) {
  /* Parsing is pure and the text never changes once an answer has arrived, so
     a long conversation re-parses nothing on re-render. */
  const blocks = useMemo(() => parseBlocks(text), [text]);

  if (blocks.length === 0) return null;

  return (
    <div className="md">
      <Blocks blocks={blocks} onCitationClick={onCitationClick} />
    </div>
  );
}

function Blocks({ blocks, onCitationClick }) {
  return blocks.map((block, index) => (
    <Block
      /* Blocks are produced by a pure parse of an immutable string: index is
         their identity, and nothing reorders. */
      key={index}
      block={block}
      onCitationClick={onCitationClick}
    />
  ));
}

function Block({ block, onCitationClick }) {
  const inline = (value) => (
    <Inline text={value} onCitationClick={onCitationClick} />
  );

  switch (block.type) {
    case 'paragraph':
      return <p className="md__p">{inline(block.text)}</p>;

    case 'heading': {
      /* Demoted by two: the page already has an h1 and the conversation's own
         heading structure sits above this. An answer's "## Outlook" is a
         sub-sub-heading of the document, whatever the model wrote. */
      const Tag = `h${Math.min(block.level + 2, 6)}`;
      return <Tag className="md__h">{inline(block.text)}</Tag>;
    }

    case 'list': {
      const Tag = block.ordered ? 'ol' : 'ul';
      return (
        <Tag className="md__list" start={block.ordered && block.start !== 1 ? block.start : undefined}>
          {block.items.map((item, index) => (
            <li className="md__item" key={index}>
              <Blocks
                blocks={item}
                onCitationClick={onCitationClick}
              />
            </li>
          ))}
        </Tag>
      );
    }

    case 'table':
      return (
        <Table block={block} onCitationClick={onCitationClick} />
      );

    case 'code':
      return (
        <pre className="md__pre" data-lang={block.lang || undefined}>
          <code className="md__code">{block.value}</code>
        </pre>
      );

    case 'quote':
      return (
        <blockquote className="md__quote">
          <Blocks blocks={block.blocks} onCitationClick={onCitationClick} />
        </blockquote>
      );

    case 'rule':
      return <hr className="md__rule" />;

    default:
      return null;
  }
}

/**
 * A table, scrolling inside itself.
 *
 * Two details that matter for financial data specifically. The wrapper takes
 * the horizontal scroll (`.u-scroll-x`), so a ten-column comparison scrolls in
 * place instead of widening the page and pushing the composer off screen. And
 * a column whose cells are all numeric is right-aligned with tabular figures
 * even when the markdown gave no alignment — a column of prices whose decimal
 * points do not line up is measurably harder to read, and models rarely bother
 * with `---:`.
 */
function Table({ block, onCitationClick }) {
  const alignments = useMemo(
    () =>
      block.align.map((given, column) =>
        given ?? (isNumericColumn(block.rows, column) ? 'end' : null),
      ),
    [block.align, block.rows],
  );

  return (
    <div className="md__table-scroll u-scroll-x" tabIndex={0} role="group">
      <table className="md__table">
        <thead>
          <tr>
            {block.head.map((cell, column) => (
              <th key={column} data-align={alignments[column] || undefined} scope="col">
                <Inline
                  text={cell}
                  onCitationClick={onCitationClick}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, column) => (
                <td key={column} data-align={alignments[column] || undefined}>
                  <Inline
                    text={cell}
                    onCitationClick={onCitationClick}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Is every filled cell in this column a number? Rs, %, commas and a sign are
    part of a number here — "Rs 1,850", "-4.2%" and "18.2" all count. */
function isNumericColumn(rows, column) {
  const cells = rows.map((row) => row[column]?.trim()).filter(Boolean);
  if (cells.length === 0) return false;

  return cells.every((cell) => /^[(]?[-+₹$]?\s?(?:Rs\.?\s?)?[\d,]+(?:\.\d+)?\s?%?[)]?$/i.test(cell));
}

/* -------------------------------------------------------------- inline pass */

function Inline({ text, onCitationClick }) {
  const tokens = useMemo(() => tokenizeInline(text), [text]);
  return <Tokens tokens={tokens} onCitationClick={onCitationClick} />;
}

function Tokens({ tokens, onCitationClick }) {
  return tokens.map((token, index) => {
    const key = index;

    switch (token.type) {
      case 'text':
        return token.value;

      case 'break':
        return <br key={key} />;

      case 'code':
        return (
          <code className="md__inline-code" key={key}>
            {token.value}
          </code>
        );

      case 'strong':
        return (
          <strong className="md__strong" key={key}>
            <Tokens tokens={token.children} onCitationClick={onCitationClick} />
          </strong>
        );

      case 'em':
        return (
          <em key={key}>
            <Tokens tokens={token.children} onCitationClick={onCitationClick} />
          </em>
        );

      case 'link':
        return (
          <a
            className="md__link"
            key={key}
            href={token.href}
            target="_blank"
            /* noreferrer as well as noopener: the destination came out of a
               model, and it has no business learning which conversation
               produced the click. */
            rel="noopener noreferrer"
          >
            <Tokens tokens={token.children} onCitationClick={onCitationClick} />
          </a>
        );

      case 'citation': {
        /* Clickable only when the answer actually carries sources. */
        if (!onCitationClick) {
          return (
            <sup className="md__cite md__cite--inert" key={key}>
              {token.number}
            </sup>
          );
        }

        return (
          <button
            type="button"
            className="md__cite"
            key={key}
            onClick={onCitationClick}
            aria-label={`Reference ${token.number} — show this answer's sources`}
          >
            <sup>{token.number}</sup>
          </button>
        );
      }

      default:
        return null;
    }
  });
}
