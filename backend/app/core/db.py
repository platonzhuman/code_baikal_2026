from __future__ import annotations

import asyncpg

from app.config import get_settings


class Database:
    """Асинхронный пул соединений asyncpg.

    Каждое выполнение запроса открывается внутри транзакции с режимом
    READ ONLY + statement_timeout — двойная защита от изменений данных.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=1,
            max_size=10,
            command_timeout=get_settings().statement_timeout_ms / 1000,
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def fetch_readonly(self, query: str, params: list | None = None) -> list[asyncpg.Record]:
        """Выполняет SQL-запрос строго в READ ONLY транзакции."""
        if not self._pool:
            raise RuntimeError("DB pool is not connected")

        async with self._pool.acquire() as conn:
            # statement_timeout в миллисекундах + read-only на уровне транзакции
            timeout_ms = get_settings().statement_timeout_ms
            async with conn.transaction():
                await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                await conn.execute("SET LOCAL default_transaction_read_only = ON")
                await conn.execute("SET LOCAL transaction_read_only = ON")
                return await conn.fetch(query, *(params or []))

    async def healthcheck(self) -> bool:
        try:
            result = await self.fetch_readonly("SELECT 1 AS ok")
            return bool(result and result[0]["ok"] == 1)
        except Exception:
            return False
