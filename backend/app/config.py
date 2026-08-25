from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://uni:uni_pass@localhost:5432/university"
    llm_api_key: str = ""
    llm_model: str = ""
    app_secret: str = "change_me"

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
