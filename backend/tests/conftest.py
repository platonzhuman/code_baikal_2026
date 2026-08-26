import os

# Тесты должны быть быстрыми и не зависеть от сетевого LLM/Yandex.
# Переопределяем .env приоритетом окружения и сбрасываем кэш настроек.
os.environ["LLM_MODE"] = "mock"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
