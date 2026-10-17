/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

export const Disclaimer = 'https://www.volcengine.com/docs/6348/68916';
export const ReversoContext = 'https://www.volcengine.com/docs/6348/68918';
export const UserAgreement = 'https://www.volcengine.com/docs/6348/128955';

/**
 * @note 请求的 API Proxy Server 地址。
 *       开发环境默认使用当前主机的 3001 端口，生产环境默认使用同源反向代理。
 */
const configuredApiBase = process.env.REACT_APP_API_BASE?.replace(/\/$/, '');
export const AIGC_PROXY_HOST =
  configuredApiBase ||
  (process.env.NODE_ENV === 'development'
    ? `http://${window.location.hostname}:3001`
    : window.location.origin);

export interface IScene {
  icon: string;
  name: string;
  questions: string[];
  agentConfig: Record<string, any>;
  llmConfig: Record<string, any>;
  asrConfig: Record<string, any>;
  ttsConfig: Record<string, any>;
}
