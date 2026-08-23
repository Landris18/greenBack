from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: Literal["local", "dev", "staging", "production"] = "local"
    APP_NAME: str = "GreenSI"
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    SECRET_KEY: str = Field(min_length=16)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"

    DATABASE_HOST: str = "postgres"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "greensi"
    DATABASE_USER: str = "greensi"
    DATABASE_PASSWORD: str = "greensi"
    DATABASE_ECHO: bool = False

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    DOCKER_HOST: str = "tcp://docker-socket-proxy:2375"
    DOCKER_TIMEOUT_SECONDS: int = 10
    COLLECTOR_INTERVAL_SECONDS: int = 30
    COLLECTOR_MAX_CONCURRENCY: int = 8
    COLLECTOR_BACKOFF_MAX_SECONDS: int = 300
    COLLECTOR_HOST_NAME: str = "localhost"
    SYSFS_PATH: str = "/hostsys"
    BMC_REDFISH_URL: str = ""
    BMC_USERNAME: str = ""
    BMC_PASSWORD: str = ""
    BMC_VERIFY_TLS: bool = True
    BMC_TIMEOUT_SECONDS: float = 2.0
    BMC_POLL_SECONDS: float = 10.0
    PROCFS_PATH: str = "/proc"
    PROJECTS_ROOT_HOST: str = "/home"
    PROJECTS_ROOT_MOUNT: str = "/host/projects"
    CALIBRATION_LOG_PATH: str = "/data/calibration/calibration_samples.csv"

    SEED_ADMIN_EMAIL: str = "admin@greensi.fr"
    SEED_ADMIN_PASSWORD: str = "greensi"
    SEED_ADMIN_NAME: str = "Administrateur"

    @property
    def rapl_path(self) -> str:
        return f"{self.SYSFS_PATH}/devices/virtual/powercap"

    @property
    def power_supply_path(self) -> str:
        return f"{self.SYSFS_PATH}/class/power_supply"

    @property
    def hwmon_path(self) -> str:
        return f"{self.SYSFS_PATH}/class/hwmon"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    @property
    def alembic_database_url(self) -> str:
        return self.database_url

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
