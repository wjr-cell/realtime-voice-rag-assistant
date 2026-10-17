/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import VERTC, {
  MirrorType,
  StreamIndex,
  IRTCEngine,
  RoomProfileType,
  onUserJoinedEvent,
  onUserLeaveEvent,
  MediaType,
  LocalStreamStats,
  RemoteStreamStats,
  StreamRemoveReason,
  LocalAudioPropertiesInfo,
  RemoteAudioPropertiesInfo,
  AudioProfileType,
  DeviceInfo,
  AutoPlayFailedEvent,
  PlayerEvent,
  NetworkQuality,
  VideoRenderMode,
  ScreenEncoderConfig,
} from '@volcengine/rtc';
import RTCAIAnsExtension from '@volcengine/rtc/extension-ainr';
import { Message } from '@arco-design/web-react';
import Apis from '@/app/index';
import { string2tlv } from '@/utils/utils';
import { COMMAND, INTERRUPT_PRIORITY } from '@/utils/handler';

export interface IEventListener {
  handleError: (e: { errorCode: any }) => void;
  handleUserJoin: (e: onUserJoinedEvent) => void;
  handleUserLeave: (e: onUserLeaveEvent) => void;
  handleTrackEnded: (e: { kind: string; isScreen: boolean }) => void;
  handleUserPublishStream: (e: { userId: string; mediaType: MediaType }) => void;
  handleUserUnpublishStream: (e: {
    userId: string;
    mediaType: MediaType;
    reason: StreamRemoveReason;
  }) => void;
  handleRemoteStreamStats: (e: RemoteStreamStats) => void;
  handleLocalStreamStats: (e: LocalStreamStats) => void;
  handleLocalAudioPropertiesReport: (e: LocalAudioPropertiesInfo[]) => void;
  handleRemoteAudioPropertiesReport: (e: RemoteAudioPropertiesInfo[]) => void;
  handleAudioDeviceStateChanged: (e: DeviceInfo) => void;
  handleAutoPlayFail: (e: AutoPlayFailedEvent) => void;
  handlePlayerEvent: (e: PlayerEvent) => void;
  handleRoomBinaryMessageReceived: (e: { userId: string; message: ArrayBuffer }) => void;
  handleNetworkQuality: (
    uplinkNetworkQuality: NetworkQuality,
    downlinkNetworkQuality: NetworkQuality
  ) => void;
}

export interface BasicBody {
  app_id: string;
  room_id: string;
  user_id: string;
  token?: string;
}

export interface EngineOwnership {
  engine?: IRTCEngine;
  engineGeneration: number;
  sessionGeneration: number;
  agentEnabled: boolean;
}

/**
 * @brief RTC Core Client
 * @notes Refer to official website documentation to get more information about the API.
 */
export class RTCClient {
  engine!: IRTCEngine;

  basicInfo!: BasicBody;

  private _audioCaptureDevice?: string;

  private _videoCaptureDevice?: string;

  audioBotEnabled = false;

  audioBotStartTime = 0;

  private engineGeneration = 0;

  private sessionGeneration = 0;

  private sessionController = new AbortController();

  private closingEngines = new WeakSet<IRTCEngine>();

  private engineListeners = new WeakMap<IRTCEngine, Array<[string, (...args: any[]) => void]>>();

  beginSession = () => {
    this.sessionController.abort();
    this.sessionController = new AbortController();
    this.sessionGeneration += 1;
    return this.sessionGeneration;
  };

  getSessionGeneration = () => this.sessionGeneration;

  isSessionCurrent = (generation: number) => generation === this.sessionGeneration;

  getSessionSignal = (generation: number) => {
    if (this.isSessionCurrent(generation)) return this.sessionController.signal;
    const controller = new AbortController();
    controller.abort();
    return controller.signal;
  };

  invalidateSession = (generation?: number) => {
    if (generation !== undefined && !this.isSessionCurrent(generation)) return;
    this.sessionController.abort();
    this.sessionGeneration += 1;
    this.audioBotEnabled = false;
    this.audioBotStartTime = 0;
    sessionStorage.removeItem('audioBotEnabled');
  };

  resetBasicInfo = () => {
    this.basicInfo = undefined as unknown as BasicBody;
  };

  captureEngineOwnership = (): EngineOwnership => ({
    engine: this.engine,
    engineGeneration: this.engineGeneration,
    sessionGeneration: this.sessionGeneration,
    agentEnabled: this.audioBotEnabled || Boolean(sessionStorage.getItem('audioBotEnabled')),
  });

  private isOwnershipCurrent = (ownership: EngineOwnership) =>
    ownership.engine === this.engine &&
    ownership.engineGeneration === this.engineGeneration &&
    this.isSessionCurrent(ownership.sessionGeneration);

