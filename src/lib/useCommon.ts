/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { useEffect, useState, useRef } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import VERTC, { MediaType } from '@volcengine/rtc';
import { Message, Modal } from '@arco-design/web-react';
import RtcClient from '@/lib/RtcClient';
import {
  clearCurrentMsg,
  clearHistoryMsg,
  localJoinRoom,
  localLeaveRoom,
  resetRtcSession,
  updateAIGCState,
  updateLocalUser,
} from '@/store/slices/room';

import useRtcListeners from '@/lib/listenerHooks';
import { RootState } from '@/store';

import {
  updateMediaInputs,
  updateSelectedDevice,
  setDevicePermissions,
} from '@/store/slices/device';
import logger from '@/utils/logger';

export const ABORT_VISIBILITY_CHANGE = 'abortVisibilityChange';
export interface FormProps {
  username: string;
  roomId: string;
  publishAudio: boolean;
}

type RTCFailureStage =
  | 'createEngine'
  | 'addEventListeners'
  | 'joinRoom'
  | 'getDevices'
  | 'StartVoiceChat';

const RTC_JOIN_TIMEOUT_MS = 15_000;

const joinRoomWithTimeout = (joinRequest: Promise<void>) =>
  new Promise<void>((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      reject(
        Object.assign(new Error(`joinRoom timed out after ${RTC_JOIN_TIMEOUT_MS}ms`), {
          code: 'JOIN_TIMEOUT',
        })
      );
    }, RTC_JOIN_TIMEOUT_MS);
    joinRequest.then(
      () => {
        window.clearTimeout(timeoutId);
        resolve();
      },
      (error) => {
        window.clearTimeout(timeoutId);
        reject(error);
      }
    );
  });

const reportRTCFailure = (stage: RTCFailureStage, error: unknown) => {
  const failure =
    error && typeof error === 'object'
      ? (error as {
          code?: string | number;
          errorCode?: string | number;
          status?: string | number;
          name?: string;
          message?: string;
        })
      : {};
  const code = String(
    failure.code || failure.errorCode || failure.status || failure.name || 'UNKNOWN'
  );
  const token = RtcClient.basicInfo?.token;
  let message = typeof failure.message === 'string' ? failure.message : '';
  if (token) message = message.split(token).join('[REDACTED]');
  message = message.replace(/001[A-Za-z0-9+/_=-]+/g, '[REDACTED]').slice(0, 300);

  console.error('[RTC 通话失败]', { stage, code, message });
  Message.error(`RTC ${stage} 失败：${code}`);
};

export const useScene = () => {
  const { scene, sceneConfigMap } = useSelector((state: RootState) => state.room);
  return sceneConfigMap[scene] || {};
};

export const useRTC = () => {
  const { scene, rtcConfigMap } = useSelector((state: RootState) => state.room);
  return rtcConfigMap[scene] || {};
};

export const useDeviceState = () => {
  const dispatch = useDispatch();
  const room = useSelector((state: RootState) => state.room);
  const localUser = room.localUser;
  const isAudioPublished = localUser.publishAudio;
  const isVideoPublished = localUser.publishVideo;
  const isScreenPublished = localUser.publishScreen;
  const queryDevices = async (type: MediaType) => {
    const mediaDevices = await RtcClient.getDevices({
      audio: type === MediaType.AUDIO,
      video: type === MediaType.VIDEO,
    });
    if (type === MediaType.AUDIO) {
      dispatch(
        updateMediaInputs({
          audioInputs: mediaDevices.audioInputs,
        })
      );
      dispatch(
        updateSelectedDevice({
          selectedMicrophone: mediaDevices.audioInputs[0]?.deviceId,
        })
      );
    } else {
      dispatch(
        updateMediaInputs({
          videoInputs: mediaDevices.videoInputs,
        })
      );
      dispatch(
        updateSelectedDevice({
          selectedCamera: mediaDevices.videoInputs[0]?.deviceId,
        })
      );
    }
    return mediaDevices;
  };

  const switchMic = async (controlPublish = true) => {
    if (controlPublish) {
      await (!isAudioPublished
        ? RtcClient.publishStream(MediaType.AUDIO)
        : RtcClient.unpublishStream(MediaType.AUDIO));
    }
    queryDevices(MediaType.AUDIO);
    await (!isAudioPublished ? RtcClient.startAudioCapture() : RtcClient.stopAudioCapture());
    dispatch(
      updateLocalUser({
        publishAudio: !isAudioPublished,
      })
    );
  };

  const switchCamera = async (controlPublish = true) => {
    if (controlPublish) {
      await (!isVideoPublished
        ? RtcClient.publishStream(MediaType.VIDEO)
        : RtcClient.unpublishStream(MediaType.VIDEO));
    }
    queryDevices(MediaType.VIDEO);
    await (!isVideoPublished ? RtcClient.startVideoCapture() : RtcClient.stopVideoCapture());
    dispatch(
      updateLocalUser({
        publishVideo: !isVideoPublished,
      })
    );
  };

  const switchScreenCapture = async (controlPublish = true) => {
    try {
      !isScreenPublished
        ? sessionStorage.setItem(ABORT_VISIBILITY_CHANGE, 'true')
        : sessionStorage.removeItem(ABORT_VISIBILITY_CHANGE);
      if (controlPublish) {
        await (!isScreenPublished
          ? RtcClient.publishScreenStream(MediaType.VIDEO)
          : RtcClient.unpublishScreenStream(MediaType.VIDEO));
      }
      await (!isScreenPublished ? RtcClient.startScreenCapture() : RtcClient.stopScreenCapture());
      dispatch(
        updateLocalUser({
          publishScreen: !isScreenPublished,
        })
      );
    } catch {
      console.warn('Not Authorized.');
    }
    sessionStorage.removeItem(ABORT_VISIBILITY_CHANGE);
    return false;
  };

  return {
    isAudioPublished,
    isVideoPublished,
    isScreenPublished,
    switchMic,
    switchCamera,
    switchScreenCapture,
  };
};

