/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { Message } from '@arco-design/web-react';
import { apiFetch, mergeHeaders } from './http';
import type { RequestResponse, ApiConfig, ApiNames, Apis } from './type';

type HeaderRecord = Record<string, string>;

export type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends Array<infer U>
    ? Array<DeepPartial<U>>
    : T[P] extends object
    ? DeepPartial<T[P]>
    : T[P];
};

/**
 * @brief Get
 * @param apiName
 * @param headers
 */
export const requestGetMethod = ({
  action,
  headers = {},
}: {
  action: string;
  headers?: Record<string, string>;
}) => {
  return async (params: Record<string, any> = {}, init: RequestInit = {}) => {
    const path = `?Action=${action}&${Object.keys(params)
      .map((key) => `${key}=${params[key]}`)
      .join('&')}`;
    const res = await apiFetch(path, {
      ...init,
      headers: mergeHeaders(headers, init.headers),
    });
    return res;
  };
};

/**
 * @brief Post
 */
export const requestPostMethod = ({
  action,
  apiPath,
  isJson = true,
  headers = {},
}: {
  action: string;
  apiPath: string;
  isJson?: boolean;
  headers?: HeaderRecord;
}) => {
  return async <T>(params: T, init: RequestInit = {}) => {
    const configuredHeaders = mergeHeaders({ 'content-type': 'application/json' }, headers);
    const res = await apiFetch(`${apiPath}?Action=${action}`, {
      ...init,
      method: 'post',
      headers: mergeHeaders(configuredHeaders, init.headers),
      body: (isJson ? JSON.stringify(params) : params) as BodyInit,
    });
    return res;
  };
};

/**
 * @brief Return handler
 * @param res
 */
export const resultHandler = (res: RequestResponse) => {
  const { Result, ResponseMetadata } = res || {};
  // Record request id for debug.
  if (ResponseMetadata.Action === 'StartVoiceChat') {
    const requestId = ResponseMetadata.RequestId;
    requestId && sessionStorage.setItem('RequestID', requestId);
  }
  if (ResponseMetadata.Error) {
    Message.error(
      `[${ResponseMetadata?.Action}]call failed(reason: ${ResponseMetadata.Error?.Message})`
    );
    throw new Error(
      `[${ResponseMetadata?.Action}]call failed(${JSON.stringify(ResponseMetadata, null, 2)})`
    );
  }
  return Result;
};

/**
 * @brief Generate APIs by apiConfigs
 * @param apiConfigs
 */
export const generateAPIs = <T extends readonly ApiConfig[]>(apiConfigs: T) =>
  apiConfigs.reduce<Apis<T>>((store, cur) => {
    const { action, apiPath = '', method = 'get' } = cur;

    const actionKey = action as ApiNames<T>;
    store[actionKey] = async (params, init) => {
      const queryData =
        method === 'get'
          ? await requestGetMethod({ action })(params, init)
          : await requestPostMethod({ action, apiPath })(params, init);
      const res = await queryData?.json();
      return resultHandler(res);
    };
    return store;
  }, {} as Apis<T>);
