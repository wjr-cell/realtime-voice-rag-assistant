from pathlib import Path

import config as config_module
import pytest
from config import Config


BASE = {
    "VOLC_ACCESS_KEY": "ak",
    "VOLC_SECRET_KEY": "sk",
    "ARK_API_KEY": "ark",
    "ARK_ENDPOINT_ID": "ep",
    "RTC_APP_ID": "rtc-app",
    "RTC_APP_KEY": "rtc-key",
    "VOLC_ACCOUNT_ID": "account",
    "KB_COLLECTION_NAME": "knowledge",
}


def test_speech_app_id_fills_asr_and_tts():
    config = Config({**BASE, "SPEECH_APP_ID": "speech"})

    assert config.ASR_APP_ID == "speech"
    assert config.TTS_APP_ID == "speech"
    assert config.KB_PROJECT_NAME == "default"
    assert config.validate() == []


def test_legacy_pair_remains_valid():
    config = Config({**BASE, "ASR_APP_ID": "asr", "TTS_APP_ID": "tts"})

    assert config.validate() == []


def test_partial_legacy_speech_config_is_rejected():
    config = Config({**BASE, "ASR_APP_ID": "asr"})

    assert "SPEECH_APP_ID or TTS_APP_ID" in config.validate()


def test_cors_origins_are_trimmed_and_empty_values_removed():
    config = Config(
        {
            **BASE,
            "SPEECH_APP_ID": "speech",
            "CORS_ORIGINS": (
                " https://app.example.com, ,https://admin.example.com "
            ),
        }
    )

    assert config.CORS_ORIGINS == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_individual_speech_app_ids_override_shared_app_id():
    config = Config(
        {
            **BASE,
            "SPEECH_APP_ID": "shared",
            "ASR_APP_ID": "asr",
            "TTS_APP_ID": "tts",
        }
    )

    assert config.ASR_APP_ID == "asr"
    assert config.TTS_APP_ID == "tts"


def test_validate_reports_every_missing_required_variable():
    config = Config({})

    assert config.validate() == [
        "VOLC_ACCESS_KEY",
        "VOLC_SECRET_KEY",
        "ARK_API_KEY",
        "ARK_ENDPOINT_ID",
        "RTC_APP_ID",
        "RTC_APP_KEY",
        "VOLC_ACCOUNT_ID",
        "KB_COLLECTION_NAME",
        "SPEECH_APP_ID or ASR_APP_ID",
        "SPEECH_APP_ID or TTS_APP_ID",
    ]


def test_server_url_trailing_slashes_are_removed():
    config = Config({**BASE, "SPEECH_APP_ID": "speech", "SERVER_URL": "https://api.example.com///"})

    assert config.SERVER_URL == "https://api.example.com"


def test_env_file_is_resolved_next_to_config_module():
    expected = Path(__file__).resolve().parents[1] / ".env"

    assert config_module.ENV_FILE == expected
    assert config_module.ENV_FILE.is_absolute()


def test_removed_default_room_and_user_ids_are_not_exposed():
    config = Config({**BASE, "SPEECH_APP_ID": "speech"})

    assert not hasattr(config, "DEFAULT_ROOM_ID")
    assert not hasattr(config, "DEFAULT_USER_ID")


@pytest.mark.parametrize("project_name", ["", "   "])
def test_blank_kb_project_name_uses_default(project_name):
    config = Config(
        {
            **BASE,
            "SPEECH_APP_ID": "speech",
            "KB_PROJECT_NAME": project_name,
        }
    )

    assert config.KB_PROJECT_NAME == "default"


def test_whitespace_required_value_is_reported_missing():
    config = Config({**BASE, "VOLC_ACCESS_KEY": "   ", "SPEECH_APP_ID": "speech"})

    assert "VOLC_ACCESS_KEY" in config.validate()


def test_whitespace_shared_speech_id_is_reported_missing():
    config = Config({**BASE, "SPEECH_APP_ID": "   "})

    assert "SPEECH_APP_ID or ASR_APP_ID" in config.validate()
    assert "SPEECH_APP_ID or TTS_APP_ID" in config.validate()


def test_blank_legacy_speech_ids_fall_back_to_shared_id():
    config = Config(
        {
            **BASE,
            "SPEECH_APP_ID": " shared ",
            "ASR_APP_ID": "   ",
            "TTS_APP_ID": "   ",
        }
    )

    assert config.ASR_APP_ID == "shared"
    assert config.TTS_APP_ID == "shared"


def test_whitespace_server_url_is_normalized_to_empty_string():
    config = Config({**BASE, "SPEECH_APP_ID": "speech", "SERVER_URL": "   "})

    assert config.SERVER_URL == ""


def test_explicit_mapping_does_not_fall_back_to_process_environment(monkeypatch):
    monkeypatch.setenv("VOLC_ACCESS_KEY", "process-ak")
    config = Config({**BASE, "VOLC_ACCESS_KEY": "", "SPEECH_APP_ID": "speech"})

    assert config.VOLC_AK == ""
    assert "VOLC_ACCESS_KEY" in config.validate()
