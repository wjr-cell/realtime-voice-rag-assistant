/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { HttpError, UNAUTHORIZED_EVENT } from '../app/http';
import * as authApi from './api';
import type { AuthUser, LoginInput, RegisterInput } from './api';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'error';

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  error: string | null;
  login: (input: LoginInput) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  logout: () => Promise<void>;
  retry: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const errorMessage = (error: unknown) =>
  error instanceof Error && error.message ? error.message : '网络错误，请重试';

export function AuthProvider({ children }: React.PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const requestGenerationRef = useRef(0);

  const beginRequest = useCallback(() => {
    requestGenerationRef.current += 1;
    return requestGenerationRef.current;
  }, []);

  const canCommit = useCallback(
    (generation: number) => mountedRef.current && requestGenerationRef.current === generation,
    []
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestGenerationRef.current += 1;
    };
  }, []);

  const loadMe = useCallback(async () => {
    const generation = beginRequest();
    if (mountedRef.current) {
      setStatus('loading');
      setError(null);
    }
    try {
      const payload = await authApi.getMe();
      if (!canCommit(generation)) return;
      setUser(payload.user);
      setStatus('authenticated');
    } catch (requestError) {
      if (!canCommit(generation)) return;
      setUser(null);
      if (requestError instanceof HttpError && requestError.status === 401) {
        setStatus('unauthenticated');
      } else {
        setError(errorMessage(requestError));
        setStatus('error');
      }
    }
  }, [beginRequest, canCommit]);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  useEffect(() => {
    const handleUnauthorized = () => {
      requestGenerationRef.current += 1;
      if (!mountedRef.current) return;
      setUser(null);
      setError(null);
      setStatus('unauthenticated');
    };
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, []);

  const authenticate = useCallback(
    async (request: () => Promise<authApi.AuthPayload>) => {
      const generation = beginRequest();
      if (mountedRef.current) setError(null);
      try {
        const payload = await request();
        if (!canCommit(generation)) return;
        setUser(payload.user);
        setStatus('authenticated');
      } catch (requestError) {
        if (canCommit(generation)) setError(errorMessage(requestError));
        throw requestError;
      }
    },
    [beginRequest, canCommit]
  );

  const login = useCallback(
    (input: LoginInput) => authenticate(() => authApi.login(input)),
    [authenticate]
  );

  const register = useCallback(
    (input: RegisterInput) => authenticate(() => authApi.register(input)),
    [authenticate]
  );

  const logout = useCallback(async () => {
    const generation = beginRequest();
    if (mountedRef.current) setError(null);
    try {
      await authApi.logout();
      if (!canCommit(generation)) return;
      setUser(null);
      setStatus('unauthenticated');
    } catch (requestError) {
      if (canCommit(generation)) {
        setError(errorMessage(requestError));
        setStatus('error');
      }
      throw requestError;
    }
  }, [beginRequest, canCommit]);

  const value = useMemo(
    () => ({ status, user, error, login, register, logout, retry: loadMe }),
    [status, user, error, login, register, logout, loadMe]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth 必须在 AuthProvider 内使用');
  return value;
}
