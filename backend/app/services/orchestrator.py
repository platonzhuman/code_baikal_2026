from __future__ import annotations

import asyncio
import math
import time
import uuid

import structlog

from app.config import get_settings
from app.core.db import Database
from app.core.logging import emit
from app.core.schemas import ChatRequest, ChatResponse, ErrorBlock, ExplanationBlock, ResultBlock
from app.core.schema_sanitizer import get_sanitized_schema
from app.core.security import SQLValidationError, build_validator
from app.services.llm_client import LLMClient

# ---- Отказы (ясные, а не «уточните») ----
_DESTRUCTIVE_VERBS = (
    "удалит", "удали", "снести", "снеси", "изменит", "измени", "обнови", "встав",
    "создай", "очисти", "стерет", "убить", "удалить",
    "добав", "внеси", "внести", "поменяй", "смени", "поправь", "переимен",
    "подставь", "переменную",
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
    "паспорт", "телефон", "почт", "email", "личные данн", "персональн",
    "фио студент", "фио абитуриент", "фио всех", "зачётк", "студенч", "паспортн",
    "имена", "именами", "именем", "имя ", "имена студентов", "их имен",
    "лучших студент", "список студент", "топ-5 студент", "топ-10 студент",
    "контакт",
)

# Намерение «про студентов» (для сторожа «не считай студентов через staff»)
_STUDENT_INTENT = ("должн", "задолжен", "сдал", "экзамен", "студент", "учится",
                   "учатся", "балл", "успеваем", "получили")


def _sql_is_fishy(question: str, sql: str) -> bool:
    """Сторож: если вопрос про студентов/должников, а SQL считает по staff — ловим."""
    q = (question or "").lower()
    su = (sql or "").lower()
    if not any(w in q for w in _STUDENT_INTENT):
        return False
    uses_staff = (" staff" in su) or ("from staff" in su) or ("join staff" in su)
    uses_students = ("students" in su) or ("enrollments" in su)
    return uses_staff and not uses_students


def _sql_has_star(sql: str) -> bool:
    """SELECT * / t.* — нельзя (утечка ПДн); ловим до валидатора для автоперегенерации."""
    su = (sql or "").lower()
    return ("select *" in su) or (" .*" in su) or (".* " in su) or su.strip().startswith("select *")


def _is_destructive(question: str) -> bool:
    q = (question or "").lower()
    return any(v in q for v in _DESTRUCTIVE_VERBS)


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _log_timings(query_id: str, role: str, status: str, timings: dict, start: float) -> None:
    """Структурированное событие: спаны этапов (спецификация логирования)."""
    total_ms = round((time.perf_counter() - start) * 1000, 1)
    spans = [{"component": k, "duration_ms": v} for k, v in timings.items()]
    emit(status_to_level(status), "orchestrator", "chat_spans",
         trace_id=query_id, query_id=query_id, role=role,
         data={"status": status, "spans": spans, "total_ms": total_ms})
    if total_ms > 8000:
        emit("WARN", "orchestrator", "chat_slow", trace_id=query_id, query_id=query_id,
             role=role, data={"total_ms": total_ms, "spans": spans})


