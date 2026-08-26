from __future__ import annotations

import json
import time

import asyncpg

from app.config import get_settings
from app.core.logging import emit


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

        t0 = time.perf_counter()
        async with self._pool.acquire() as conn:
            # statement_timeout в миллисекундах + read-only на уровне транзакции
            timeout_ms = get_settings().statement_timeout_ms
            async with conn.transaction():
                await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                await conn.execute("SET LOCAL default_transaction_read_only = ON")
                await conn.execute("SET LOCAL transaction_read_only = ON")
                rows = await conn.fetch(query, *(params or []))
        ql = query.lstrip().lower()
        if not ql.startswith(("information_schema", "pg_", "select 1 ")):
            emit("DEBUG", "db", "db_query", data={"sql_preview": query[:300],
                                                  "row_count": len(rows),
                                                  "execution_time_ms": round((time.perf_counter() - t0) * 1000, 2)})
        return rows

    async def healthcheck(self) -> bool:
        try:
            result = await self.fetch_readonly("SELECT 1 AS ok")
            return bool(result and result[0]["ok"] == 1)
        except Exception:
            return False

    async def execute(self, query: str, params: list | None = None) -> str:
        """Выполнить запись в БД (для chat_messages / служебных таблиц)."""
        if not self._pool:
            raise RuntimeError("DB pool is not connected")
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *(params or []))

    async def explain(self, query: str) -> dict:
        """EXPLAIN (FORMAT JSON) для оценки стоимости/времени плана.

        Не выполняет запрос (только планирует) -> безопасно для оценки.
        """
        if not self._pool:
            raise RuntimeError("DB pool is not connected")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL statement_timeout = {get_settings().statement_timeout_ms}")
                await conn.execute("SET LOCAL default_transaction_read_only = ON")
                await conn.execute("SET LOCAL transaction_read_only = ON")
                rows = await conn.fetch("EXPLAIN (FORMAT JSON) " + query)
                raw = rows[0]["QUERY PLAN"]
                if isinstance(raw, str):
                    raw = json.loads(raw)
                plan = raw[0]["Plan"]
                return {
                    "total_cost": plan.get("Total Cost", 0.0),
                    "startup_cost": plan.get("Startup Cost", 0.0),
                    "plan_rows": plan.get("Plan Rows", 0),
                    "node_type": plan.get("Node Type", ""),
                }