  createEngine = async () => {
    const sessionGeneration = this.sessionGeneration;
    const engine = VERTC.createEngine(this.basicInfo.app_id);
    const engineGeneration = this.engineGeneration + 1;
    const ownership: EngineOwnership = {
      engine,
      engineGeneration,
      sessionGeneration,
      agentEnabled: this.audioBotEnabled || Boolean(sessionStorage.getItem('audioBotEnabled')),
    };
    this.engine = engine;
    this.engineGeneration = engineGeneration;
    try {
      const AIAnsExtension = new RTCAIAnsExtension();
      await engine.registerExtension(AIAnsExtension);
      AIAnsExtension.enable();
    } catch (error) {
      console.warn(
        `当前环境不支持 AI 降噪, 此错误可忽略, 不影响实际使用, e: ${(error as any).message}`
      );
    }
    if (!this.isOwnershipCurrent(ownership)) await this.leaveRoom(ownership);
    return ownership;
  };

  addEventListeners = (
    {
      handleError,
      handleUserJoin,
      handleUserLeave,
      handleTrackEnded,
      handleUserPublishStream,
      handleUserUnpublishStream,
      handleRemoteStreamStats,
      handleLocalStreamStats,
      handleLocalAudioPropertiesReport,
      handleRemoteAudioPropertiesReport,
      handleAudioDeviceStateChanged,
      handleAutoPlayFail,
      handlePlayerEvent,
      handleRoomBinaryMessageReceived,
      handleNetworkQuality,
    }: IEventListener,
    ownership = this.captureEngineOwnership()
  ) => {
    const engine = ownership.engine;
    if (!engine) return;
    const listeners: Array<[string, (...args: any[]) => void]> = [];
    const add = (event: string, handler: (...args: any[]) => void) => {
      const guarded = (...args: any[]) => {
        if (this.isOwnershipCurrent(ownership)) handler(...args);
      };
      listeners.push([event, guarded]);
      engine.on(event as any, guarded);
    };
    add(VERTC.events.onError, handleError);
    add(VERTC.events.onUserJoined, handleUserJoin);
    add(VERTC.events.onUserLeave, handleUserLeave);
    add(VERTC.events.onTrackEnded, handleTrackEnded);
    add(VERTC.events.onUserPublishStream, handleUserPublishStream);
    add(VERTC.events.onUserUnpublishStream, handleUserUnpublishStream);
    add(VERTC.events.onRemoteStreamStats, handleRemoteStreamStats);
    add(VERTC.events.onLocalStreamStats, handleLocalStreamStats);
    add(VERTC.events.onAudioDeviceStateChanged, handleAudioDeviceStateChanged);
    add(VERTC.events.onLocalAudioPropertiesReport, handleLocalAudioPropertiesReport);
    add(VERTC.events.onRemoteAudioPropertiesReport, handleRemoteAudioPropertiesReport);
    add(VERTC.events.onAutoplayFailed, handleAutoPlayFail);
    add(VERTC.events.onPlayerEvent, handlePlayerEvent);
    add(VERTC.events.onRoomBinaryMessageReceived, handleRoomBinaryMessageReceived);
    add(VERTC.events.onNetworkQuality, handleNetworkQuality);
    this.engineListeners.set(engine, listeners);
  };

  joinRoom = (ownership = this.captureEngineOwnership()) => {
    console.log(
      ' ------ userJoinRoom\n',
      `roomId: ${this.basicInfo.room_id}\n`,
      `uid: ${this.basicInfo.user_id}`
    );
    console.log(
      ' ------ joinRoom\n',
      `roomId: ${this.basicInfo.room_id}\n`,
      `uid: ${this.basicInfo.user_id}`
    );
    if (!ownership.engine) return Promise.resolve();
    return ownership.engine.joinRoom(
      this.basicInfo.token!,
      `${this.basicInfo.room_id!}`,
      {
        userId: this.basicInfo.user_id!,
        extraInfo: JSON.stringify({
          call_scene: 'RTC-AIGC',
          user_name: this.basicInfo.user_id,
          user_id: this.basicInfo.user_id,
        }),
      },
      {
        isAutoPublish: true,
        isAutoSubscribeAudio: true,
        roomProfileType: RoomProfileType.chat,
      }
    );
  };

  leaveRoom = async (ownership = this.captureEngineOwnership()) => {
    const targetEngine = ownership.engine;
    if (!targetEngine || this.closingEngines.has(targetEngine)) return;
    this.closingEngines.add(targetEngine);
    this.engineListeners.get(targetEngine)?.forEach(([event, listener]) => {
      targetEngine.off?.(event as any, listener);
    });
    this.engineListeners.delete(targetEngine);
    try {
      await targetEngine.leaveRoom();
    } finally {
      VERTC.destroyEngine(targetEngine);
      if (this.engine === targetEngine) {
        this.engine = undefined as unknown as IRTCEngine;
        this._audioCaptureDevice = undefined;
      }
    }
  };