def status_to_level(status: str) -> str:
    return "ERROR" if status and "error" in str(status) else ("WARN" if "cached" in str(status) else "INFO")


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
        timings: dict[str, float] = {}

        # Кэш: повторный вопрос той же роли — мгновенно (без LLM/БД).
        if not history:
            _t = time.perf_counter()
            cached = await self._cached(req.role.value, req.question)
            timings["cache_check"] = _ms(_t)
            if cached is not None:
                _log_timings(query_id, req.role.value, "success(cached)", timings, start)
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
        _t = time.perf_counter()
        raw_sql, judge_info, suggestion = await self._generate_sql_candidate(req, schema, history)
        timings["llm_gen"] = _ms(_t)

        if raw_sql is None:
            msg = suggestion or "Уточните, пожалуйста, условия запроса — и я пересоберу его."
            return self._error("NEEDS_REFINEMENT", msg, query_id, start, sql="",
                               meta=self._judge_meta(judge_info))

        try:
            # Шаг 2: жёсткая безопасность (AST) — только SELECT/whitelist/ПДн.
            _t = time.perf_counter()
            safe_sql, meta = self.validator.validate(raw_sql)
            timings["ast"] = _ms(_t)
        except SQLValidationError as e:
            return self._error(e.code, e.message, query_id, start, sql=raw_sql)

        # Шаг 3-4: EXPLAIN + COUNT + выборка — ПАРАЛЛЕЛЬНО (экономия ~2 сек на сети к БД).
        page_size = req.max_rows

        async def _timed(key, coro):
            t0 = time.perf_counter()
            try:
                r = await coro
                timings[key] = _ms(t0)
                return r, None
            except Exception as e:
                timings[key] = _ms(t0)
                return None, e

        plan_r, count_r, rows_r = await asyncio.gather(
            _timed("explain", self.db.explain(safe_sql)),
            _timed("count", self._count_rows(safe_sql)),
            _timed("fetch", self.db.fetch_readonly(self._page_sql(safe_sql, max(req.page, 1), page_size))),
        )
        plan, plan_err = plan_r
        total, count_err = count_r
        page_rows, fetch_err = rows_r
        if count_err is not None:
            return self._error("DB_EXECUTION", f"Ошибка подсчёта строк: {count_err}",
                               query_id, start, sql=safe_sql)
        if fetch_err is not None:
            return self._error("DB_EXECUTION", f"Ошибка выполнения запроса: {fetch_err}",
                               query_id, start, sql=safe_sql)
        total = int(total)

        if plan.get("total_cost", 0.0) > self.settings.explain_max_cost:
            return self._error(
                "NEEDS_REFINEMENT",
                "Запрос оценивается как слишком дорогой. Уточните условия (факультет, год, "
                "категория, статус), чтобы я построил более дешёвый запрос.",
                query_id, start, sql=safe_sql, meta=self._judge_meta(judge_info),
            )

        truncated = meta.get("truncated", False)
        if total == 0:
            return self._error(
                "EMPTY_RESULT",
                "По вашему запросу ничего не найдено. Уточните, пожалуйста, критерии "
                "(факультет, год, категория, статус) — и я пересоберу запрос.",
                query_id, start, sql=safe_sql, meta=self._judge_meta(judge_info),
            )

        # Пагинация: уточняем страницу по общему числу (перезапрос только если вышли за диапазон).
        total_pages = max(1, math.ceil(total / page_size))
        page = min(max(req.page, 1), total_pages)
        if page != max(req.page, 1):
            _t = time.perf_counter()
            page_rows = await self.db.fetch_readonly(self._page_sql(safe_sql, page, page_size))
            timings["fetch"] = timings.get("fetch", 0.0) + _ms(_t)

        columns = list(page_rows[0].keys()) if page_rows else []
        data = [dict(r) for r in page_rows]
        timings["summarize"] = 0

        _log_timings(query_id, req.role.value, "success", timings, start)

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
        """Страница из БД. Если в SQL уже есть LIMIT (топ-N из модели) и он ≤ page_size —
        сохраняем его (иначе пагинация перезаписывает и топ-1/топ-3 теряются)."""
        import sqlglot
        parsed = sqlglot.parse_one(sql, read="postgres")
        limit = parsed.args.get("limit")
        model_limit = None
        if limit is not None:
            expr = limit.expression
            if expr is not None and expr.is_number:
                model_limit = int(expr.this)
        base = Orchestrator._remove_limit_and_order(sql)
        offset = (page - 1) * page_size
        if model_limit is not None and model_limit <= page_size and model_limit > 0:
            return f"{base} LIMIT {model_limit} OFFSET {offset}"
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
                  and meta.get("score", 0.0) >= self.settings.sql_judge_threshold
                  and not _sql_is_fishy(req.question, sql)
                  and not _sql_has_star(sql))
            if ok:
                return sql, meta, ""
            if _sql_has_star(sql):
                feedback = ("Ошибка: использование SELECT * (звёздочки) ЗАПРЕЩЕНО — "
                            "перечисли нужные столбцы явно, без *.")
            elif _sql_is_fishy(req.question, sql):
                feedback = ("Ошибка: подсчёт СТУДЕНТОВ (должники/задолженность/сдал/учится) "
                            "иди через students/enrollments (enrollments.passed=false), "
                            "НЕ через staff/departments.")
            else:
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
