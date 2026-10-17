import importlib
import importlib.util
from types import SimpleNamespace

import pytest

from config import Config


SETTINGS = Config(
    {
        "RTC_APP_ID": "rtc-app",
        "RTC_APP_KEY": "rtc-key",
        "ASR_APP_ID": "asr-app",
        "TTS_APP_ID": "tts-app",
        "SERVER_URL": "https://configured.example.com",
    }
)
RTC = {
    "rtc_room_id": "room_a",
    "rtc_user_id": "user_1",
    "rtc_task_id": "task_a",
}


def voice_module():
    spec = importlib.util.find_spec("services.voice_chat_service")
    assert spec is not None, "voice chat service must exist"
    return importlib.import_module("services.voice_chat_service")


def test_start_and_stop_share_global_app_room_and_task():
    build_voice_chat_body = voice_module().build_voice_chat_body

    start = build_voice_chat_body(
        "StartVoiceChat", SETTINGS, RTC, "https://api.example.com"
    )
    stop = build_voice_chat_body(
        "StopVoiceChat", SETTINGS, RTC, "https://api.example.com"
    )

    assert start["AppId"] == stop["AppId"] == SETTINGS.RTC_APP_ID
    assert start["RoomId"] == stop["RoomId"] == "room_a"
    assert start["TaskId"] == stop["TaskId"] == "task_a"
    assert start["AgentConfig"]["TargetUserId"] == ["user_1"]


def test_start_preserves_existing_voice_chat_configuration():
    start = voice_module().build_voice_chat_body(
        "StartVoiceChat", SETTINGS, RTC, "http://request.example.com"
    )

    assert start["AgentConfig"] == {
        "TargetUserId": ["user_1"],
        "WelcomeMessage": "我是懂小智，你的专属课程顾问，有什么问题尽管问我吧，我比懂王更强",
        "UserId": "AiAgent",
        "EnableConversationStateCallback": True,
    }
    assert start["Config"] == {
        "ASRConfig": {
            "Provider": "volcano",
            "ProviderParams": {
                "Mode": "smallmodel",
                "AppId": "asr-app",
                "Cluster": "volcengine_streaming_common",
            },
        },
        "TTSConfig": {
            "Provider": "volcano",
            "ProviderParams": {
                "app": {"appid": "tts-app", "cluster": "volcano_tts"},
                "audio": {
                    "voice_type": "BV001_streaming",
                    "speed_ratio": 1,
                    "pitch_ratio": 1,
                    "volume_ratio": 1,
                },
            },
        },
        "LLMConfig": {
            "Mode": "CustomLLM",
            "Url": "http://request.example.com/api/chat_callback",
            "Method": "POST",
            "ApiType": "http",
        },
        "InterruptMode": 0,
    }


def test_resolve_server_url_prefers_config_and_allows_local_request_fallback():
    module = voice_module()
    request = SimpleNamespace(base_url="http://localhost:3001/")

    assert module.resolve_server_url(request, SETTINGS) == (
        "https://configured.example.com"
    )
    assert module.resolve_server_url(request, Config({})) == "http://localhost:3001"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:3001/",
        "http://[::1]:3001/",
        "http://10.1.2.3:3001/",
        "http://172.16.1.2:3001/",
        "http://172.31.255.254:3001/",
        "http://192.168.1.2:3001/",
    ],
)
def test_resolve_server_url_allows_private_development_hosts(base_url):
    request = SimpleNamespace(base_url=base_url)

    assert voice_module().resolve_server_url(request, Config({})) == base_url.rstrip(
        "/"
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://attacker.example:3001/",
        "http://8.8.8.8:3001/",
        "http://172.32.0.1:3001/",
        "http://192.169.1.2:3001/",
        "http://attacker.example\\@localhost:3001/",
        "http://attacker.example@localhost:3001/",
        "http://localhost:3001/private",
        "http://localhost:3001/?next=attacker.example",
        "http://localhost:3001/#attacker.example",
        "http://localhost:not-a-port/",
        "ftp://localhost:3001/",
    ],
)
def test_resolve_server_url_rejects_unconfigured_public_hosts(base_url):
    request = SimpleNamespace(base_url=base_url)

    with pytest.raises(ValueError, match="^不安全的服务地址$"):
        voice_module().resolve_server_url(request, Config({}))


def test_resolve_server_url_rebuilds_canonical_ipv6_origin():
    request = SimpleNamespace(base_url="http://[0:0:0:0:0:0:0:1]:3001/")

    assert voice_module().resolve_server_url(request, Config({})) == (
        "http://[::1]:3001"
    )


def test_unsupported_voice_chat_action_is_rejected():
    with pytest.raises(ValueError, match="^不支持的 Action: Unknown$"):
        voice_module().build_voice_chat_body(
            "Unknown", SETTINGS, RTC, "https://api.example.com"
        )
