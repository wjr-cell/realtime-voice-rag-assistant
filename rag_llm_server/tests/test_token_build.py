import base64
import hashlib
import hmac
import importlib
import importlib.util
import struct
import time

from config import Config
from services.token_build import PRIVILEGES


APP_ID = "a" * 24
APP_KEY = "test-app-key"


def voice_module():
    spec = importlib.util.find_spec("services.voice_chat_service")
    assert spec is not None, "voice chat service must exist"
    return importlib.import_module("services.voice_chat_service")


def read_uint16(data, offset):
    return struct.unpack_from("<H", data, offset)[0], offset + 2


def read_uint32(data, offset):
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def read_bytes(data, offset):
    length, offset = read_uint16(data, offset)
    return data[offset : offset + length], offset + length


def decode_token(token):
    assert token[:3] == "001"
    app_id = token[3:27]
    outer = base64.b64decode(token[27:])
    message, offset = read_bytes(outer, 0)
    signature, offset = read_bytes(outer, offset)
    assert offset == len(outer)

    offset = 0
    nonce, offset = read_uint32(message, offset)
    issued_at, offset = read_uint32(message, offset)
    expire_at, offset = read_uint32(message, offset)
    room, offset = read_bytes(message, offset)
    user, offset = read_bytes(message, offset)
    privilege_count, offset = read_uint16(message, offset)
    privileges = {}
    for _ in range(privilege_count):
        privilege, offset = read_uint16(message, offset)
        expires, offset = read_uint32(message, offset)
        privileges[privilege] = expires
    assert offset == len(message)
    return {
        "app_id": app_id,
        "message": message,
        "signature": signature,
        "nonce": nonce,
        "issued_at": issued_at,
        "expire_at": expire_at,
        "room": room.decode(),
        "user": user.decode(),
        "privileges": privileges,
    }


def test_build_rtc_token_keeps_official_format_and_24_hour_permissions():
    module = voice_module()
    config = Config({"RTC_APP_ID": APP_ID, "RTC_APP_KEY": APP_KEY})
    rtc = {"rtc_room_id": "room_dynamic", "rtc_user_id": "user_7"}

    before = int(time.time())
    decoded = decode_token(module.build_rtc_token(config, rtc))
    after = int(time.time())

    assert decoded["app_id"] == APP_ID
    assert before <= decoded["issued_at"] <= after
    assert decoded["expire_at"] - decoded["issued_at"] == 24 * 60 * 60
    assert decoded["room"] == "room_dynamic"
    assert decoded["user"] == "user_7"
    assert list(decoded["privileges"]) == [0, 1, 2, 3, 4]
    assert decoded["privileges"] == {
        PRIVILEGES["PrivPublishStream"]: 0,
        PRIVILEGES["privPublishAudioStream"]: 0,
        PRIVILEGES["privPublishVideoStream"]: 0,
        PRIVILEGES["privPublishDataStream"]: 0,
        PRIVILEGES["PrivSubscribeStream"]: 0,
    }
    assert decoded["signature"] == hmac.new(
        APP_KEY.encode(), decoded["message"], hashlib.sha256
    ).digest()
