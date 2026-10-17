/* eslint-disable import/first */
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';
import React from 'react';
import { Message } from '@arco-design/web-react';

const mockStopAgent = jest.fn<Promise<void>, [string, AbortSignal?]>();
const mockStopAudioCapture = jest.fn<Promise<void>, []>();
const mockStopScreenCapture = jest.fn<Promise<void>, []>();
const mockStopVideoCapture = jest.fn<Promise<void>, []>();
const mockRtcLeaveRoom = jest.fn<Promise<void>, []>();
const mockDispatch = jest.fn<void, [any]>();
const mockCreateEngine = jest.fn<
  Promise<{ engine: object; engineGeneration: number; sessionGeneration: number }>,
  []
>();
const mockJoinRoom = jest.fn<Promise<void>, [unknown]>();
const mockStartAgent = jest.fn<Promise<void>, [string, number?]>();
const mockResetBasicInfo = jest.fn<void, []>();
let mockGeneration = 1;

function mockStopAgentProxy(...args: any[]) {
  return mockStopAgent(args[0], args[1]);
}

function mockStopAudioCaptureProxy() {
  return mockStopAudioCapture();
}

function mockStopScreenCaptureProxy() {
  return mockStopScreenCapture();
}

function mockStopVideoCaptureProxy() {
  return mockStopVideoCapture();
}

function mockRtcLeaveRoomProxy() {
  return mockRtcLeaveRoom();
}

function mockResetBasicInfoProxy() {
  return mockResetBasicInfo();
}

jest.mock('./pages/MainPage', () => {
  const React = require('react');
  return function MockMainPage() {
    React.useEffect(() => {
      fetch('/getScenes', { method: 'POST', credentials: 'include' });
    }, []);
    return <div>RTC MainPage</div>;
  };
});
jest.mock(
  '@/lib/RtcClient',
  () => ({
    __esModule: true,
    default: {
      stopAgent: mockStopAgentProxy,
      stopAudioCapture: mockStopAudioCaptureProxy,
      stopScreenCapture: mockStopScreenCaptureProxy,
      stopVideoCapture: mockStopVideoCaptureProxy,
      leaveRoom: mockRtcLeaveRoomProxy,
      captureEngineOwnership: () => ({
        engine: {},
        engineGeneration: 1,
        sessionGeneration: mockGeneration,
      }),
      invalidateSession: () => {
        mockGeneration += 1;
      },
      beginSession: () => {
        mockGeneration += 1;
        return mockGeneration;
      },
      resetBasicInfo: mockResetBasicInfoProxy,
      getSessionGeneration: () => mockGeneration,
      isSessionCurrent: (generation: number) => generation === mockGeneration,
      createEngine: () => mockCreateEngine(),
      addEventListeners: () => undefined,
      joinRoom: (ownership: unknown) => mockJoinRoom(ownership),
      getDevices: () => Promise.resolve({ audioInputs: [], audioOutputs: [], videoInputs: [] }),
      publishStream: () => undefined,
      startAudioCapture: () => Promise.resolve(),
      startAgent: (scene: string, generation?: number) => mockStartAgent(scene, generation),
      basicInfo: { room_id: 'room', user_id: 'user' },
    },
  }),
  { virtual: true }
);
jest.mock('react-redux', () => ({
  useDispatch: () => mockDispatch,
  useSelector: (selector: any) =>
    selector({
      room: { scene: 'scene-1', sceneConfigMap: { 'scene-1': { id: 'scene-1' } } },
      device: { devicePermissions: { audio: true } },
    }),
}));
jest.mock('@/lib/listenerHooks', () => ({ __esModule: true, default: () => ({}) }), {
  virtual: true,
});
jest.mock(
  '@/store/slices/room',
  () => ({
    clearCurrentMsg: () => ({ type: 'clearCurrentMsg' }),
    clearHistoryMsg: () => ({ type: 'clearHistoryMsg' }),
    localLeaveRoom: () => ({ type: 'localLeaveRoom' }),
    resetRtcSession: () => ({ type: 'resetRtcSession' }),
    localJoinRoom: () => ({ type: 'localJoinRoom' }),
    updateAIGCState: () => ({ type: 'updateAIGCState' }),
    updateLocalUser: () => ({ type: 'updateLocalUser' }),
  }),
  { virtual: true }
);
jest.mock(
  '@/store/slices/device',
  () => ({
    updateMediaInputs: () => ({}),
    updateSelectedDevice: () => ({}),
    setDevicePermissions: () => ({}),
  }),
  { virtual: true }
);
jest.mock('@/utils/logger', () => ({ __esModule: true, default: { debug: () => undefined } }), {
  virtual: true,
});
jest.mock('@volcengine/rtc', () => ({
  __esModule: true,
  default: { isSupported: () => Promise.resolve(true) },
  MediaType: { AUDIO: 1, VIDEO: 2 },
}));

