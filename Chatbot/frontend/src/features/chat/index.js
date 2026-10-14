/**
 * Public surface of the chat feature.
 *
 * One screen, and the source table beside it. Everything else — the composer,
 * the trace, the markdown renderer, the panels — is internal to the feature,
 * so it stays free to be reorganised without anything outside noticing.
 */
export { ChatScreen } from './ChatScreen';
export { sourceMeta, sourceSentence } from './sources';
