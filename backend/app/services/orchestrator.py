from __future__ import annotations

import asyncio
import math
import time
import uuid

from app.config import get_settings
from app.core.db import Database
from app.core.schemas import ChatRequest, ChatResponse, ErrorBlock, ExplanationBlock, ResultBlock
from app.core.schema_sanitizer import get_sanitized_schema
from app.core.security import SQLValidationError, build_validator
from app.services.llm_client import LLMClient

# ---- Отказы (ясные, а не «уточните») ----
_DESTRUCTIVE_VERBS = (
    "удалит", "удали", "снести", "снеси", "изменит", "измени", "обнови", "встав",
    "создай", "очисти", "стерет", "убить", "удалить",
    "drop", "delete", "update", "insert", "alter", "truncate", "replace",
)
_REFUSAL_PII_HINTS_UNUSED = (
    "fio", "персональн", "пдн", "чувствительн", "student_card", "sensitive", "паспорт",
    "личн", "скрыт",
)
_REFUSAL_DML_HINTS = (
    "не select", "несколько инструкций", "только select",
    "insert ", "update ", "delete ", "drop ", "alter ", "truncate ",
    "dml", "манипуляц",
)

# Явные просьбы про персональные данные — отказ сразу (но НЕ трогаем «фио преподавателей»).
_PII_QUESTION_HINTS = (
    "паспорт", "телефон", "почт", "email", "личн", "персональн",
    "фио студент", "фио абитуриент", "фио всех", "зачётк", "студенч", "паспортн",
)


def _is_destructive(question: str) -> bool:
    q = (question or "").lower()
    return any(v in q for v in _DESTRUCTIVE_VERBS)


def _asks_pii(question: str) -> bool:
    q = (question or "").lower()
    return any(v in q for v in _PII_QUESTION_HINTS)


def classify_refusal(check: dict) -> tuple[str, str] | None:
    """Если судья поймал нарушение правил — вернуть (код, сообщение) для чёткого отказа.

    ПДн: реагируем ТОЛЬКО если причина прямо про выборку чувствительных полей
    (иначе фраза «поля fio недоступны» из разбора схемы даёт ложный отказ).
    """
    reason = str(check.get("reason", "")).lower()
    select_hint = any(w in reason for w in ("выборка", "выбирает", "select ", "столбц"))
    pii_hint = any(w in reason for w in ("fio", "персональн", "паспорт", "чувствительн",
                                         "пдн", "student_card", "ф.и.о", "контакт", "телефон"))
    if select_hint and pii_hint:
        return ("PDN_VIOLATION",
                "Персональные данные недоступны. Система выдаёт только "
                "обезличенные агрегированные показатели (COUNT/AVG), без ФИО и контактов.")
    if any(h in reason for h in _REFUSAL_DML_HINTS):
        return ("READ_ONLY",
                "Доступ только для чтения. Удаление и изменение данных невозможны "
                "— система выполняет только SELECT.")
    return None


