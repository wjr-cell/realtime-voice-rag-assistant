/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import Header from '@/components/Header';
import AuthUserActions from '@/components/AuthUserActions';
import ResizeWrapper from '@/components/ResizeWrapper';
import Menu from './Menu';
import { useIsMobile } from '@/utils/utils';
import Apis from '@/app/index';
import RtcClient from '@/lib/RtcClient';
import MainArea from './MainArea';
import { ABORT_VISIBILITY_CHANGE, useLeave } from '@/lib/useCommon';
import {
  RTCConfig,
  SceneConfig,
  updateRTCConfig,
  updateScene,
  updateSceneConfig,
} from '@/store/slices/room';
import styles from './index.module.less';

export default function () {
  const leaveRoom = useLeave();
  const dispatch = useDispatch();

  const getScenes = async (generation: number, signal: AbortSignal) => {
    const {
      scenes,
    }: {
      scenes: {
        rtc: RTCConfig;
        scene: SceneConfig;
      }[];
    } = await Apis.Basic.getScenes(undefined, { signal });
    if (!RtcClient.isSessionCurrent(generation)) return;
    dispatch(updateScene(scenes[0].scene.id));
    dispatch(
      updateSceneConfig(
        scenes.reduce<Record<string, SceneConfig>>((prev, cur) => {
          prev[cur.scene.id] = cur.scene;
          return prev;
        }, {})
      )
    );
    dispatch(
      updateRTCConfig(
        scenes.reduce<Record<string, RTCConfig>>((prev, cur) => {
          prev[cur.scene.id] = cur.rtc;
          return prev;
        }, {})
      )
    );
  };

  useEffect(() => {
    RtcClient.resetBasicInfo();
    const generation = RtcClient.beginSession();
    getScenes(generation, RtcClient.getSessionSignal(generation)).catch((error) => {
      if (error?.name !== 'AbortError') console.warn('获取场景配置失败');
    });
    const isOriginalDemo = window.location.host.startsWith('localhost');
    const handler = () => {
      if (
        document.visibilityState === 'hidden' &&
        !sessionStorage.getItem(ABORT_VISIBILITY_CHANGE)
      ) {
        leaveRoom();
      }
    };
    !isOriginalDemo && document.addEventListener('visibilitychange', handler);
    return () => {
      !isOriginalDemo && document.removeEventListener('visibilitychange', handler);
      leaveRoom(new AbortController().signal).catch(() => undefined);
    };
  }, []);

  return (
    <ResizeWrapper className={styles.container}>
      <Header>
        <AuthUserActions />
      </Header>
      <div
        className={styles.main}
        style={{
          padding: useIsMobile() ? '' : '24px',
        }}
      >
        <div className={`${styles.mainArea} ${useIsMobile() ? styles.isMobile : ''}`}>
          <MainArea />
        </div>
        {useIsMobile() ? null : (
          <div className={styles.operationArea}>
            <Menu />
          </div>
        )}
      </div>
    </ResizeWrapper>
  );
}
