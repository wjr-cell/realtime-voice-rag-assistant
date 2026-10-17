/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

export type RequestParams = Record<string, any>;

export interface RequestResponse {
  ResponseMetadata: Partial<{
    Action: string;
    Version: string;
    Service: string;
    Region: string;
    RequestId: string;
    Error: {
      Code: string;
      Message: string;
    };
  }>;
  Result: any;
}

type TupleToUnion<T extends readonly unknown[]> = T[number];
type PromiseRequestFn = (params?: RequestParams, init?: RequestInit) => Promise<any>;

export type ApiConfig = { action: string; method: string; apiPath?: string };
export type ApiNames<T extends readonly ApiConfig[]> = TupleToUnion<T>['action'];
export type Apis<T extends readonly ApiConfig[]> = Record<ApiNames<T>, PromiseRequestFn>;
