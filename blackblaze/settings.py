"""Typed configuration, loaded from the environment at import time.

Importing this module raises if a required key is missing, so the service
refuses to start rather than failing halfway through someone's upload.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    b2_key_id: str
    b2_app_key: str
    b2_bucket_name: str
    anthropic_api_key: str

    # Uploads above this are rejected with 413. Keeps a synchronous request
    # inside a sane timeout and stays under B2's large-file threshold.
    max_upload_bytes: int = 10 * 1024 * 1024

    # Text is truncated to this before being sent for summarisation.
    max_text_chars: int = 20_000

    # B2 file_info becomes HTTP headers and caps at roughly 2KB in total,
    # so the stored copy of the description is truncated to this.
    max_metadata_description_chars: int = 500

    model: str = "claude-opus-5"


settings = Settings()
