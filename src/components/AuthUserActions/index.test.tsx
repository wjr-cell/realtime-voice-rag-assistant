/* eslint-disable import/first */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, jest, test } from '@jest/globals';
import React from 'react';

const mockLogout = jest.fn<Promise<void>, []>();
const mockLeaveRoom = jest.fn<Promise<void>, [AbortSignal?]>();
const mockStopVoiceChat = jest.fn<Promise<void>, [unknown, RequestInit?]>();
const mockStartVoiceChat = jest.fn<Promise<void>, [unknown]>();
const mockString2tlv = jest.fn<Uint8Array, unknown[]>();
const mockCreateRtcEngine = jest.fn();

function mockStopVoiceChatProxy(...args: any[]) {
  return mockStopVoiceChat(args[0], args[1]);
}

function mockStartVoiceChatProxy(...args: any[]) {
  return mockStartVoiceChat(args[0]);
}

function mockString2tlvProxy(...args: any[]) {
  return mockString2tlv(args);
}

function mockCreateRtcEngineProxy(...args: any[]) {
  return mockCreateRtcEngine(args[0]);
}

jest.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, username: 'alice' }, logout: mockLogout }),
}));
jest.mock('../../lib/useCommon', () => ({ useLeave: () => mockLeaveRoom }));
jest.mock(
  '@/app/index',
  () => ({
    __esModule: true,
    default: {
      VoiceChat: {
        StopVoiceChat: mockStopVoiceChatProxy,
        StartVoiceChat: mockStartVoiceChatProxy,
      },
    },
  }),
  { virtual: true }
);
jest.mock('@/utils/utils', () => ({ string2tlv: mockString2tlvProxy }), { virtual: true });
jest.mock('@/utils/handler', () => ({ COMMAND: {}, INTERRUPT_PRIORITY: { NONE: 0 } }), {
  virtual: true,
});
jest.mock('@/lib/RtcClient', () => ({ __esModule: true, default: { basicInfo: undefined } }), {
  virtual: true,
});
jest.mock('@volcengine/rtc', () => ({
  __esModule: true,
  default: {
    createEngine: mockCreateRtcEngineProxy,
    destroyEngine: (engine: unknown) => mockDestroyEngineProxy(engine),
    events: {
      onError: 'onError',
      onUserJoined: 'onUserJoined',
      onUserLeave: 'onUserLeave',
      onTrackEnded: 'onTrackEnded',
      onUserPublishStream: 'onUserPublishStream',
      onUserUnpublishStream: 'onUserUnpublishStream',
      onRemoteStreamStats: 'onRemoteStreamStats',
      onLocalStreamStats: 'onLocalStreamStats',
      onAudioDeviceStateChanged: 'onAudioDeviceStateChanged',
      onLocalAudioPropertiesReport: 'onLocalAudioPropertiesReport',
      onRemoteAudioPropertiesReport: 'onRemoteAudioPropertiesReport',
      onAutoplayFailed: 'onAutoplayFailed',
      onPlayerEvent: 'onPlayerEvent',
      onRoomBinaryMessageReceived: 'onRoomBinaryMessageReceived',
      onNetworkQuality: 'onNetworkQuality',
    },
  },
  MirrorType: { MIRROR_TYPE_RENDER: 0 },
  StreamIndex: { STREAM_INDEX_MAIN: 0, STREAM_INDEX_SCREEN: 1 },
  RoomProfileType: { chat: 0 },
  MediaType: { AUDIO: 1, VIDEO: 2, AUDIO_AND_VIDEO: 3 },
  AudioProfileType: {},
  NetworkQuality: { UNKNOWN: 0 },
  VideoRenderMode: { RENDER_MODE_FILL: 0, RENDER_MODE_HIDDEN: 1 },
}));
jest.mock('@volcengine/rtc/extension-ainr', () => ({
  __esModule: true,
  default: class MockExtension {
    enable() {}
  },
}));

import AuthUserActions from './index';
import { RTCClient } from '../../lib/RtcClient';
import roomReducer, {
  localJoinRoom,
  resetRtcSession,
  updateRTCConfig,
  updateScene,
  updateSceneConfig,
} from '../../store/slices/room';

const mockDestroyEngine = jest.fn<void, [unknown]>();

function mockDestroyEngineProxy(engine: unknown) {
  return mockDestroyEngine(engine);
}

beforeEach(() => {
  mockLogout.mockReset().mockResolvedValue(undefined);
  mockLeaveRoom.mockReset().mockResolvedValue(undefined);
  mockStopVoiceChat.mockReset().mockResolvedValue(undefined);
  mockDestroyEngine.mockReset();
  mockCreateRtcEngine.mockReset();
  jest.useRealTimers();
});

