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

    async def chat(self, req: ChatRequest, query_id: str | None = None) -> ChatResponse:
        async with self._sem:
            return await self._chat(req, query_id)

    async def _chat(self, req: ChatRequest, query_id: str | None = None) -> ChatResponse:
        start = time.perf_counter()
        query_id = query_id or req.query_id or str(uuid.uuid4())
        schema = get_sanitized_schema(req.role.value)

        # Шаг 1: генерация SQL + оценка судьи (0..1). Самоисправление при низком score.
        raw_sql, judge_info, suggestion = await self._generate_acceptable_sql(req, schema)

        if raw_sql is None:
            code = "NEEDS_REFINEMENT" if suggestion else "SQL_REJECTED"
            msg = suggestion or (
                f"Не удалось получить логичный SQL (score < {self.settings.sql_judge_threshold}). "
                "Данные не придумываются."
            )
            return self._error(
                code, msg, query_id, start, sql="", meta=self._judge_meta(judge_info),
            )

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

        return ChatResponse(
            status="success",
            text=await self.llm.summarize(req.question, safe_sql, columns, data, req.role.value, total),
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

    async def _generate_acceptable_sql(self, req: ChatRequest, schema: str) -> tuple[str | None, dict, str]:
        """Петля: генерация + судейство + 1 самоисправление, затем сужение запроса.

        Пытаемся получить телефонно-приемлемый SQL (score >= порог). Если после
        max_sql_attempts (генерация + 1 самоисправление) не удалось — просим LLM
        предложить пользователю КАНДИДАТОВ запроса либо сузить условия.
        Возвращает (sql, judge_info, suggestion).
        """
        feedback = ""
        last_check: dict = {}
        for _ in range(self.settings.max_sql_attempts):
            sql, _ = await self.llm.generate_sql(req.question, schema, req.role.value, feedback)
            check = await self.llm.check_sql(sql, req.question, schema, req.role.value)
            last_check = check
            if check["is_valid"] and check["score"] >= self.settings.sql_judge_threshold:
                return sql, last_check, ""
            feedback = f"Предыдущий SQL нелогичен ({check['score']}): {check['reason']}. Исправь."
        # Все попытки исчерпаны -> интерактивное сужение (кандидаты / подсказка)
        suggestion = await self.llm.suggest_narrowing(req.question, schema, req.role.value, feedback)
        return None, last_check, suggestion

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

    def _error(self, code, message, query_id, start, req=None, sql="", meta=None) -> ChatResponse:
        return ChatResponse(
            status="error",
            text=f"Не удалось ответить: {message}. Данные не придумываются.",
            sql=sql,
            error=ErrorBlock(code=code, message=message),
            meta={
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "query_id": query_id,
                **({"judge": meta} if meta else {}),
            },
        )
