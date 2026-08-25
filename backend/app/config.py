from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://uni:uni_pass@localhost:5432/university"
    app_secret: str = "change_me"

    # LLM (Lead AI, P1)
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_mode: str = "auto"          # auto | mock | real
    llm_auth: str = "auto"          # auto | bearer | apikey
    llm_timeout: float = 30.0
    llm_max_retries: int = 2

    # Yandex AI Studio / Cloud (fallback, если LLM_* не заполнены)
    yandex_cloud_api_key: str = ""
    yandex_cloud_model: str = ""
    yandex_cloud_folder: str = ""

    # Безопасность
    statement_timeout_ms: int = 5000
    max_rows: int = 100          # авто-LIMIT для "широких" запросов
    max_concurrent_queries: int = 8
    rate_limit_per_minute: int = 10

    # LLM-«судья» (проверка логичности SQL 0..1)
    sql_judge_threshold: float = 0.8
    max_sql_attempts: int = 2    # генерация + самоисправление (≤ N попыток)


@lru_cache
def get_settings() -> Settings:
    return Settings()