import App from './App';
import { useJoin, useLeave } from './lib/useCommon';

const fetchMock = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>();
const response = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

beforeEach(() => {
  jest.spyOn(console, 'warn').mockImplementation(() => {});
  fetchMock.mockReset();
  global.fetch = fetchMock;
  mockDispatch.mockReset();
  mockStopAgent.mockReset().mockResolvedValue(undefined);
  mockStopAudioCapture.mockReset().mockResolvedValue(undefined);
  mockStopScreenCapture.mockReset().mockResolvedValue(undefined);
  mockStopVideoCapture.mockReset().mockResolvedValue(undefined);
  mockRtcLeaveRoom.mockReset().mockResolvedValue(undefined);
  mockGeneration = 1;
  mockCreateEngine.mockReset().mockResolvedValue({
    engine: {},
    engineGeneration: 1,
    sessionGeneration: 1,
  });
  mockJoinRoom.mockReset().mockResolvedValue(undefined);
  mockStartAgent.mockReset().mockResolvedValue(undefined);
  mockResetBasicInfo.mockReset();
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

describe('useLeave cleanup', () => {
  test('误传的点击事件不会被当作 AbortSignal 传给 StopVoiceChat', async () => {
    const clickEvent = { type: 'click' } as unknown as AbortSignal;
    const { result } = renderHook(() => useLeave());

    await act(async () => {
      await result.current(clickEvent);
    });

    expect(mockStopAgent).toHaveBeenCalledWith('scene-1', undefined);
    expect(mockResetBasicInfo).not.toHaveBeenCalled();
  });

  test('Stop 失败仍停止所有设备、离房并清理 Redux，且透传 AbortSignal', async () => {
    mockStopAgent.mockRejectedValueOnce(new Error('stop failed'));
    mockStopAudioCapture.mockRejectedValueOnce(new Error('audio failed'));
    const signal = new AbortController().signal;
    const { result } = renderHook(() => useLeave());

    await act(async () => {
      await expect(result.current(signal)).rejects.toThrow('stop failed');
    });

    expect(mockStopAgent).toHaveBeenCalledWith('scene-1', signal);
    expect(mockStopAudioCapture).toHaveBeenCalledTimes(1);
    expect(mockStopScreenCapture).toHaveBeenCalledTimes(1);
    expect(mockStopVideoCapture).toHaveBeenCalledTimes(1);
    expect(mockRtcLeaveRoom).toHaveBeenCalledTimes(1);
    expect(mockResetBasicInfo).toHaveBeenCalledTimes(1);
    expect(mockDispatch.mock.calls.map(([action]) => action.type)).toEqual(['resetRtcSession']);
  });

  test('join 进行中退出会使旧 join 失效，恢复后不写 Redux 或启动 VoiceChat', async () => {
    let finishJoin!: () => void;
    mockJoinRoom.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishJoin = resolve;
      })
    );
    const { result } = renderHook(() => {
      const [joining, join] = useJoin();
      const leave = useLeave();
      return { joining, join, leave };
    });

    let joinPromise!: Promise<void | boolean>;
    await act(async () => {
      joinPromise = result.current.join();
      await Promise.resolve();
    });
    expect(mockJoinRoom).toHaveBeenCalledTimes(1);
    await act(async () => {
      await result.current.leave(new AbortController().signal);
      finishJoin();
      await joinPromise;
    });

    expect(mockStartAgent).not.toHaveBeenCalled();
    expect(result.current.joining).toBe(false);
    expect(mockDispatch.mock.calls.map(([action]) => action.type)).toEqual(['resetRtcSession']);
  });

  test('日常 leave 打断 pending join 后恢复 joining 并保持可再次加入', async () => {
    let finishJoin!: () => void;
    mockJoinRoom.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishJoin = resolve;
      })
    );
    const { result } = renderHook(() => {
      const [joining, join] = useJoin();
      const leave = useLeave();
      return { joining, join, leave };
    });

    let joinPromise!: Promise<void | boolean>;
    await act(async () => {
      joinPromise = result.current.join();
      await Promise.resolve();
      await result.current.leave();
      finishJoin();
      await joinPromise;
    });

    expect(result.current.joining).toBe(false);
    expect(mockStartAgent).not.toHaveBeenCalled();
    expect(mockDispatch.mock.calls.map(([action]) => action.type)).toEqual([
      'clearHistoryMsg',
      'clearCurrentMsg',
      'localLeaveRoom',
      'updateAIGCState',
    ]);
  });

  test('joinRoom reject 会关闭 owned engine、恢复 joining 且不向事件边界抛错', async () => {
    const secretToken = '001-secret-rtc-token';
    const joinError = Object.assign(new Error(`token invalid: ${secretToken}`), {
      code: 'INVALID_TOKEN',
    });
    mockJoinRoom.mockRejectedValueOnce(joinError);
    const messageError = jest.spyOn(Message, 'error').mockImplementation(() => undefined as any);
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    const { result } = renderHook(() => useJoin());

    await act(async () => {
      await expect(result.current[1]()).resolves.toBe(false);
    });

    expect(mockRtcLeaveRoom).toHaveBeenCalledTimes(1);
    expect(result.current[0]).toBe(false);
    expect(mockDispatch).not.toHaveBeenCalled();
    expect(messageError).toHaveBeenCalledWith('RTC joinRoom 失败：INVALID_TOKEN');
    expect(consoleError).toHaveBeenCalledWith('[RTC 通话失败]', {
      stage: 'joinRoom',
      code: 'INVALID_TOKEN',
      message: 'token invalid: [REDACTED]',
    });
    expect(JSON.stringify(consoleError.mock.calls)).not.toContain(secretToken);
  });

  test('StartVoiceChat reject 会关闭 owned engine并恢复 joining', async () => {
    const startError = Object.assign(new Error('upstream rejected'), {
      status: 502,
    });
    mockStartAgent.mockRejectedValueOnce(startError);
    const messageError = jest.spyOn(Message, 'error').mockImplementation(() => undefined as any);
    jest.spyOn(console, 'error').mockImplementation(() => {});
    const { result } = renderHook(() => useJoin());

    await act(async () => {
      await expect(result.current[1]()).resolves.toBe(false);
    });

    expect(mockRtcLeaveRoom).toHaveBeenCalledTimes(1);
    expect(result.current[0]).toBe(false);
    expect(mockDispatch).not.toHaveBeenCalled();
    expect(messageError).toHaveBeenCalledWith('RTC StartVoiceChat 失败：502');
  });

  test('joinRoom 长时间无结果时显示 JOIN_TIMEOUT 并关闭 owned engine', async () => {
    jest.useFakeTimers();
    mockJoinRoom.mockReturnValueOnce(new Promise<void>(() => undefined));
    const messageError = jest.spyOn(Message, 'error').mockImplementation(() => undefined as any);
    jest.spyOn(console, 'error').mockImplementation(() => {});
    const { result } = renderHook(() => useJoin());

    await act(async () => {
      void result.current[1]();
      await Promise.resolve();
    });
    await act(async () => {
      jest.advanceTimersByTime(15_000);
      await Promise.resolve();
    });

    expect(messageError).toHaveBeenCalledWith('RTC joinRoom 失败：JOIN_TIMEOUT');
    expect(mockRtcLeaveRoom).toHaveBeenCalledTimes(1);
    expect(result.current[0]).toBe(false);
    jest.useRealTimers();
  });
});