class Orchestrator:
    """Цепочка: вопрос -> (LLM генерация + судья 0..1) -> AST-валидация -> БД -> ответ.

    LLM-судья (check_sql) оценивает логичность сгенерированного SQL от 0 до 1.
    Если score < порога (0.8) — самоисправление (регенерация), максимум N попыток.
    AST-валидатор — всегда жёсткий слой безопасности (SELECT + whitelist + ПДн).
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.validator = build_validator()
        self.llm = LLMClient()
        self.settings = get_settings()
        # Лимит конкурентности: не перегружаем LLM и БД параллельными запросами.
        self._sem = asyncio.Semaphore(self.settings.max_concurrent_queries)
        # Кэш ответов: (role|question) -> (ts, ChatResponse). Повторные вопросы мгновенно.
        self._cache: dict[str, tuple[float, ChatResponse]] = {}
        self._cache_lock = asyncio.Lock()

    async def _cached(self, role: str, question: str) -> ChatResponse | None:
        async with self._cache_lock:
            hit = self._cache.get(f"{role}|{question}")
            if hit is None:
                return None
            ts, resp = hit
            if time.time() - ts > self.settings.cache_ttl:
                self._cache.pop(f"{role}|{question}", None)
                return None
            copy = resp.model_copy(deep=True)
            copy.meta.latency_ms = 0
            copy.meta.cached = True
            return copy

    async def _cache_put(self, role: str, question: str, resp: ChatResponse) -> None:
        async with self._cache_lock:
            self._cache[f"{role}|{question}"] = (time.time(), resp)

    async def chat(self, req: ChatRequest, query_id: str | None = None,
                   history: list[dict] | None = None) -> ChatResponse:
        async with self._sem:
            return await self._chat(req, query_id, history)

    async def _chat(self, req: ChatRequest, query_id: str | None = None,
                    history: list[dict] | None = None) -> ChatResponse:
        start = time.perf_counter()
        query_id = query_id or req.query_id or str(uuid.uuid4())
        schema = get_sanitized_schema(req.role.value)

        # Кэш: повторный вопрос той же роли — мгновенно (без LLM/БД).
        if not history:
            cached = await self._cached(req.role.value, req.question)
            if cached is not None:
                return cached

        # Отказ до LLM: явное желание изменить/удалить данные -> сразу "нет".
        if _is_destructive(req.question):
            return self._error(
                "READ_ONLY",
                "Доступ только для чтения. Удаление, изменение и создание данных "
                "невозможны — система является безопасным коннектором «SELECT только».",
                query_id, start, meta=self._judge_meta({}),
            )
        # Отказ до LLM: просьба про персональные данные (не ФИО преподавателей).
        if _asks_pii(req.question):
            return self._error(
                "PDN_VIOLATION",
                "Персональные данные недоступны. Система выдаёт только обезличенные "
                "агрегированные показатели (COUNT/AVG), без ФИО, паспортов, телефонов "
                "и контактов студентов и абитуриентов.",
                query_id, start, meta=self._judge_meta({}),
            )

        # Шаг 1: генерация + САМОСУДЬЯ (1 вызов LLM, редко 2). Дальше — без LLM до ответа.
        raw_sql, judge_info, suggestion = await self._generate_sql_candidate(req, schema, history)

        if raw_sql is None:
            msg = suggestion or "Уточните, пожалуйста, условия запроса — и я пересоберу его."
            return self._error("NEEDS_REFINEMENT", msg, query_id, start, sql="",
                               meta=self._judge_meta(judge_info))

        try:
            # Шаг 2: жёсткая безопасность (AST) — только SELECT/whitelist/ПДн.
            safe_sql, meta = self.validator.validate(raw_sql)
        except SQLValidationError as e:
            return self._error(e.code, e.message, query_id, start, sql=raw_sql)

        # Шаг 3: проверка стоимости (EXPLAIN) — не выполняем слишком дорогие запросы.
        try:
            plan = await self.db.explain(safe_sql)
        except Exception:
            plan = {"total_cost": 0.0}
        if plan.get("total_cost", 0.0) > self.settings.explain_max_cost:
            return self._error(
                "NEEDS_REFINEMENT",
                "Запрос оценивается как слишком дорогой. Уточните условия (факультет, год, "
                "категория, статус), чтобы я построил более дешёвый запрос.",
                query_id, start, sql=safe_sql, meta=self._judge_meta(judge_info),
            )

        try:
            # Шаг 4: узнаём ОБЩЕЕ число строк (без LIMIT) для настоящей пагинации.
            total = await self._count_rows(safe_sql)
        except Exception as e:
            return self._error("DB_EXECUTION", f"Ошибка подсчёта строк: {e}", query_id, start, sql=safe_sql)

        truncated = meta.get("truncated", False)
        if total == 0:
            return self._error(
                "EMPTY_RESULT",
                "По вашему запросу ничего не найдено. Уточните, пожалуйста, критерии "
                "(факультет, год, категория, статус) — и я пересоберу запрос.",
                query_id, start, sql=safe_sql, meta=self._judge_meta(judge_info),
            )

        # Пагинация: страница из БД через LIMIT/OFFSET.
        page_size = req.max_rows
        total_pages = max(1, math.ceil(total / page_size))
        page = min(max(req.page, 1), total_pages)
        try:
            page_rows = await self.db.fetch_readonly(self._page_sql(safe_sql, page, page_size))
        except Exception as e:
            return self._error("DB_EXECUTION", f"Ошибка выполнения запроса: {e}", query_id, start, sql=safe_sql)

        columns = list(page_rows[0].keys()) if page_rows else []
        data = [dict(r) for r in page_rows]

        resp = ChatResponse(
            status="success",
            text=self._template_summarize(req.question, columns, data, total),
            sql=safe_sql,
            result=ResultBlock(
                columns=columns,
                rows=data,
                row_count=total,
                truncated=truncated,
                warning=("Запрос широкий, показаны первые строки" if truncated else None),
                suggested_filters=self._suggest_filters(meta, total, page_size),
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
            ),
            explanation=self._explain(meta, safe_sql),
            meta={
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "query_id": query_id,
                "plan": plan,
                "judge": self._judge_meta(judge_info),
            },
        )
        if not history:
            await self._cache_put(req.role.value, req.question, resp)
        return resp

    @staticmethod
    def _template_summarize(question: str, columns: list[str], rows: list[dict], total: int) -> str:
        """Быстрый шаблонный ответ (без вызова LLM — ради скорости)."""
        if not rows:
            return f"По запросу «{question}» ничего не найдено."
        parts = []
        for r in rows[:3]:
            if len(columns) >= 2:
                parts.append(f"{r.get(columns[0], '')} — {r.get(columns[1], '')}")
            elif columns:
                parts.append(str(r.get(columns[0], "")))
        head = "; ".join(parts)
        return (f"Результат по запросу «{question}»: всего {total} записей. "
                f"{head}" + ("…" if total > 3 else "."))

    def _suggest_filters(self, meta: dict, total: int = 0, page_size: int = 50) -> list[dict[str, str]] | None:
        """Уточняющие фильтры для «широкого»/неуточнённого запроса (Big Data бонус)."""
        if meta.get("truncated") or total > page_size:
            return [
                {"field": "faculty", "label": "Факультет"},
                {"field": "year", "label": "Год"},
                {"field": "status", "label": "Статус"},
            ]
        return None

    @staticmethod
    def _remove_limit_and_order(sql: str) -> str:
        import sqlglot
        expr = sqlglot.parse_one(sql, read="postgres")
        if expr is not None and hasattr(expr, "set"):
            expr.set("order", None)
            expr.set("limit", None)
        return expr.sql(dialect="postgres")

    @staticmethod
    def _page_sql(sql: str, page: int, page_size: int) -> str:
        base = Orchestrator._remove_limit_and_order(sql)
        offset = (page - 1) * page_size
        return f"{base} LIMIT {page_size} OFFSET {offset}"

    async def _count_rows(self, sql: str) -> int:
        """Общее число строк БЕЗ LIMIT (для настоящей пагинации)."""
        inner = self._remove_limit_and_order(sql)
        count_sql = f"SELECT COUNT(*) AS __total FROM ({inner}) __sub"
        rows = await self.db.fetch_readonly(count_sql)
        return int(rows[0]["__total"])

    async def _generate_sql_candidate(self, req: ChatRequest, schema: str,
                                      history: list[dict] | None = None,
                                      ) -> tuple[str | None, dict, str]:
        """1-2 вызова LLM: генерация + САМОСУДЬЯ (один вызов). При неуверенности —
        одна попытка исправления с фидбеком; потом сужение. Возвращает (sql, judge_info, suggestion).
        """
        feedback = ""
        last_meta: dict = {}
        for _ in range(self.settings.max_sql_attempts):
            sql, meta = await self.llm.generate_and_judge(req.question, schema, req.role.value,
                                                          feedback, history)
            last_meta = meta
            ok = (not meta.get("unknown") and meta.get("is_valid")
                  and meta.get("score", 0.0) >= self.settings.sql_judge_threshold)
            if ok:
                return sql, meta, ""
            feedback = f"Предыдущий SQL нелогичен ({meta.get('score')}): {meta.get('reason')}. Исправь."
        suggestion = await self.llm.suggest_narrowing(req.question, schema, req.role.value, feedback)
        return None, last_meta, suggestion

    def _judge_meta(self, info: dict) -> dict:
        return {
            "score": info.get("score", 0.0),
            "reason": info.get("reason", ""),
            "threshold": self.settings.sql_judge_threshold,
        }

    def _explain(self, meta: dict, sql: str = "") -> ExplanationBlock:
        """Explainable AI: AST-объяснение SQL (P1) + метаданные валидатора (P2)."""
        ast = self.llm.explain_sql(sql) if sql else {}
        e = self.validator.explain(meta)
        return ExplanationBlock(
            tables=ast.get("tables") or e["tables"],
            joins=ast.get("joins", []),
            filters=ast.get("filters", []),
            aggregates=ast.get("aggregates", []),
            constraints=ast.get("constraints", []),
        )

    _REFUSAL_CODES = {"PDN_VIOLATION", "READ_ONLY", "NOT_SELECT", "TABLE_FORBIDDEN", "NEEDS_REFINEMENT"}

    def _error(self, code, message, query_id, start, req=None, sql="", meta=None) -> ChatResponse:
        # Для отказов (запрещённое действие/ПДн) — чистый текст отказа, без «не удалось ответить».
        text = message if code in self._REFUSAL_CODES else f"Не удалось ответить: {message}. Данные не придумываются."
        return ChatResponse(
            status="error",
            text=text,
            sql=sql,
            error=ErrorBlock(code=code, message=message),
            meta={
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "query_id": query_id,
                **({"judge": meta} if meta else {}),
            },
        )
