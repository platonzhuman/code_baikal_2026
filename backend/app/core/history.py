from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from app.core.schemas import ChatResponse


class RateLimiter:
    """Простой скользящий лимит запросов на ключ (session_id/IP)."""

    def __init__(self, per_minute: int = 10) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = 60.0
        async with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) >= self.per_minute:
                return False
            dq.append(now)
            return True


class HistoryStore:
    """Логи запросов + история диалогов (персистентно в chat_messages, если есть БД).

    - Пишет в таблицу chat_messages (переживает рестарт) — для GET /history.
    - Дублирует последнюю запись в памяти (быстрый доступ / fallback).
    - Вопросы/ответы храним без чувствительных полей (ПДн).
    """

    def __init__(self, db=None, max_logs: int = 1000) -> None:
        self._db = db
        self._logs: deque[dict] = deque(maxlen=max_logs)
        self._threads: dict[str, list[dict]] = {}
        self._by_query_id: dict[str, ChatResponse] = {}
        self._lock = asyncio.Lock()

    async def begin(self, session_id: str, query_id: str, role: str, question: str) -> None:
        """Отметить запрос как «в обработке» (до выполнения). Если сервер упадёт —
        в истории останется processing -> фронт покажет «запрос не был обработан»."""
        entry = {
            "query_id": query_id, "session_id": session_id, "role": role,
            "question": question, "answer": "", "sql": "", "status": "processing",
            "error": None, "created_at": time.time(),
        }
        async with self._lock:
            self._threads.setdefault(session_id, []).append(entry)
        if self._db:
            try:
                await self._db.execute(
                    "INSERT INTO chat_messages (query_id, session_id, role, question, answer, sql, status) "
                    "VALUES ($1,$2,$3,$4,'','','processing') ON CONFLICT (query_id) DO NOTHING",
                    [query_id, session_id, role, question],
                )
            except Exception:
                pass

    async def emit(self, session_id: str, req_question: str, req_role: str, response: ChatResponse) -> None:
        """Зафиксировать итог запроса: обновить запись (была 'processing') + кэш по query_id."""
        query_id = response.meta.query_id
        new_entry = {
            "query_id": query_id, "session_id": session_id, "role": req_role,
            "question": req_question, "answer": response.text, "sql": response.sql,
            "status": response.status,
            "error": response.error.message if response.error else None,
            "created_at": time.time(),
        }
        async with self._lock:
            thread = self._threads.setdefault(session_id, [])
            replaced = False
            for i, e in enumerate(thread):
                if e["query_id"] == query_id:
                    thread[i] = new_entry
                    replaced = True
                    break
            if not replaced:
                thread.append(new_entry)
            old = next((x for x in self._logs if x["query_id"] == query_id), None)
            if old is None:
                self._logs.append(dict(new_entry))
            else:
                old.update(new_entry)
            self._by_query_id[query_id] = response
        if self._db:
            try:
                await self._db.execute(
                    "UPDATE chat_messages SET answer=$1, sql=$2, status=$3 WHERE query_id=$4",
                    [response.text, response.sql, response.status, query_id],
                )
            except Exception:
                pass

    async def get_cached(self, query_id: str) -> ChatResponse | None:
        """Дедупликация: готовый ответ по query_id (повторный ретрай)."""
        if not query_id:
            return None
        async with self._lock:
            return self._by_query_id.get(query_id)

    async def get_thread(self, session_id: str) -> list[dict]:
        async with self._lock:
            return list(self._threads.get(session_id, []))

    async def all_logs(self) -> list[dict]:
        async with self._lock:
            return list(self._logs)


def build_store(db=None) -> HistoryStore:
    return HistoryStore(db=db)
