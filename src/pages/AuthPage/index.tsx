/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { Alert, Button, Card, Input } from '@arco-design/web-react';
import { IconUser, IconLock, IconArrowRight, IconRobot } from '@arco-design/web-react/icon';
import { FormEvent, useState } from 'react';
import { useAuth } from '../../auth/AuthContext';
import Logo from '@/assets/img/dongwang_logo.jpg';
import styles from './index.module.less';

type Mode = 'login' | 'register';

export default function AuthPage() {
  const auth = useAuth();
  const [mode, setMode] = useState<Mode>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const switchMode = () => {
    setMode((current) => (current === 'login' ? 'register' : 'login'));
    setPassword('');
    setConfirmPassword('');
    setLocalError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    if (mode === 'register' && password !== confirmPassword) {
      setLocalError('两次输入的密码不一致');
      return;
    }
    setSubmitting(true);
    try {
      if (mode === 'login') await auth.login({ username, password });
      else await auth.register({ username, password, confirmPassword });
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : '请求失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.logoBadge}>
            <img src={Logo} alt="Logo" className={styles.logoImg} />
          </div>
          <h1 className={styles.title}>实时对话式 AI 体验馆</h1>
          <p className={styles.subtitle}>
            <IconRobot className={styles.sparkleIcon} />
            智能语音交互，即刻开启体验
          </p>
        </div>

        <Card className={styles.card}>

          <div className={styles.tabHeader}>
            <span className={styles.activeTab}>
              {mode === 'login' ? '账号登录' : '创建新账号'}
            </span>
          </div>

          <form onSubmit={submit} className={styles.form}>
            {localError && <Alert type="error" content={localError} className={styles.alert} closable />}
            
            <div className={styles.formItem}>
              <label htmlFor="auth-username" className={styles.label}>用户名</label>
              <Input
                id="auth-username"
                size="large"
                prefix={<IconUser style={{ color: '#86909c' }} />}
                placeholder="请输入用户名"
                value={username}
                onChange={setUsername}
                autoComplete="username"
                required
                className={styles.input}
              />
            </div>

            <div className={styles.formItem}>
              <label htmlFor="auth-password" className={styles.label}>密码</label>
              <Input.Password
                id="auth-password"
                size="large"
                prefix={<IconLock style={{ color: '#86909c' }} />}
                placeholder="请输入密码"
                value={password}
                onChange={setPassword}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                className={styles.input}
              />
            </div>

            {mode === 'register' && (
              <div className={styles.formItem}>
                <label htmlFor="auth-confirm-password" className={styles.label}>确认密码</label>
                <Input.Password
                  id="auth-confirm-password"
                  size="large"
                  prefix={<IconLock style={{ color: '#86909c' }} />}
                  placeholder="请再次输入密码"
                  value={confirmPassword}
                  onChange={setConfirmPassword}
                  autoComplete="new-password"
                  required
                  className={styles.input}
                />
              </div>
            )}

            <Button
              type="primary"
              htmlType="submit"
              size="large"
              loading={submitting}
              disabled={submitting}
              long
              className={styles.submitBtn}
            >
              <span>{mode === 'login' ? '登 录' : '注 册'}</span>
              <IconArrowRight style={{ marginLeft: 6 }} />
            </Button>

            <div className={styles.switchBox}>
              <span className={styles.switchText}>
                {mode === 'login' ? '还没有账号？' : '已有账号？'}
              </span>
              <Button type="text" onClick={switchMode} disabled={submitting} className={styles.switchBtn}>
                {mode === 'login' ? '立即注册' : '返回登录'}
              </Button>
            </div>
          </form>
        </Card>

        <footer className={styles.footer}>
          Powered by 豆包大模型 & 懂王 AI
        </footer>
      </div>
    </main>
  );
}

