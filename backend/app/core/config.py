"""应用配置：从项目根目录的 .env 读取。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "mysql+aiomysql://root:@127.0.0.1:3306/trade_order?charset=utf8mb4"
    test_database_url: str = ""
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 480

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vision_model: str = "qwen3-vl-plus"

    llm_timeout_seconds: float = 30
    # 模型请求是否使用系统代理（HTTPS_PROXY 等环境变量）
    llm_use_system_proxy: bool = False

    upload_max_bytes: int = 10 * 1024 * 1024

    # 业务时区相对 UTC 的小时数，默认北京时间
    app_utc_offset_hours: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
