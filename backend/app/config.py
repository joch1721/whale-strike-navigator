"""
Central config — loads from .env and exposes typed settings.
Import this anywhere in the backend: from app.config import settings
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    app_env: str = "development"

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # External API keys
    aisstream_api_key: str = ""
    whale_alert_api_key: str = ""

    # Scheduling
    ais_refresh_interval_minutes: int = 15

    # CORS
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    # Data directories
    raw_data_dir: Path = Path("../data/raw")
    processed_data_dir: Path = Path("../data/processed")
    shapefiles_dir: Path = Path("../data/shapefiles")

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
