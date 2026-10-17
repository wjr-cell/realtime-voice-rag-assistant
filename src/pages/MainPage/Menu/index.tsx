/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import VERTC from '@volcengine/rtc';
import { Tooltip, Typography } from '@arco-design/web-react';
import { IconRobot, IconInfoCircle } from '@arco-design/web-react/icon';
import { useSelector } from 'react-redux';
import { RootState } from '@/store';
import Operation from './components/Operation';
import CameraArea from '../MainArea/Room/CameraArea';
import { isMobile } from '@/utils/utils';
import { useScene } from '@/lib/useCommon';
import packageJson from '../../../../package.json';
import styles from './index.module.less';

function Menu() {
  const room = useSelector((state: RootState) => state.room);
  const isJoined = room?.isJoined;
  const { isVision, name } = useScene();
  const requestId = sessionStorage.getItem('RequestID');

  return (
    <div className={styles.wrapper}>
      {isJoined && isMobile() && isVision ? (
        <div className={styles['mobile-camera-wrapper']}>
          <CameraArea className={styles['mobile-camera']} />
        </div>
      ) : null}
      <div className={`${styles.box} ${styles.info}`}>
        <div className={styles.headerTitle}>
          <IconRobot className={styles.icon} />
          <span>AI 人设</span>
        </div>
        <div className={styles.personaTag}>{name}</div>
      </div>
      {isJoined ? <Operation /> : ''}
      <div className={`${styles.box} ${styles.info}`}>
        <div className={styles.headerTitle}>
          <IconInfoCircle className={styles.icon} />
          <span>{isJoined ? '其他信息' : '版本信息'}</span>
        </div>
        <div className={styles.desc}>
          <span className={styles.label}>Demo 版本</span>
          <span className={styles.val}>{packageJson.version}</span>
        </div>
        <div className={styles.desc}>
          <span className={styles.label}>SDK 版本</span>
          <span className={styles.val}>{VERTC.getSdkVersion()}</span>
        </div>

        {isJoined ? (
          <div className={styles.desc}>
            房间ID{' '}
            <Tooltip content={room.roomId || '-'}>
              <Typography.Paragraph
                ellipsis={{
                  rows: 1,
                  expandable: false,
                }}
                className={styles.value}
              >
                {room.roomId || '-'}
              </Typography.Paragraph>
            </Tooltip>
          </div>
        ) : (
          ''
        )}
        {room.isAIGCEnable ? (
          <div className={styles.desc}>
            RequestID{' '}
            <Tooltip content={requestId || '-'}>
              <Typography.Paragraph
                ellipsis={{
                  rows: 1,
                  expandable: false,
                }}
                className={styles.value}
              >
                {requestId || '-'}
              </Typography.Paragraph>
            </Tooltip>
          </div>
        ) : (
          ''
        )}
      </div>
    </div>
  );
}

export default Menu;
