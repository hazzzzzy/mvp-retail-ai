from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_db: str = "mvp_retail_ai"
    mysql_user: str = "root"
    mysql_password: str = "root"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    chroma_dir: str = "./.chroma"
    embed_model_path: str = "./models/bge-base-zh-v1.5"

    sql_max_rows: int = 200
    sql_timeout_seconds: int = 5

    crm_base_url: str = "http://127.0.0.1:8000/mock/crm"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def chroma_dir_abs(self) -> str:
        return str((Path(__file__).resolve().parents[2] / self.chroma_dir).resolve())

    @property
    def embed_model_abs(self) -> str:
        return str((Path(__file__).resolve().parents[2] / self.embed_model_path).resolve())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
