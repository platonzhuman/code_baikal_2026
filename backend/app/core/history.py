from __future__ import annotations

import asyncio
from collections import deque

from app.core.schemas import ChatResponse


class HistoryStore:
    """Лёгкое in-memory хранилище: логи запросов + история диалогов по session_id.

    Для хакатона достаточно. В проде заменить на таблицу chat_messages + audit-log.
    Каждая запись логируется без ПДн (вопрос храним, но без чувствительных полей).
    """

    def __init__(self, max_logs: int = 1000) -> None:
        self._logs: deque[dict] = deque(maxlen=max_logs)
        self._threads: dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()

    async def record(self, session_id: str, query_id: str, role: str,
                     question: str, response: ChatResponse) -> dict:
        entry = {
            "query_id": query_id,
            "session_id": session_id,
            "role": role,
            "question": question,
            "status": response.status,
            "sql": response.sql,
            "row_count": response.result.row_count if response.result else 0,
            "latency_ms": response.meta.latency_ms if response.meta else 0,
            "error": response.error.message if response.error else None,
        }
        async with self._lock:
            self._logs.append(entry)
            self._threads.setdefault(session_id, []).append({
                "query_id": query_id,
                "question": question,
                "answer": response.text,
                "role": role,
            })
        return entry

    async def get_thread(self, session_id: str) -> list[dict]:
        async with self._lock:
            return list(self._threads.get(session_id, []))

    async def all_logs(self) -> list[dict]:
        async with self._lock:
            return list(self._logs)


def build_store() -> HistoryStore:
    return HistoryStore()