  checkPermission(): Promise<{
    video: boolean;
    audio: boolean;
  }> {
    return VERTC.enableDevices({
      video: false,
      audio: true,
    });
  }

  /**
   * @brief get the devices
   * @returns
   */
  async getDevices(props?: { video?: boolean; audio?: boolean }): Promise<{
    audioInputs: MediaDeviceInfo[];
    audioOutputs: MediaDeviceInfo[];
    videoInputs: MediaDeviceInfo[];
  }> {
    const { video = false, audio = true } = props || {};
    let audioInputs: MediaDeviceInfo[] = [];
    let audioOutputs: MediaDeviceInfo[] = [];
    let videoInputs: MediaDeviceInfo[] = [];
    const { video: hasVideoPermission, audio: hasAudioPermission } = await VERTC.enableDevices({
      video,
      audio,
    });
    if (audio) {
      const inputs = await VERTC.enumerateAudioCaptureDevices();
      const outputs = await VERTC.enumerateAudioPlaybackDevices();
      audioInputs = inputs.filter((i) => i.deviceId && i.kind === 'audioinput');
      audioOutputs = outputs.filter((i) => i.deviceId && i.kind === 'audiooutput');
      this._audioCaptureDevice = audioInputs.filter((i) => i.deviceId)?.[0]?.deviceId;
      if (hasAudioPermission) {
        if (!audioInputs?.length) {
          Message.error('无麦克风设备, 请先确认设备情况。');
        }
        if (!audioOutputs?.length) {
          Message.error('无扬声器设备, 请先确认设备情况。');
        }
      } else {
        Message.error('暂无麦克风设备权限, 请先确认设备权限授予情况。');
      }
    }
    if (video) {
      videoInputs = await VERTC.enumerateVideoCaptureDevices();
      videoInputs = videoInputs.filter((i) => i.deviceId && i.kind === 'videoinput');
      this._videoCaptureDevice = videoInputs?.[0]?.deviceId;
      if (hasVideoPermission) {
        if (!videoInputs?.length) {
          Message.error('无摄像头设备, 请先确认设备情况。');
        }
      } else {
        Message.error('暂无摄像头设备权限, 请先确认设备权限授予情况。');
      }
    }

    return {
      audioInputs,
      audioOutputs,
      videoInputs,
    };
  }

  startVideoCapture = async (camera?: string) => {
    await this.engine.startVideoCapture(camera || this._videoCaptureDevice);
  };

  stopVideoCapture = async (ownership = this.captureEngineOwnership()) => {
    const engine = ownership.engine;
    if (!engine) return;
    engine.setLocalVideoMirrorType(MirrorType.MIRROR_TYPE_RENDER);
    await engine.stopVideoCapture();
  };

  startScreenCapture = async (enableAudio = false) => {
    await this.engine.startScreenCapture({
      enableAudio,
    });
  };

  stopScreenCapture = async (ownership = this.captureEngineOwnership()) => {
    await ownership.engine?.stopScreenCapture();
  };

  startAudioCapture = async (mic?: string, ownership = this.captureEngineOwnership()) => {
    await ownership.engine?.startAudioCapture(mic || this._audioCaptureDevice);
  };

  stopAudioCapture = async (ownership = this.captureEngineOwnership()) => {
    await ownership.engine?.stopAudioCapture();
  };

  publishStream = (mediaType: MediaType, ownership = this.captureEngineOwnership()) => {
    // RTC你准备开始听完说话
    console.log('publishStream 我说话了。。。', mediaType);

    ownership.engine?.publishStream(mediaType);
  };

  unpublishStream = (mediaType: MediaType) => {
    this.engine.unpublishStream(mediaType);
  };

  publishScreenStream = async (mediaType: MediaType) => {
    await this.engine.publishScreen(mediaType);
  };

  unpublishScreenStream = async (mediaType: MediaType) => {
    await this.engine.unpublishScreen(mediaType);
  };

  setScreenEncoderConfig = async (description: ScreenEncoderConfig) => {
    await this.engine.setScreenEncoderConfig(description);
  };

  /**
   * @brief 设置业务标识参数
   * @param businessId
   */
  setBusinessId = (businessId: string) => {
    this.engine.setBusinessId(businessId);
  };

  setAudioVolume = (volume: number) => {
    this.engine.setCaptureVolume(StreamIndex.STREAM_INDEX_MAIN, volume);
    this.engine.setCaptureVolume(StreamIndex.STREAM_INDEX_SCREEN, volume);
  };

  /**
   * @brief 设置音质档位
   */
  setAudioProfile = (profile: AudioProfileType) => {
    this.engine.setAudioProfile(profile);
  };

