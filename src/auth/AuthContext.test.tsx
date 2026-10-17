import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';
import React from 'react';

import { generateAPIs, requestPostMethod } from '../app/base';
import { apiFetch, HttpError, UNAUTHORIZED_EVENT } from '../app/http';
import { AuthProvider, useAuth } from './AuthContext';

const fetchMock = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>();

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

const jsonResponse = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    })
  );

function AuthHarness() {
  const auth = useAuth();

  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="username">{auth.user?.username || ''}</span>
      <span data-testid="error">{auth.error || ''}</span>
      <button onClick={() => auth.retry()}>retry</button>
      <button
        onClick={() => auth.login({ username: 'Alice', password: 'secret12' }).catch(() => {})}
      >
        login
      </button>
      <button
        onClick={() =>
          auth
            .register({ username: 'Bob', password: 'secret12', confirmPassword: 'secret12' })
            .catch(() => {})
        }
      >
        register
      </button>
      <button onClick={() => auth.logout().catch(() => {})}>logout</button>
      <button onClick={() => apiFetch('/getScenes', { method: 'POST' }).catch(() => {})}>
        ordinary
      </button>
    </div>
  );
}

const renderAuth = () =>
  render(
    <AuthProvider>
      <AuthHarness />
    </AuthProvider>
  );

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock;
});

