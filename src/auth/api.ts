/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { apiFetch } from '../app/http';

export interface AuthUser {
  id: number;
  username: string;
}

export interface AuthPayload {
  user: AuthUser;
}

export interface LoginInput {
  username: string;
  password: string;
}

export interface RegisterInput extends LoginInput {
  confirmPassword: string;
}

async function authJson(path: string, body?: object, emit401 = false) {
  const response = await apiFetch(
    path,
    body
      ? {
          method: 'POST',
          body: JSON.stringify(body),
        }
      : undefined,
    emit401
  );
  return (await response.json()) as AuthPayload;
}

export const getMe = () => authJson('/api/auth/me', undefined, true);

export const login = (body: LoginInput) => authJson('/api/auth/login', body, false);

export const register = ({ confirmPassword, ...body }: RegisterInput) =>
  authJson('/api/auth/register', { ...body, confirm_password: confirmPassword }, false);

export const logout = () => apiFetch('/api/auth/logout', { method: 'POST' }, false);
