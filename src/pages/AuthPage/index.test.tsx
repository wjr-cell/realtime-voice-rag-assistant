import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, jest, test } from '@jest/globals';
import React from 'react';

import { AuthProvider } from '../../auth/AuthContext';
import AuthPage from './index';

const fetchMock = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>();
const response = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock;
});

const renderPage = async () => {
  fetchMock.mockImplementationOnce(() => response({ detail: '请先登录' }, 401));
  render(
    <AuthProvider>
      <AuthPage />
    </AuthProvider>
  );
  await waitFor(() => expect(screen.getByLabelText('用户名')).toBeTruthy());
};

describe('AuthPage', () => {
  test('登录页显示用户名、密码和注册切换', async () => {
    await renderPage();

    expect(screen.getByLabelText('用户名')).toBeTruthy();
    expect(screen.getByLabelText('密码')).toBeTruthy();
    expect(screen.getByRole('button', { name: '登录' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '注册账号' })).toBeTruthy();
  });

  test('注册模式显示确认密码，密码不一致时不发送注册请求', async () => {
    await renderPage();
    const initialCalls = fetchMock.mock.calls.length;

    await userEvent.click(screen.getByRole('button', { name: '注册账号' }));
    await userEvent.type(screen.getByLabelText('用户名'), 'new-user');
    await userEvent.type(screen.getByLabelText('密码'), 'secret12');
    await userEvent.type(screen.getByLabelText('确认密码'), 'different');
    await userEvent.click(screen.getByRole('button', { name: '注册' }));

    expect(await screen.findByText('两次输入的密码不一致')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(initialCalls);
  });

  test('登录失败展示后端 detail', async () => {
    await renderPage();
    fetchMock.mockImplementationOnce(() => response({ detail: '用户名或密码错误' }, 401));

    await userEvent.type(screen.getByLabelText('用户名'), 'bad-user');
    await userEvent.type(screen.getByLabelText('密码'), 'bad-password');
    await userEvent.click(screen.getByRole('button', { name: '登录' }));

    expect(await screen.findByText('用户名或密码错误')).toBeTruthy();
  });
});
