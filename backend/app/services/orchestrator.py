from __future__ import annotations

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

    async def chat(self, req: ChatRequest) -> ChatResponse:
        start = time.perf_counter()
        query_id = str(uuid.uuid4())
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
            # Шаг 2: жёсткая безопасность (AST) + выполнение в READ ONLY
            safe_sql, meta = self.validator.validate(raw_sql)
            rows = await self.db.fetch_readonly(safe_sql)
        except SQLValidationError as e:
            return self._error(e.code, e.message, query_id, start, sql=raw_sql)
        except Exception as e:
            return self._error("DB_EXECUTION", f"Ошибка выполнения запроса: {e}", query_id, start, sql=safe_sql)

        columns = list(rows[0].keys()) if rows else []
        data = [dict(r) for r in rows[: req.max_rows]]

        truncated = meta.get("truncated", False)
        # Пустой результат → дружелюбное сообщение (не «0 записей»)
        if not rows:
            return self._error(
                "EMPTY_RESULT",
                "По вашему запросу ничего не найдено. Уточните, пожалуйста, критерии "
                "(факультет, год, категория, статус) — и я пересоберу запрос.",
                query_id, start, sql=safe_sql, meta=self._judge_meta(judge_info),
            )

        return ChatResponse(
            status="success",
            text=self._summarize(req.question, len(rows)),
            sql=safe_sql,
            result=ResultBlock(
                columns=columns,
                rows=data,
                row_count=len(rows),
                truncated=truncated,
                warning=("Запрос широкий, показаны первые строки" if truncated else None),
                suggested_filters=self._suggest_filters(meta),
            ),
            explanation=self._explain(meta),
            meta={
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "query_id": query_id,
                "judge": self._judge_meta(judge_info),
            },
        )

    def _suggest_filters(self, meta: dict) -> list[dict[str, str]] | None:
        """Уточняющие фильтры для «широкого» запроса (Big Data бонус)."""
        if not meta.get("truncated"):
            return None
        return [
            {"field": "faculty", "label": "Факультет"},
            {"field": "year", "label": "Год"},
            {"field": "status", "label": "Статус"},
        ]

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

    def _summarize(self, question: str, row_count: int) -> str:
        return (f"По запросу «{question}» найдено записей: {row_count}. "
                "Данные приведены в агрегированном виде.")

    def _explain(self, meta: dict) -> ExplanationBlock:
        e = self.validator.explain(meta)
        return ExplanationBlock(
            tables=e["tables"],
            joins=e["joins"],
            filters=e["filters"],
            aggregates=e["aggregates"],
            constraints=e["constraints"],
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