describe('RTC logout support', () => {
  test('createEngine A 挂起期间创建 B，A 恢复只清理 A 且 ownership 不漂移', async () => {
    const client = new RTCClient();
    client.basicInfo = { app_id: 'app', room_id: 'room', user_id: 'user' };
    let finishA!: () => void;
    const engineA = {
      registerExtension: jest.fn(
        () =>
          new Promise<void>((resolve) => {
            finishA = resolve;
          })
      ),
      leaveRoom: jest.fn<Promise<void>, []>().mockResolvedValue(undefined),
    } as any;
    const engineB = {
      registerExtension: jest.fn<Promise<void>, [unknown]>().mockResolvedValue(undefined),
      leaveRoom: jest.fn<Promise<void>, []>().mockResolvedValue(undefined),
    } as any;
    mockCreateRtcEngine.mockReturnValueOnce(engineA).mockReturnValueOnce(engineB);

    const createA = client.createEngine();
    await Promise.resolve();
    client.invalidateSession();
    const ownershipB = await client.createEngine();
    finishA();
    const ownershipA = await createA;

    expect(ownershipA.engine).toBe(engineA);
    expect(ownershipB.engine).toBe(engineB);
    expect(client.engine).toBe(engineB);
    expect(mockDestroyEngine).toHaveBeenCalledWith(engineA);
    expect(mockDestroyEngine).not.toHaveBeenCalledWith(engineB);
  });

  test('invalidateSession 会 abort 当前页面请求并使 generation 失效', () => {
    const client = new RTCClient();
    const generation = client.beginSession();
    const signal = client.getSessionSignal(generation);

    client.invalidateSession(generation);

    expect(signal.aborted).toBe(true);
    expect(client.isSessionCurrent(generation)).toBe(false);
  });

  test('resetRtcSession 清空 scene、RTC 配置和用户房间状态', () => {
    let state = roomReducer(undefined, { type: 'init' });
    state = roomReducer(state, updateScene('scene-1'));
    state = roomReducer(state, updateSceneConfig({ 'scene-1': { id: 'scene-1' } } as any));
    state = roomReducer(
      state,
      updateRTCConfig({
        'scene-1': { AppId: 'app', RoomId: 'room', UserId: 'user', Token: 'secret-token' },
      })
    );
    state = roomReducer(
      state,
      localJoinRoom({ roomId: 'room', user: { username: 'user', userId: 'user' } })
    );

    state = roomReducer(state, resetRtcSession());

    expect(state.scene).toBe('');
    expect(state.sceneConfigMap).toEqual({});
    expect(state.rtcConfigMap).toEqual({});
    expect(state.roomId).toBeUndefined();
    expect(state.isJoined).toBe(false);
  });

  test('stopAgent 将 AbortSignal 传给 StopVoiceChat 且失败也重置 bot 状态', async () => {
    const client = new RTCClient();
    client.audioBotEnabled = true;
    client.audioBotStartTime = 100;
    mockStopVoiceChat.mockRejectedValueOnce(new Error('stop failed'));
    const signal = new AbortController().signal;

    await expect(client.stopAgent('scene-1', signal)).rejects.toThrow('stop failed');

    expect(mockStopVoiceChat).toHaveBeenCalledWith({ SceneID: 'scene-1' }, { signal });
    expect(client.audioBotEnabled).toBe(false);
    expect(client.audioBotStartTime).toBe(0);
  });

  test('session 同步失效后仍按 ownership 停止旧 Agent', async () => {
    const client = new RTCClient();
    client.audioBotEnabled = true;
    const ownership = client.captureEngineOwnership();
    const signal = new AbortController().signal;

    client.invalidateSession(ownership.sessionGeneration);
    await client.stopAgent('scene-old', signal, ownership);

    expect(mockStopVoiceChat).toHaveBeenCalledWith({ SceneID: 'scene-old' }, { signal });
  });

  test('engine 尚未创建时 leaveRoom 安全返回', async () => {
    const client = new RTCClient();

    await expect(client.leaveRoom()).resolves.toBeUndefined();
  });

  test('joinRoom 日志不包含 RTC Token', () => {
    const client = new RTCClient();
    const secretToken = 'unique-secret-rtc-token';
    client.basicInfo = {
      app_id: 'app',
      room_id: 'room',
      user_id: 'user',
      token: secretToken,
    };
    client.engine = { joinRoom: jest.fn() } as any;
    const consoleLog = jest.spyOn(console, 'log').mockImplementation(() => {});

    client.joinRoom();

    expect(consoleLog.mock.calls.flat().join(' ')).not.toContain(secretToken);
    consoleLog.mockRestore();
  });

  test('旧 cleanup 恢复后只销毁捕获的旧 engine，不影响新 engine', async () => {
    const client = new RTCClient();
    let finishOldLeave!: () => void;
    const oldEngine = {
      leaveRoom: jest.fn(
        () =>
          new Promise<void>((resolve) => {
            finishOldLeave = resolve;
          })
      ),
    } as any;
    const newEngine = {
      leaveRoom: jest.fn<Promise<void>, []>().mockResolvedValue(undefined),
    } as any;
    client.engine = oldEngine;
    const ownership = client.captureEngineOwnership();

    const oldCleanup = client.leaveRoom(ownership);
    client.engine = newEngine;
    finishOldLeave();
    await oldCleanup;

    expect(mockDestroyEngine).toHaveBeenCalledWith(oldEngine);
    expect(mockDestroyEngine).not.toHaveBeenCalledWith(newEngine);
    expect(client.engine).toBe(newEngine);
  });

  test('旧 engine 事件失效且解绑，新 engine 事件正常转发', async () => {
    const client = new RTCClient();
    const eventHandlers = new Map<string, (...args: any[]) => void>();
    const oldEngine = {
      on: jest.fn((event: string, handler: (...args: any[]) => void) =>
        eventHandlers.set(event, handler)
      ),
      off: jest.fn(),
      leaveRoom: jest.fn<Promise<void>, []>().mockResolvedValue(undefined),
    } as any;
    client.engine = oldEngine;
    const oldOwnership = client.captureEngineOwnership();
    const oldUserJoin = jest.fn();
    const listeners = {
      handleError: jest.fn(),
      handleUserJoin: oldUserJoin,
      handleUserLeave: jest.fn(),
      handleTrackEnded: jest.fn(),
      handleUserPublishStream: jest.fn(),
      handleUserUnpublishStream: jest.fn(),
      handleRemoteStreamStats: jest.fn(),
      handleLocalStreamStats: jest.fn(),
      handleLocalAudioPropertiesReport: jest.fn(),
      handleRemoteAudioPropertiesReport: jest.fn(),
      handleAudioDeviceStateChanged: jest.fn(),
      handleAutoPlayFail: jest.fn(),
      handlePlayerEvent: jest.fn(),
      handleRoomBinaryMessageReceived: jest.fn(),
      handleNetworkQuality: jest.fn(),
    } as any;
    client.addEventListeners(listeners, oldOwnership);
    eventHandlers.get('onUserJoined')?.({ userId: 'old-current' });
    expect(oldUserJoin).toHaveBeenCalledTimes(1);

    client.invalidateSession(oldOwnership.sessionGeneration);
    eventHandlers.get('onUserJoined')?.({ userId: 'old-stale' });
    expect(oldUserJoin).toHaveBeenCalledTimes(1);
    await client.leaveRoom(oldOwnership);
    expect(oldEngine.off).toHaveBeenCalled();

    const newEventHandlers = new Map<string, (...args: any[]) => void>();
    const newEngine = {
      on: jest.fn((event: string, handler: (...args: any[]) => void) =>
        newEventHandlers.set(event, handler)
      ),
    } as any;
    client.engine = newEngine;
    const newOwnership = client.captureEngineOwnership();
    const newUserJoin = jest.fn();
    client.addEventListeners({ ...listeners, handleUserJoin: newUserJoin }, newOwnership);
    newEventHandlers.get('onUserJoined')?.({ userId: 'new-current' });
    expect(newUserJoin).toHaveBeenCalledTimes(1);
  });
});

