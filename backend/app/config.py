"""Application settings, read from environment variables (prefix FRAMEWORK_) or backend/.env."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRAMEWORK_", env_file=".env", extra="ignore")

    storage_dir: Path = Path("./storage")
    max_upload_mb: int = 2048
    ffprobe_path: str = "ffprobe"
    ffmpeg_path: str = "ffmpeg"
    # Speech-to-text model for the creative director: tiny, base, small (default), medium, large-v3.
    # Bigger catches more "um"s but is slower. Empty string turns transcription off.
    whisper_model: str = "small"
    cors_origins: list[str] = ["http://localhost:3000"]
    # Read from ANTHROPIC_API_KEY (environment or backend/.env). Optional.
    anthropic_api_key: str | None = Field(None, validation_alias="ANTHROPIC_API_KEY")

    # Containers we accept on import. Checked by extension first, then confirmed by ffprobe.
    allowed_extensions: set[str] = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".mxf"}

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