  /**
   * @brief 切换设备
   */
  switchDevice = (deviceType: MediaType, deviceId: string) => {
    if (deviceType === MediaType.AUDIO) {
      this._audioCaptureDevice = deviceId;
      this.engine.setAudioCaptureDevice(deviceId);
    }
    if (deviceType === MediaType.VIDEO) {
      this._videoCaptureDevice = deviceId;
      this.engine.setVideoCaptureDevice(deviceId);
    }
    if (deviceType === MediaType.AUDIO_AND_VIDEO) {
      this._audioCaptureDevice = deviceId;
      this._videoCaptureDevice = deviceId;
      this.engine.setVideoCaptureDevice(deviceId);
      this.engine.setAudioCaptureDevice(deviceId);
    }
  };

  setLocalVideoMirrorType = (type: MirrorType) => {
    return this.engine.setLocalVideoMirrorType(type);
  };

  setLocalVideoPlayer = (
    userId: string,
    renderDom?: string | HTMLElement,
    isScreenShare = false,
    renderMode = VideoRenderMode.RENDER_MODE_FILL
  ) => {
    return this.engine.setLocalVideoPlayer(
      isScreenShare ? StreamIndex.STREAM_INDEX_SCREEN : StreamIndex.STREAM_INDEX_MAIN,
      {
        renderDom,
        userId,
        renderMode,
      }
    );
  };

  setRemoteVideoPlayer = (
    userId: string,
    renderDom?: string | HTMLElement,
    renderMode = VideoRenderMode.RENDER_MODE_HIDDEN
  ) => {
    return this.engine.setRemoteVideoPlayer(StreamIndex.STREAM_INDEX_MAIN, {
      renderDom,
      userId,
      renderMode,
    });
  };

  /**
   * @brief 移除播放器
   */
  removeLocalVideoPlayer = (userId: string, scope: StreamIndex | 'Both' = 'Both') => {
    let removeScreen = scope === StreamIndex.STREAM_INDEX_SCREEN;
    let removeCamera = scope === StreamIndex.STREAM_INDEX_MAIN;
    if (scope === 'Both') {
      removeCamera = true;
      removeScreen = true;
    }
    if (removeScreen) {
      this.engine.setLocalVideoPlayer(StreamIndex.STREAM_INDEX_SCREEN, { userId });
    }
    if (removeCamera) {
      this.engine.setLocalVideoPlayer(StreamIndex.STREAM_INDEX_MAIN, { userId });
    }
  };

  /**
   * @brief 启用 AIGC
   */
  startAgent = async (scene: string, generation?: number) => {
    if (this.audioBotEnabled) {
      await this.stopAgent(scene);
    }
    const params = { SceneID: scene };
    await (generation === undefined
      ? Apis.VoiceChat.StartVoiceChat(params)
      : Apis.VoiceChat.StartVoiceChat(params, {
          signal: this.getSessionSignal(generation),
        }));
    if (generation !== undefined && !this.isSessionCurrent(generation)) return;
    this.audioBotEnabled = true;
    this.audioBotStartTime = Date.now();
  };

  /**
   * @brief 关闭 AIGC
   */
  stopAgent = async (
    scene: string,
    signal?: AbortSignal,
    ownership = this.captureEngineOwnership()
  ) => {
    try {
      if (ownership.agentEnabled) {
        const params = { SceneID: scene };
        await (signal
          ? Apis.VoiceChat.StopVoiceChat(params, { signal })
          : Apis.VoiceChat.StopVoiceChat(params));
      }
    } finally {
      if (this.isSessionCurrent(ownership.sessionGeneration)) {
        this.audioBotStartTime = 0;
        sessionStorage.removeItem('audioBotEnabled');
        this.audioBotEnabled = false;
      }
    }
  };

  /**
   * @brief 命令 AIGC
   */
  commandAgent = ({
    command,
    agentName,
    interruptMode = INTERRUPT_PRIORITY.NONE,
    message = '',
  }: {
    command: COMMAND;
    agentName: string;
    interruptMode?: INTERRUPT_PRIORITY;
    message?: string;
  }) => {
    if (this.audioBotEnabled) {
      this.engine.sendUserBinaryMessage(
        agentName,
        string2tlv(
          JSON.stringify({
            Command: command,
            InterruptMode: interruptMode,
            Message: message,
          }),
          'ctrl'
        )
      );
      return;
    }
    console.warn('Interrupt failed, bot not enabled.');
  };

  /**
   * @brief 更新 AIGC 配置
   */
  updateAgent = async (scene: string) => {
    if (this.audioBotEnabled) {
      await this.stopAgent(scene);
      await this.startAgent(scene);
    } else {
      await this.startAgent(scene);
    }
  };

  /**
   * @brief 获取当前 AI 是否启用
   */
  getAgentEnabled = () => {
    return this.audioBotEnabled;
  };
}

export default new RTCClient();