describe('AuthUserActions', () => {
  test('显示规范化用户名和退出按钮', () => {
    render(<AuthUserActions />);

    expect(screen.getByText('alice')).toBeTruthy();
    expect(screen.getByRole('button', { name: '退出登录' })).toBeTruthy();
  });

  test.each([
    ['清理成功', () => mockLeaveRoom.mockResolvedValue(undefined)],
    ['清理失败', () => mockLeaveRoom.mockRejectedValue(new Error('cleanup failed'))],
  ])('%s后仍调用 logout', async (_, arrange) => {
    arrange();
    render(<AuthUserActions />);
    const button = screen.getByRole('button', { name: '退出登录' });

    await userEvent.click(button);

    await waitFor(() => expect(mockLogout).toHaveBeenCalledTimes(1));
  });

  test('提交期间退出按钮禁用', async () => {
    mockLogout.mockReturnValue(new Promise(() => {}));
    render(<AuthUserActions />);

    await userEvent.click(screen.getByRole('button', { name: '退出登录' }));

    expect(screen.getByRole('button', { name: '退出登录' }).hasAttribute('disabled')).toBe(true);
  });

  test('整个清理超过 3 秒时 abort 并调用 logout', async () => {
    jest.useFakeTimers();
    mockLeaveRoom.mockReturnValue(new Promise(() => {}));
    render(<AuthUserActions />);

    act(() => screen.getByRole('button', { name: '退出登录' }).click());
    const signal = mockLeaveRoom.mock.calls[0][0];
    expect(signal?.aborted).toBe(false);
    await act(async () => {
      jest.advanceTimersByTime(3000);
      await Promise.resolve();
    });

    expect(signal?.aborted).toBe(true);
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  test('未入房时也执行有界 reset/leave 再 logout', async () => {
    render(<AuthUserActions />);

    await userEvent.click(screen.getByRole('button', { name: '退出登录' }));

    expect(mockLeaveRoom).toHaveBeenCalledTimes(1);
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  test('logout 拒绝时 onClick 边界吸收异常并恢复按钮', async () => {
    mockLogout.mockRejectedValueOnce(new Error('logout failed'));
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    render(<AuthUserActions />);

    await userEvent.click(screen.getByRole('button', { name: '退出登录' }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: '退出登录' }).hasAttribute('disabled')).toBe(false)
    );
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
