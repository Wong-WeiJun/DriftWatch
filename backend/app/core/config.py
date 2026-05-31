from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "DriftWatch"
    ENV: str = "development"
    DEBUG: bool = True

    AWS_REGION: str = "ap-southeast-1"
    DYNAMODB_TABLE_NAME: str = "driftwatch_events"
    TF_STATE_BUCKET: str = "state_bucket"
    SNS_TOPIC_ARN: str = ""

    API_V1_STR: str = "/api/v1"
    SCAN_INTERVAL_HOURS: int = 3
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
