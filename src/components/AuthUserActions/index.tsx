/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { Button } from '@arco-design/web-react';
import { useState } from 'react';
import { useAuth } from '../../auth/AuthContext';
import { useLeave } from '../../lib/useCommon';
import styles from './index.module.less';

export default function AuthUserActions() {
  const { user, logout } = useAuth();
  const leaveRoom = useLeave();
  const [submitting, setSubmitting] = useState(false);

  const handleLogout = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const controller = new AbortController();
      let timeoutId: number | undefined;
      const cleanup = leaveRoom(controller.signal).catch(() => undefined);
      const timeout = new Promise<void>((resolve) => {
        timeoutId = window.setTimeout(() => {
          controller.abort();
          resolve();
        }, 3000);
      });
      try {
        await Promise.race([cleanup, timeout]);
      } finally {
        if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      }
    } finally {
      try {
        await logout();
      } finally {
        setSubmitting(false);
      }
    }
  };

  return (
    <div className={styles.actions}>
      <div className={styles.userBadge}>
        <span className={styles.avatarDot} />
        <span className={styles.username}>{user?.username}</span>
      </div>
      <Button
        type="outline"
        size="small"
        onClick={() => void handleLogout().catch(() => undefined)}
        loading={submitting}
        disabled={submitting}
        className={styles.logoutBtn}
      >
        退出登录
      </Button>
    </div>
  );
}
