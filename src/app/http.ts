/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { AIGC_PROXY_HOST } from '../config';

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'HttpError';
  }
}

export const UNAUTHORIZED_EVENT = 'auth:unauthorized';

export function mergeHeaders(defaults?: HeadersInit, input?: HeadersInit) {
  const headers = new Headers(defaults);
  new Headers(input).forEach((value, key) => headers.set(key, value));
  return headers;
}

export async function apiFetch(path: string, init: RequestInit = {}, emit401 = true) {
  const response = await fetch(`${AIGC_PROXY_HOST}${path}`, {
    ...init,
    credentials: 'include',
    headers: mergeHeaders({ 'content-type': 'application/json' }, init.headers),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 && emit401) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new HttpError(response.status, payload.detail || '请求失败');
  }

  return response;
}
