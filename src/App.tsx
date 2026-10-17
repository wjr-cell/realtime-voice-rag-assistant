/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { Button, Spin } from '@arco-design/web-react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import MainPage from './pages/MainPage';
import AuthPage from './pages/AuthPage';
import '@arco-design/web-react/dist/css/arco.css';

function AppContent() {
  const auth = useAuth();

  if (auth.status === 'loading') {
    return (
      <div role="status">
        <Spin /> 正在检查登录状态…
      </div>
    );
  }
  if (auth.status === 'error') {
    return (
      <div role="alert">
        <div>{auth.error || '无法检查登录状态'}</div>
        <Button onClick={auth.retry}>重试</Button>
      </div>
    );
  }
  if (auth.status === 'unauthenticated') return <AuthPage />;

  return (
    <Routes>
      <Route path="/">
        <Route index element={<MainPage />} />
        <Route path="/*" element={<MainPage />} />
      </Route>
    </Routes>
  );
}

function App() {
  console.warn('运行问题可参考 README 内容进行排查');
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