describe('App auth gate', () => {
  test('未登录显示登录页且不挂载 MainPage/getScenes', async () => {
    fetchMock.mockImplementationOnce(() => response({ detail: '请先登录' }, 401));
    render(<App />);

    expect(await screen.findByRole('button', { name: '登录' })).toBeTruthy();
    expect(screen.queryByText('RTC MainPage')).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/getScenes'))).toBe(false);
  });

  test('登录成功后挂载 MainPage 并请求 getScenes', async () => {
    fetchMock
      .mockImplementationOnce(() => response({ detail: '请先登录' }, 401))
      .mockImplementationOnce(() => response({ user: { id: 1, username: 'alice' } }))
      .mockImplementationOnce(() => response({ ok: true }));
    render(<App />);
    await screen.findByRole('button', { name: '登录' });

    await userEvent.type(screen.getByLabelText('用户名'), 'alice');
    await userEvent.type(screen.getByLabelText('密码'), 'secret12');
    await userEvent.click(screen.getByRole('button', { name: '登录' }));

    expect(await screen.findByText('RTC MainPage')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/getScenes'))).toBe(true);
  });

  test('认证检查期间显示加载状态', () => {
    fetchMock.mockReturnValueOnce(new Promise(() => {}));
    render(<App />);

    expect(screen.getByText('正在检查登录状态…')).toBeTruthy();
  });

  test('认证网络错误显示重试按钮，点击后重新检查', async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError('network failed'))
      .mockImplementationOnce(() => response({ detail: '请先登录' }, 401));
    render(<App />);

    await userEvent.click(await screen.findByRole('button', { name: '重试' }));

    await waitFor(() => expect(screen.getByRole('button', { name: '登录' })).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
