import ipaddress
from urllib.parse import urlsplit

from services.token_build import AccessToken, PRIVILEGES


WELCOME_MESSAGE = (
    "我是小智，你的专属课程顾问，有什么问题尽管问我吧"
)


def build_rtc_token(config, rtc: dict) -> str:
    token = AccessToken(
        config.RTC_APP_ID,
        config.RTC_APP_KEY,
        rtc["rtc_room_id"],
        rtc["rtc_user_id"],
    )
    token.add_privilege(PRIVILEGES["PrivSubscribeStream"], 0)
    token.add_privilege(PRIVILEGES["PrivPublishStream"], 0)
    token.expire_time(token.issued_at + 24 * 60 * 60)
    return token.serialize()


def resolve_server_url(request, config) -> str:
    if config.SERVER_URL:
        return config.SERVER_URL

    fallback_url = str(request.base_url).rstrip("/")
    try:
        if "\\" in fallback_url:
            raise ValueError
        parsed = urlsplit(fallback_url)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        hostname = parsed.hostname
        port = parsed.port
        if hostname is None:
            raise ValueError
        if hostname == "localhost":
            normalized_host = hostname
            address = None
        else:
            address = ipaddress.ip_address(hostname)
            normalized_host = address.compressed
    except ValueError:
        raise ValueError("不安全的服务地址") from None

    if address is not None:
        allowed_addresses = {
            ipaddress.ip_address("127.0.0.1"),
            ipaddress.ip_address("::1"),
        }
        private_networks = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
        if address not in allowed_addresses and not any(
            address in network for network in private_networks
        ):
            raise ValueError("不安全的服务地址")
        if address.version == 6:
            normalized_host = f"[{normalized_host}]"

    normalized_port = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{normalized_host}{normalized_port}"


def build_existing_asr_tts_llm_config(config, server_url: str) -> dict:
    return {
        "ASRConfig": {
            "Provider": "volcano",
            "ProviderParams": {
                "Mode": "smallmodel",
                "AppId": config.ASR_APP_ID,
                "Cluster": "volcengine_streaming_common",
            },
        },
        "TTSConfig": {
            "Provider": "volcano",
            "ProviderParams": {
                "app": {"appid": config.TTS_APP_ID, "cluster": "volcano_tts"},
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
            "Url": f"{server_url}/api/chat_callback",
            "Method": "POST",
            "ApiType": "https" if server_url.startswith("https") else "http",
        },
        "InterruptMode": 0,
    }


def build_voice_chat_body(
    action: str, config, rtc: dict, server_url: str
) -> dict:
    if action == "StartVoiceChat":
        return {
            "AppId": config.RTC_APP_ID,
            "RoomId": rtc["rtc_room_id"],
            "TaskId": rtc["rtc_task_id"],
            "AgentConfig": {
                "TargetUserId": [rtc["rtc_user_id"]],
                "WelcomeMessage": WELCOME_MESSAGE,
                "UserId": "AiAgent",
                "EnableConversationStateCallback": True,
            },
            "Config": build_existing_asr_tts_llm_config(config, server_url),
        }
    if action == "StopVoiceChat":
        return {
            "AppId": config.RTC_APP_ID,
            "RoomId": rtc["rtc_room_id"],
            "TaskId": rtc["rtc_task_id"],
        }
    raise ValueError(f"不支持的 Action: {action}")