describe('AuthProvider', () => {
  test('首次 me 请求携带 cookie，并在成功后进入 authenticated', async () => {
    fetchMock.mockImplementationOnce(() => jsonResponse({ user: { id: 7, username: 'alice' } }));

    renderAuth();

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
    expect(screen.getByTestId('username').textContent).toBe('alice');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/auth\/me$/),
      expect.objectContaining({ credentials: 'include' })
    );
  });

  test('me 返回 401 时进入 unauthenticated', async () => {
    fetchMock.mockImplementationOnce(() => jsonResponse({ detail: '请先登录' }, 401));

    renderAuth();

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
  });

  test('me 网络错误进入 error，retry 后可恢复', async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockImplementationOnce(() => jsonResponse({ user: { id: 8, username: 'retry-user' } }));
    renderAuth();

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('error'));
    await userEvent.click(screen.getByRole('button', { name: 'retry' }));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
    expect(screen.getByTestId('username').textContent).toBe('retry-user');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test('login 成功保存用户，失败时保留服务端 detail 且不发全局 401', async () => {
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ detail: '请先登录' }, 401))
      .mockImplementationOnce(() => jsonResponse({ user: { id: 1, username: 'alice' } }))
      .mockImplementationOnce(() => jsonResponse({ detail: '用户名或密码错误' }, 401));
    const unauthorized = jest.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, unauthorized);
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
    unauthorized.mockClear();

    await userEvent.click(screen.getByRole('button', { name: 'login' }));
    await waitFor(() => expect(screen.getByTestId('username').textContent).toBe('alice'));
    await userEvent.click(screen.getByRole('button', { name: 'login' }));
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('用户名或密码错误'));

    expect(unauthorized).not.toHaveBeenCalled();
    window.removeEventListener(UNAUTHORIZED_EVENT, unauthorized);
  });

  test('register 映射 confirmPassword 并在成功时保存用户', async () => {
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ detail: '请先登录' }, 401))
      .mockImplementationOnce(() => jsonResponse({ user: { id: 2, username: 'bob' } }));
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));

    await userEvent.click(screen.getByRole('button', { name: 'register' }));

    await waitFor(() => expect(screen.getByTestId('username').textContent).toBe('bob'));
    const [, init] = fetchMock.mock.calls[1];
    expect(init).toBeDefined();
    const requestBody = JSON.parse(String(init?.body));
    expect(requestBody).toEqual({
      username: 'Bob',
      password: 'secret12',
      confirm_password: 'secret12',
    });
    expect(requestBody).not.toHaveProperty('confirmPassword');
  });

  test('register 失败时暴露服务端 detail', async () => {
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ detail: '请先登录' }, 401))
      .mockImplementationOnce(() => jsonResponse({ detail: '用户名已存在' }, 409));
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));

    await userEvent.click(screen.getByRole('button', { name: 'register' }));

    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('用户名已存在'));
  });

  test('普通 API 的 401 全局事件会清除当前用户', async () => {
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ user: { id: 3, username: 'carol' } }))
      .mockImplementationOnce(() => jsonResponse({ detail: '登录已过期' }, 401));
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('username').textContent).toBe('carol'));

    await userEvent.click(screen.getByRole('button', { name: 'ordinary' }));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
    expect(screen.getByTestId('username').textContent).toBe('');
  });

  test('logout 接受 204 响应而不解析 JSON', async () => {
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ user: { id: 4, username: 'dave' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));

    await userEvent.click(screen.getByRole('button', { name: 'logout' }));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
  });

  test('后发 retry 成功后，先发 retry 的失败不能覆盖认证状态', async () => {
    const olderRetry = deferred<Response>();
    const newerRetry = deferred<Response>();
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ detail: '请先登录' }, 401))
      .mockReturnValueOnce(olderRetry.promise)
      .mockReturnValueOnce(newerRetry.promise);
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));

    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    await act(async () => {
      newerRetry.resolve(await jsonResponse({ user: { id: 9, username: 'newer-retry' } }));
    });
    await waitFor(() => expect(screen.getByTestId('username').textContent).toBe('newer-retry'));
    await act(async () => {
      olderRetry.reject(new TypeError('older request failed'));
      await Promise.resolve();
    });

    expect(screen.getByTestId('status').textContent).toBe('authenticated');
    expect(screen.getByTestId('username').textContent).toBe('newer-retry');
    expect(screen.getByTestId('error').textContent).toBe('');
  });

  test('login 开始后会让尚未完成的 me 响应失效', async () => {
    const pendingMe = deferred<Response>();
    const pendingLogin = deferred<Response>();
    fetchMock.mockReturnValueOnce(pendingMe.promise).mockReturnValueOnce(pendingLogin.promise);
    renderAuth();

    await userEvent.click(screen.getByRole('button', { name: 'login' }));
    await act(async () => {
      pendingLogin.resolve(await jsonResponse({ user: { id: 10, username: 'login-user' } }));
    });
    await waitFor(() => expect(screen.getByTestId('username').textContent).toBe('login-user'));
    await act(async () => {
      pendingMe.resolve(await jsonResponse({ user: { id: 11, username: 'stale-me' } }));
    });

    expect(screen.getByTestId('status').textContent).toBe('authenticated');
    expect(screen.getByTestId('username').textContent).toBe('login-user');
  });

  test('全局 401 会失效进行中的 login，旧成功响应不能恢复用户', async () => {
    const pendingLogin = deferred<Response>();
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ detail: '请先登录' }, 401))
      .mockReturnValueOnce(pendingLogin.promise);
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));

    await userEvent.click(screen.getByRole('button', { name: 'login' }));
    act(() => window.dispatchEvent(new Event(UNAUTHORIZED_EVENT)));
    await act(async () => {
      pendingLogin.resolve(await jsonResponse({ user: { id: 12, username: 'stale-login' } }));
    });

    expect(screen.getByTestId('status').textContent).toBe('unauthenticated');
    expect(screen.getByTestId('username').textContent).toBe('');
  });

  test('logout 会失效旧请求，且 logout 失败进入 error 而不会被旧响应复活', async () => {
    const pendingRetry = deferred<Response>();
    fetchMock
      .mockImplementationOnce(() => jsonResponse({ user: { id: 13, username: 'signed-in' } }))
      .mockReturnValueOnce(pendingRetry.promise)
      .mockRejectedValueOnce(new TypeError('logout network failed'));
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));

    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    await userEvent.click(screen.getByRole('button', { name: 'logout' }));
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('error'));
    await act(async () => {
      pendingRetry.resolve(await jsonResponse({ user: { id: 14, username: 'stale-retry' } }));
    });

    expect(screen.getByTestId('status').textContent).toBe('error');
    expect(screen.getByTestId('username').textContent).toBe('signed-in');
    expect(screen.getByTestId('error').textContent).toBe('logout network failed');
  });

  test('卸载后异步响应完成不会产生状态更新警告', async () => {
    const pendingMe = deferred<Response>();
    fetchMock.mockReturnValueOnce(pendingMe.promise);
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    const view = renderAuth();

    view.unmount();
    await act(async () => {
      pendingMe.resolve(await jsonResponse({ user: { id: 15, username: 'after-unmount' } }));
    });

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});

