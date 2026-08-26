import os

# Тесты должны быть быстрыми и не зависеть от сетевого LLM/Yandex.
# Переопределяем .env приоритетом окружения и сбрасываем кэш настроек.
os.environ["LLM_MODE"] = "mock"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

import asyncio  # noqa: E402

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.core.schema_loader import load_schema  # noqa: E402
from app.core.schema_sanitizer import set_schema  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _load_real_schema():
    """Подтягиваем схему из БД один раз, чтобы unit-тесты санитайзера
    работали с реальной структурой (без хардкода)."""

    def _run():
        async def _inner():
            db = Database(get_settings().database_url)
            await db.connect()
            try:
                set_schema(await load_schema(db))
            finally:
                await db.close()

        asyncio.run(_inner())

    _run()
