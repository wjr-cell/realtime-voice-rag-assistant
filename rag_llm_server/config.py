import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().with_name(".env")
load_dotenv(ENV_FILE)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _is_missing(value: str | None) -> bool:
    return not value or (isinstance(value, str) and not value.strip())


class Config:
    def __init__(self, environ: Mapping[str, str] | None = None):
        source = os.environ if environ is None else environ

        self.VOLC_AK = source.get("VOLC_ACCESS_KEY")
        self.VOLC_SK = source.get("VOLC_SECRET_KEY")
        self.ARK_API_KEY = source.get("ARK_API_KEY")
        self.ARK_ENDPOINT_ID = _clean_optional(source.get("ARK_ENDPOINT_ID"))
        self.RTC_APP_ID = _clean_optional(source.get("RTC_APP_ID"))
        self.RTC_APP_KEY = source.get("RTC_APP_KEY")

        server_url = _clean_optional(source.get("SERVER_URL")) or ""
        self.SERVER_URL = server_url.rstrip("/")

        self.VOLC_ACCOUNT_ID = _clean_optional(source.get("VOLC_ACCOUNT_ID"))
        self.KB_COLLECTION_NAME = _clean_optional(source.get("KB_COLLECTION_NAME"))
        self.KB_PROJECT_NAME = (
            _clean_optional(source.get("KB_PROJECT_NAME")) or "default"
        )

        speech_app_id = _clean_optional(source.get("SPEECH_APP_ID"))
        self.ASR_APP_ID = _clean_optional(source.get("ASR_APP_ID")) or speech_app_id
        self.TTS_APP_ID = _clean_optional(source.get("TTS_APP_ID")) or speech_app_id

        self.CORS_ORIGINS = [
            origin.strip()
            for origin in source.get("CORS_ORIGINS", "").split(",")
            if origin.strip()
        ]

    def validate(self) -> list[str]:
        required = (
            ("VOLC_ACCESS_KEY", self.VOLC_AK),
            ("VOLC_SECRET_KEY", self.VOLC_SK),
            ("ARK_API_KEY", self.ARK_API_KEY),
            ("ARK_ENDPOINT_ID", self.ARK_ENDPOINT_ID),
            ("RTC_APP_ID", self.RTC_APP_ID),
            ("RTC_APP_KEY", self.RTC_APP_KEY),
            ("VOLC_ACCOUNT_ID", self.VOLC_ACCOUNT_ID),
            ("KB_COLLECTION_NAME", self.KB_COLLECTION_NAME),
        )
        missing = [name for name, value in required if _is_missing(value)]
        if not self.ASR_APP_ID:
            missing.append("SPEECH_APP_ID or ASR_APP_ID")
        if not self.TTS_APP_ID:
            missing.append("SPEECH_APP_ID or TTS_APP_ID")
        return missing


settings = Config()