describe('apiFetch 和现有 RTC API', () => {
  test('apiFetch 对错误响应抛出带状态和 detail 的 HttpError', async () => {
    fetchMock.mockImplementationOnce(() => jsonResponse({ detail: '服务异常' }, 503));
    const request = apiFetch('/health');

    await expect(request).rejects.toBeInstanceOf(HttpError);
    await expect(request).rejects.toEqual(
      expect.objectContaining({ status: 503, message: '服务异常' })
    );
  });

  test('apiFetch 保留 Headers 实例并允许大小写无关地覆盖默认 Content-Type', async () => {
    fetchMock.mockImplementationOnce(() => jsonResponse({ ok: true }));

    await apiFetch('/headers', {
      headers: new Headers({ 'X-Headers-Instance': 'kept', 'Content-Type': 'text/plain' }),
    });

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get('x-headers-instance')).toBe('kept');
    expect(headers.get('content-type')).toBe('text/plain');
  });

  test('apiFetch 保留 tuple headers 并覆盖默认 Content-Type', async () => {
    fetchMock.mockImplementationOnce(() => jsonResponse({ ok: true }));

    await apiFetch('/tuple-headers', {
      headers: [
        ['X-Tuple', 'kept'],
        ['Content-Type', 'application/custom'],
      ],
    });

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get('x-tuple')).toBe('kept');
    expect(headers.get('content-type')).toBe('application/custom');
  });

  test('base header 与 RequestInit Headers 合并且调用方大小写无关覆盖默认值', async () => {
    fetchMock.mockImplementationOnce(() => jsonResponse({ ok: true }));
    const request = requestPostMethod({
      action: 'HeaderAction',
      apiPath: '/proxy',
      headers: { 'X-Base': 'base', 'content-type': 'application/base' },
    });

    await request(
      {},
      {
        headers: new Headers({ 'X-Init': 'init', 'Content-Type': 'text/plain' }),
      }
    );

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get('x-base')).toBe('base');
    expect(headers.get('x-init')).toBe('init');
    expect(headers.get('content-type')).toBe('text/plain');
  });

  test('生成的 RTC API 保持原有单参数调用兼容', async () => {
    fetchMock.mockImplementationOnce(() =>
      jsonResponse({ ResponseMetadata: { Action: 'getScenes' }, Result: { scenes: ['default'] } })
    );
    const apis = generateAPIs([
      { action: 'getScenes', method: 'post', apiPath: '/getScenes' },
    ] as const);

    await expect(apis.getScenes({})).resolves.toEqual({ scenes: ['default'] });
  });

  test('生成的 RTC API 接受第二个 RequestInit 并透传 signal', async () => {
    fetchMock.mockImplementationOnce(() =>
      jsonResponse({ ResponseMetadata: { Action: 'getScenes' }, Result: { scenes: [] } })
    );
    const controller = new AbortController();
    const apis = generateAPIs([
      { action: 'getScenes', method: 'post', apiPath: '/getScenes' },
    ] as const);

    await apis.getScenes({}, { signal: controller.signal });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/getScenes?Action=getScenes'),
      expect.objectContaining({ credentials: 'include', signal: controller.signal })
    );
  });
});

describe('API base', () => {
  const originalNodeEnv = process.env.NODE_ENV;
  const originalConfiguredBase = process.env.REACT_APP_API_BASE;

  afterEach(() => {
    Object.defineProperty(process.env, 'NODE_ENV', { value: originalNodeEnv, configurable: true });
    if (originalConfiguredBase === undefined) delete process.env.REACT_APP_API_BASE;
    else process.env.REACT_APP_API_BASE = originalConfiguredBase;
    jest.resetModules();
  });

  const loadBase = (nodeEnv: string, configured?: string) => {
    Object.defineProperty(process.env, 'NODE_ENV', { value: nodeEnv, configurable: true });
    if (configured === undefined) delete process.env.REACT_APP_API_BASE;
    else process.env.REACT_APP_API_BASE = configured;
    let base = '';
    jest.isolateModules(() => {
      base = require('../config').AIGC_PROXY_HOST;
    });
    return base;
  };

  test('development 默认使用当前主机的 3001 端口', () => {
    expect(loadBase('development')).toBe(`http://${window.location.hostname}:3001`);
  });

  test('production 默认使用页面同源地址', () => {
    expect(loadBase('production')).toBe(window.location.origin);
  });

  test('显式配置的 API base 优先并移除结尾斜杠', () => {
    expect(loadBase('production', 'https://api.example.com/')).toBe('https://api.example.com');
  });
});
