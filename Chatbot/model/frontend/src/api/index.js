/**
 * Public surface of the api module.
 *
 * Import from '@/api'. The one exception is `configureAuthBridge`, which the
 * auth provider needs and nothing else should touch — it is exported here so
 * that "who wired the token in?" has exactly one answer.
 */

export { ApiError } from './ApiError';
export { configureAuthBridge } from './client';
export { API_BASE_URL } from './config';

export * as authApi from './auth.api';
export * as chatApi from './chat.api';