export const useGetDevicePermission = () => {
  const [permission, setPermission] = useState<{
    audio: boolean;
  }>();

  const dispatch = useDispatch();

  useEffect(() => {
    (async () => {
      const permission = await RtcClient.checkPermission();
      dispatch(setDevicePermissions(permission));
      setPermission(permission);
    })();
  }, [dispatch]);
  return permission;
};

export const useJoin = (): [boolean, () => Promise<void | boolean>] => {
  const devicePermissions = useSelector((state: RootState) => state.device.devicePermissions);
  const room = useSelector((state: RootState) => state.room);

  const dispatch = useDispatch();

  const { id } = useScene();
  const [joining, setJoining] = useState(false);
  const listeners = useRtcListeners();
  const mountedRef = useRef(true);

  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    []
  );

  const handleAIGCModeStart = async (generation: number) => {
    if (room.isAIGCEnable) {
      await RtcClient.stopAgent(id);
      if (!RtcClient.isSessionCurrent(generation) || !mountedRef.current) return false;
      await RtcClient.startAgent(id, generation);
    } else {
      await RtcClient.startAgent(id, generation);
    }
    return RtcClient.isSessionCurrent(generation) && mountedRef.current;
  };

  async function disPatchJoin(): Promise<boolean | undefined> {
    if (joining) {
      return;
    }
    const generation = RtcClient.getSessionGeneration();
    const isActive = () => RtcClient.isSessionCurrent(generation) && mountedRef.current;

    const isSupported = await VERTC.isSupported();
    if (!isActive()) return;
    if (!isSupported) {
      Modal.error({
        title: '不支持 RTC',
        content: '您的浏览器可能不支持 RTC 功能，请尝试更换浏览器或升级浏览器后再重试。',
      });
      return;
    }

    setJoining(true);
    let ownership: Awaited<ReturnType<typeof RtcClient.createEngine>> | undefined;
    let joined = false;
    let stage: RTCFailureStage = 'createEngine';
    try {
      /** 1. Create RTC Engine */
      ownership = await RtcClient.createEngine();
      if (!isActive()) return false;

      /** 2.1 Set events callbacks */
      stage = 'addEventListeners';
      RtcClient.addEventListeners(listeners, ownership);

      /** 2.2 RTC starting to join room */
      stage = 'joinRoom';
      await joinRoomWithTimeout(RtcClient.joinRoom(ownership));
      if (!isActive()) return false;

      /** 3. Set users' devices info */
      stage = 'getDevices';
      const mediaDevices = await RtcClient.getDevices({
        audio: true,
        video: false,
      });
      if (!isActive()) return false;

      if (devicePermissions.audio) {
        try {
          RtcClient.publishStream(MediaType.AUDIO, ownership);
          await RtcClient.startAudioCapture(mediaDevices.audioInputs[0]?.deviceId, ownership);
        } catch (e) {
          logger.debug('No permission for mic');
        }
      }

      if (!isActive()) return false;
      stage = 'StartVoiceChat';
      if (!(await handleAIGCModeStart(generation)) || !isActive()) return false;

      dispatch(
        localJoinRoom({
          roomId: RtcClient.basicInfo.room_id,
          user: {
            username: RtcClient.basicInfo.user_id,
            userId: RtcClient.basicInfo.user_id,
          },
        })
      );
      dispatch(
        updateSelectedDevice({
          selectedMicrophone: mediaDevices.audioInputs[0]?.deviceId,
          selectedCamera: mediaDevices.videoInputs[0]?.deviceId,
        })
      );
      dispatch(updateMediaInputs(mediaDevices));
      if (devicePermissions.audio) dispatch(updateLocalUser({ publishAudio: true }));
      dispatch(clearCurrentMsg());
      dispatch(updateAIGCState({ isAIGCEnable: true }));
      joined = true;
      return true;
    } catch (error) {
      reportRTCFailure(stage, error);
      return false;
    } finally {
      if (!joined && ownership) await RtcClient.leaveRoom(ownership).catch(() => undefined);
      if (mountedRef.current) setJoining(false);
    }
  }

  return [joining, disPatchJoin];
};

export const useLeave = () => {
  const dispatch = useDispatch();
  const { id } = useScene();
  const idRef = useRef(id);
  idRef.current = id;

  type LeaveRoom = {
    (): Promise<void>;
    (signal: AbortSignal): Promise<void>;
  };
  const leaveRoom: LeaveRoom = async (signal?: AbortSignal) => {
    const abortSignal = signal instanceof AbortSignal ? signal : undefined;
    const ownership = RtcClient.captureEngineOwnership();
    RtcClient.invalidateSession(ownership.sessionGeneration);
    if (abortSignal) {
      RtcClient.resetBasicInfo();
      dispatch(resetRtcSession());
    } else {
      dispatch(clearHistoryMsg());
      dispatch(clearCurrentMsg());
      dispatch(localLeaveRoom());
      dispatch(updateAIGCState({ isAIGCEnable: false }));
      RtcClient.beginSession();
    }
    try {
      await RtcClient.stopAgent(idRef.current, abortSignal, ownership);
    } finally {
      await Promise.allSettled([
        RtcClient.stopAudioCapture(ownership),
        RtcClient.stopScreenCapture(ownership),
        RtcClient.stopVideoCapture(ownership),
      ]);
      await RtcClient.leaveRoom(ownership);
    }
  };

  return leaveRoom;
};
