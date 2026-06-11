from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "DriftWatch"
    ENV: str = "development"
    DEBUG: bool = True

    AWS_REGION: str = "ap-southeast-2"
    AWS_ACCOUNT_ID: str = ""

    AWS_ENDPOINT_URL: str | None = None

    TF_STATE_BUCKET: str = ""
    TF_STATE_KEY: str = "terraform.tfstate"

    DYNAMODB_TABLE_NAME: str = "driftwatch"

    SNS_TOPIC_ARN: str = ""

    API_V1_STR: str = "/api/v1"
    SCAN_INTERVAL_HOURS: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
    )

    @property
    def TERRAFORM_STATE_BUCKET(self) -> str:
        return self.TF_STATE_BUCKET

    @property
    def TERRAFORM_STATE_KEY(self) -> str:
        return self.TF_STATE_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
