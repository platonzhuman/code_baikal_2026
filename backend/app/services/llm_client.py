from __future__ import annotations

import asyncio
import json
import re

import httpx
import sqlglot
from pydantic import BaseModel, Field, ValidationError
from sqlglot import exp
from sqlglot.errors import ParseError

from app.config import get_settings
from app.core.schema_sanitizer import build_system_prompt
from app.core.security import ALLOWED_TABLES, SENSITIVE_COLUMNS


class LLMUnavailable(Exception):
    """Сетевой/API сбой при обращении к LLM."""


class LLMFormatError(Exception):
    """Ответ LLM не распознан (не JSON / нет нужных полей)."""


# ---------- Валидируемые ответы LLM (pydantic) ----------

class GenerationOutput(BaseModel):
    """Ответ генератора SQL: { "sql": "...", "explanation": {...}, "score": 0..1, "reason": "..." }."""
    sql: str = Field(..., min_length=1)
    explanation: dict = {}
    score: float = Field(default=0.9, ge=0.0, le=1.0)
    reason: str = ""


class JudgeOutput(BaseModel):
    """Ответ LLM-судьи: оценка логичности SQL 0..1."""
    score: float = Field(..., ge=0.0, le=1.0)
    reason: str = ""
    is_valid: bool = False


class NarrowingOutput(BaseModel):
    """Ответ на «сузь запрос»: подсказка + кандидаты."""
    message: str = ""
    candidates: list[str] = []


# ---------- Системные промпты для вспомогательных LLM-звеньев ----------

JUDGE_SYSTEM = (
    "Ты — строгий судья качества SQL для вопросов на естественном языке к БД университета.\n"
    "Оцени, насколько SQL соответствует вопросу пользователя и доступной схеме БД.\n"
    "Верни ТОЛЬКО JSON: {\"score\": <0..1>, \"reason\": \"<краткая причина>\", "
    "\"is_valid\": <true|false>}.\n"
    "Шкала:\n"
    "- score < 0.4: запрос не связан с вопросом, нелогичен или нарушает схему;\n"
    "- 0.4..0.79: частично корректен, есть неточности (лишние/недостающие условия);\n"
    "- score >= 0.8: запрос логичен и соответствует вопросу (is_valid=true).\n"
    "Помни про ПДн: выборка fio/email/phone/student_card_no недопустима; по таблицам "
    "students/applicants/enrollments допустимы только агрегаты."
)

NARROWING_SYSTEM = (
    "Ты — ассистент, помогающий пользователю уточнить запрос к БД университета.\n"
    "Пользователь задал вопрос, по которому невозможно построить корректный SQL "
    "(слишком общий или противоречивый). Предложи, как сузить запрос.\n"
    "Верни ТОЛЬКО JSON: {\"message\": \"<подсказка 1-2 предложения>\", "
    "\"candidates\": [\"<вариант 1>\", \"<вариант 2>\", \"<вариант 3>\"]}.\n"
    "Варианты — конкретные переформулировки вопроса пользователя "
    "(факультет, год, статус, категория, программа)."
)

SUMMARIZE_SYSTEM = (
    "Ты — ассистент университета. Пользователь задал вопрос на естественном языке, "
    "по нему выполнен SQL-запрос и получена таблица результата.\n"
    "Напиши ПОНЯТНЫЙ ответ пользователю (1-3 предложения) на русском языке, опираясь "
    "ТОЛЬКО на данные результата. Не выдумывай цифры и факты, которых нет в таблице.\n"
    "Если строк нет — так и скажи."
)


class LLMClient:
    """Клиент LLM (Lead AI, P1): генерация SQL, судья 0..1, сужение, суммаризатор.

    Режимы (`LLM_MODE` из .env):
    - `mock` — детерминированные заглушки (офлайн, для тестов/демо);
    - `real` — реальный API (OpenAI-совместимый шлюз);
    - `auto` — реальный при наличии LLM_API_KEY+LLM_MODEL, иначе mock.
    При сбое реального API генератор безопасно откатывается на mock (система жива).
    """

    def __init__(self, threshold: float | None = None, mode: str | None = None) -> None:
        s = get_settings()
        self.threshold = threshold if threshold is not None else s.sql_judge_threshold
        self.settings = s
        self.mode = (mode or s.llm_mode).lower()
        # Yandex AI Studio можно задать через LLM_* или YANDEX_CLOUD_* (fallback).
        self._api_key = (s.llm_api_key or s.yandex_cloud_api_key).strip()
        self._model = (s.llm_model or s.yandex_cloud_model).strip()
        self._base_url = (s.llm_base_url or "").strip().rstrip("/")
        self._timeout = s.llm_timeout
        self._connect_timeout = s.llm_connect_timeout
        self._retries = s.llm_max_retries
        # Авто-определение Yandex: по хосту или по ключу (AQVN...)
        self._is_yandex = (
            "yandex" in self._base_url.lower()
            or self._api_key.startswith("AQVN")
        )
        # Yandex требует URI модели вида gpt://<folder>/<model>/<version>
        if (
            self._is_yandex
            and self.settings.yandex_cloud_folder
            and self._model
            and not self._model.startswith("gpt://")
        ):
            self._model = f"gpt://{self.settings.yandex_cloud_folder}/{self._model}"
        if not self._base_url:
            self._base_url = (
                "https://llm.api.cloud.yandex.net/v1" if self._is_yandex
                else "https://api.openai.com/v1"
            )

    # ---------------- конфигурация ----------------

    @property
    def real_enabled(self) -> bool:
        """Реальный LLM активен, только если есть ключ и модель."""
        if self.mode == "mock":
            return False
        return bool(self._api_key and self._model)

    async def _call_llm(self, system: str, user: str, json_mode: bool = True) -> str:
        """OpenAI-совместимый chat/completions через httpx (async, retry).

        Yandex AI Studio использует заголовок `Api-Key`, остальные провайдеры — `Bearer`.
        """
        url = f"{self._base_url}/chat/completions"
        auth = self.settings.llm_auth.lower()
        if auth == "apikey" or (auth == "auto" and self._is_yandex):
            headers = {"Authorization": f"Api-Key {self._api_key}", "Content-Type": "application/json"}
        else:
            headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._timeout, connect=self._connect_timeout)
                ) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                # Некоторые шлюзы не поддерживают json_object -> повторим без него
                if resp.status_code in (400, 422) and json_mode:
                    return await self._call_llm(system, user, json_mode=False)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as e:
                raise LLMFormatError(f"Неожиданный формат ответа API: {e}") from e
            except httpx.HTTPStatusError as e:
                if resp.status_code in (400, 401, 403, 404, 429) and attempt == self._retries:
                    raise LLMUnavailable(f"API {resp.status_code}: {resp.text[:200]}") from e
                last_err = e
            except httpx.HTTPError as e:
                last_err = e
            except json.JSONDecodeError as e:
                raise LLMFormatError(f"Ответ API не JSON: {e}") from e
            if attempt < self._retries:
                await asyncio.sleep(min(2 ** attempt, 4))
        raise LLMUnavailable(f"LLM недоступен после {self._retries + 1} попыток: {last_err}")

    # ---------------- LLM №1: генерация SQL ----------------

    async def generate_sql(self, question: str, schema: str, role: str,
                           feedback: str = "", history: list[dict] | None = None) -> tuple[str, dict]:
        """LLM №1: вопрос -> SQL (с учётом истории разговора). Возвращает (sql, meta)."""
        if self.real_enabled:
            try:
                system = build_system_prompt(role)
                user = self._build_gen_user(question, schema, role, feedback, history)
                content = await self._call_llm(system, user)
                out = GenerationOutput.model_validate_json(self._extract_json(content))
                sql = self._sanitize_sql(out.sql)
                meta = {"model": self._model, "score": out.score, "reason": out.reason,
                        "feedback": feedback}
                if self._is_unknown(sql):
                    meta["unknown"] = True
                return sql, meta
            except (LLMUnavailable, LLMFormatError, ValidationError, json.JSONDecodeError) as e:
                # Сбой реальной модели -> безопасный откат на mock, система жива.
                sql = self._mock_generate(question, role)
                check = self._mock_check(sql)
                return sql, {"model": "mock-generator", "fallback": str(e)[:200],
                             "score": check["score"], "reason": check["reason"], "feedback": feedback}

        sql = self._mock_generate(question, role)
        check = self._mock_check(sql)
        return sql, {"model": "mock-generator", "score": check["score"],
                     "reason": check["reason"], "feedback": feedback}

    async def generate_and_judge(self, question: str, schema: str, role: str,
                                 feedback: str = "",
                                 history: list[dict] | None = None) -> tuple[str, dict]:
        """ОДИН вызов LLM: генерация + самосудья (score/reason). Возвращает (sql, meta)."""
        sql, meta = await self.generate_sql(question, schema, role, feedback, history)
        meta["is_valid"] = bool(meta.get("score", 0.0) >= self.threshold) and not self._is_unknown(sql)
        return sql, meta

    @staticmethod
    def _format_history(history: list[dict] | None) -> str:
        """Краткая история разговора для контекста (последние 4 хода)."""
        if not history:
            return ""
        lines = []
        for item in history[-4:]:
            q = (item.get("question") or "").strip()
            a = (item.get("answer") or "").strip()
            if q:
                lines.append(f"- Пользователь: {q[:120]}")
            if a:
                lines.append(f"- Ассистент: {a[:120]}")
        return "\n".join(lines)

    def _build_gen_user(self, question: str, schema: str, role: str, feedback: str,
                        history: list[dict] | None = None) -> str:
        parts = []
        hist = self._format_history(history)
        if hist:
            parts.append("ИСТОРИЯ РАЗГОВОРА (учитывай её для понимания уточнений типа «на бюджете», "
                         "«в этом году»):\n" + hist)
        parts.append(f"Вопрос: {question}")
        if feedback:
            parts.append(f"Замечание от судьи: {feedback}. Исправь SQL с учётом замечания.")
        parts.append("Схема БД (только из этих таблиц/столбцов):\n" + schema)
        parts.append('Верни ТОЛЬКО JSON: {"sql": "<postgres SELECT>", '
                     '"explanation": {"logic": "<кратко о логике>"}}. Без markdown.')
        return "\n\n".join(parts)

    def _sanitize_sql(self, sql: str) -> str:
        """Строгая проверка сгенерированного SQL (анти-галлюцинация)."""
        sql = (sql or "").strip()
        sql = re.sub(r"^```(?:sql)?\s*", "", sql).strip()
        sql = re.sub(r"\s*```$", "", sql).strip()
        sql = sql.rstrip(";").strip()
        if not sql or not sql.lower().startswith("select"):
            return "UNKNOWN"
        try:
            stmts = sqlglot.parse(sql, read="postgres")
        except ParseError:
            return "UNKNOWN"
        if len(stmts) != 1 or not isinstance(stmts[0], exp.Select):
            return "UNKNOWN"
        tables = {t.name.lower() for t in stmts[0].find_all(exp.Table)}
        if tables and not tables <= ALLOWED_TABLES:
            return "UNKNOWN"
        cols = {c.name.lower() for c in stmts[0].find_all(exp.Column)}
        if cols & SENSITIVE_COLUMNS:
            return "UNKNOWN"
        return sql

    @staticmethod
    def _is_unknown(sql: str) -> bool:
        return (sql or "").upper() == "UNKNOWN"

    # ---------------- LLM-судья 0..1 ----------------

    async def check_sql(self, sql: str, question: str, schema: str, role: str) -> dict:
        """LLM-судья: оценка логичности SQL 0..1.

        Возвращает {"score": float, "reason": str, "is_valid": bool}.
        Жёсткие AST-проверки (SELECT/whitelist/ПДн) выполняются локально и всегда
        имеют приоритет — это третья линия защиты до обращения к LLM.
        """
        hard = self._hard_gate(sql)
        if hard is not None:
            return hard

        if self.real_enabled:
            try:
                system = JUDGE_SYSTEM
                user = (
                    f"Вопрос пользователя: {question}\n\n"
                    f"SQL: {sql}\n\nДоступная схема БД:\n{schema}"
                )
                content = await self._call_llm(system, user)
                out = JudgeOutput.model_validate_json(self._extract_json(content))
                is_valid = bool(out.is_valid or out.score >= self.threshold)
                return {"score": round(out.score, 3), "reason": out.reason, "is_valid": is_valid}
            except (LLMUnavailable, LLMFormatError, ValidationError, json.JSONDecodeError):
                return self._mock_check(sql)

        return self._mock_check(sql)

    def _hard_gate(self, sql: str) -> dict | None:
        """Локальные проверки: SELECT / один стейтмент / whitelist / ПДн."""
        if not sql:
            return {"score": 0.0, "reason": "пустой SQL", "is_valid": False}
        try:
            stmts = sqlglot.parse(sql, read="postgres")
        except ParseError:
            return {"score": 0.1, "reason": "SQL не парсится", "is_valid": False}
        if len(stmts) != 1 or not isinstance(stmts[0], exp.Select):
            return {"score": 0.1, "reason": "не SELECT / несколько инструкций", "is_valid": False}
        tables = {t.name.lower() for t in stmts[0].find_all(exp.Table)}
        if not tables:
            return {"score": 0.2, "reason": "нет таблиц", "is_valid": False}
        if not tables <= ALLOWED_TABLES:
            return {"score": 0.2, "reason": "таблицы вне whitelist", "is_valid": False}
        cols = {c.name.lower() for c in stmts[0].find_all(exp.Column)}
        if cols & SENSITIVE_COLUMNS:
            return {"score": 0.1, "reason": "выборка ПДн-столбцов запрещена", "is_valid": False}
        return None

    # ---------------- сужение запроса ----------------

    async def suggest_narrowing(self, question: str, schema: str, role: str, feedback: str = "") -> str:
        """Подсказка пользователю, как сузить слишком общий/противоречивый запрос.

        Возвращает человекочитаемое сообщение: короткая просьба уточнить + варианты
        по порядку (каждый в отдельной строке), БЕЗ технических деталей из судьи.
        """
        if self.real_enabled:
            try:
                system = NARROWING_SYSTEM
                user = f"Вопрос: {question}\nЗамечание: {feedback}\nСхема:\n{schema}"
                content = await self._call_llm(system, user)
                out = NarrowingOutput.model_validate_json(self._extract_json(content))
                return self._format_narrowing(out.message, out.candidates)
            except (LLMUnavailable, LLMFormatError, ValidationError, json.JSONDecodeError):
                return self._fallback_narrowing()
        return self._fallback_narrowing()

    @staticmethod
    def _format_narrowing(message: str, candidates: list[str]) -> str:
        msg = (message or "Уточните, пожалуйста, условия запроса.").strip()
        if candidates:
            lines = "\n".join(f"{i + 1}) {c.strip()}" for i, c in enumerate(candidates) if c.strip())
            msg = f"{msg}\n\nМогу уточнить:\n{lines}"
        return msg

    @staticmethod
    def _fallback_narrowing() -> str:
        # Без технических деталей (фидбек судьи пользователю не показываем).
        return ("Не хватает данных, чтобы построить запрос. Уточните, пожалуйста: "
                "факультет, год, категорию или статус — и я пересоберу запрос.")

    # ---------------- суммаризатор ----------------

    async def summarize(
        self,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict],
        role: str = "",
        row_count: int | None = None,
    ) -> str:
        """Таблица результата -> понятный человеческий текст."""
        if self.real_enabled:
            try:
                system = SUMMARIZE_SYSTEM
                table = self._rows_to_text(columns, rows)
                user = f"Вопрос: {question}\n\nSQL: {sql}\n\nРезультат:\n{table}"
                content = await self._call_llm(system, user, json_mode=False)
                text = (content or "").strip().strip('"')
                if text:
                    return text
            except (LLMUnavailable, LLMFormatError, httpx.HTTPError):
                pass
        n = len(rows) if row_count is None else row_count
        return (
            f"По запросу «{question}» найдено записей: {n}. "
            "Данные приведены в агрегированном виде."
        )

    @staticmethod
    def _rows_to_text(columns: list[str], rows: list[dict], max_rows: int = 15) -> str:
        if not columns or not rows:
            return "(пусто)"
        lines = [", ".join(str(c) for c in columns)]
        for r in rows[:max_rows]:
            lines.append(", ".join(str(r.get(c, "")) for c in columns))
        return "\n".join(lines)

    # ---------------- Explainable AI ----------------

    def explain_sql(self, sql: str) -> dict:
        """Структурированное объяснение SQL (tables/joins/filters/aggregates/constraints)."""
        empty = {"tables": [], "joins": [], "filters": [], "aggregates": [], "constraints": []}
        try:
            ast = sqlglot.parse_one(sql, read="postgres")
        except ParseError:
            return empty
        if not isinstance(ast, exp.Select):
            return empty

        tables = sorted({t.name.lower() for t in ast.find_all(exp.Table)})

        joins: list[str] = []
        for j in ast.find_all(exp.Join):
            right = j.this.name if isinstance(j.this, exp.Table) else j.this.sql(dialect="postgres")
            on = j.args.get("on")
            joins.append(f"JOIN {right} ON {on.sql(dialect='postgres')}" if on is not None else f"JOIN {right}")

        filters: list[str] = []
        where = ast.args.get("where")
        if where is not None:
            for node in where.find_all(exp.Predicate):
                f = node.sql(dialect="postgres")
                if f not in filters:
                    filters.append(f)
            if not filters:
                filters.append(where.sql(dialect="postgres"))

        aggregates: list[str] = []
        for a in ast.find_all(exp.AggFunc):
            s = a.sql(dialect="postgres")
            if s not in aggregates:
                aggregates.append(s)
        group = ast.args.get("group")
        if group is not None:
            aggregates.append("GROUP BY " + group.sql(dialect="postgres"))

        constraints: list[str] = []
        limit = ast.args.get("limit")
        if limit is not None:
            constraints.append("LIMIT " + limit.sql())
        if ast.args.get("distinct") is not None:
            constraints.append("DISTINCT")
        if not constraints:
            constraints.append("нет")

        return {
            "tables": tables,
            "joins": joins,
            "filters": filters,
            "aggregates": aggregates,
            "constraints": constraints,
        }

    # ---------------- вспомогательное ----------------

    @staticmethod
    def _extract_json(content: str) -> str:
        """Вытаскиваем JSON из ответа LLM (устойчиво к markdown-обёрткам)."""
        if not content:
            raise json.JSONDecodeError("пустой ответ", "", 0)
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return content[start:end + 1]
        return content

    # ---------------- mock-заглушки (офлайн-режим) ----------------

    def _mock_generate(self, question: str, role: str) -> str:
        """Детерминированный генератор для демо/тестов без API."""
        q = question.lower()

        # Приёмная кампания / заявления
        if any(k in q for k in ("заявлен", "подано", "подач")) and "студент" not in q:
            m = re.search(r"20\d{2}", q)
            year = m.group(0) if m else None
            if "экономик" in q:
                cond = f"EXTRACT(YEAR FROM a.submitted_date) = {year} AND " if year else ""
                return (f"SELECT p.name, COUNT(a.id) AS applications FROM applicants a "
                        f"JOIN programs p ON a.program_id = p.id WHERE {cond}lower(p.name) "
                        f"LIKE '%экономик%' GROUP BY p.name LIMIT 50")
            if year:
                return (f"SELECT p.name, COUNT(a.id) AS applications FROM applicants a "
                        f"JOIN programs p ON a.program_id = p.id "
                        f"WHERE EXTRACT(YEAR FROM a.submitted_date) = {year} "
                        f"GROUP BY p.name ORDER BY applications DESC LIMIT 50")
            return ("SELECT p.name, COUNT(a.id) AS applications FROM applicants a "
                    "JOIN programs p ON a.program_id = p.id "
                    "GROUP BY p.name ORDER BY applications DESC LIMIT 50")

        # Средний балл / ЕГЭ / GPA / проходной
        if any(k in q for k in ("средн", "балл", "gpa", "егэ")):
            if "егэ" in q or "абитуриент" in q:
                return ("SELECT p.name, AVG(a.ege_score) AS avg_ege FROM applicants a "
                        "JOIN programs p ON a.program_id = p.id GROUP BY p.name LIMIT 50")
            if any(k in q for k in ("проходн", "прошлого год", "миним")):
                return ("SELECT p.name, AVG(p.min_score_prev) AS avg_min_score FROM programs p "
                        "GROUP BY p.name LIMIT 50")
            if any(k in q for k in ("семестр", "успеваемост")):
                return ("SELECT p.name, AVG(e.grade) AS avg_grade FROM enrollments e "
                        "JOIN courses c ON e.course_id = c.id JOIN programs p ON c.program_id = p.id "
                        "GROUP BY p.name LIMIT 50")
            return ("SELECT p.name, AVG(s.gpa) AS avg_gpa FROM students s "
                    "JOIN programs p ON s.program_id = p.id GROUP BY p.name LIMIT 50")

        # Задолженности / не сдали экзамен
        if any(k in q for k in ("задолжен", "не сдал", "не сдали", "неаттест", "долг")):
            return ("SELECT c.name, COUNT(DISTINCT e.student_id) AS debtors FROM enrollments e "
                    "JOIN courses c ON e.course_id = c.id WHERE e.passed = false "
                    "GROUP BY c.name LIMIT 50")

        # Студенты: численность / динамика
        if "студент" in q and any(k in q for k in ("сколько", "численн", "обуча", "учится", "динамик")):
            if any(k in q for k in ("факультет", "кафедр", "программ")):
                return ("SELECT f.name, COUNT(s.id) AS students FROM students s "
                        "JOIN programs p ON s.program_id = p.id "
                        "JOIN faculties f ON p.faculty_id = f.id "
                        "WHERE s.status = 'active' GROUP BY f.name LIMIT 50")
            return ("SELECT p.name, COUNT(s.id) AS students FROM students s "
                    "JOIN programs p ON s.program_id = p.id GROUP BY p.name LIMIT 50")

        # Кафедры / преподаватели / нагрузка
        if any(k in q for k in ("кафедр", "преподавател", "нагрузка", "декан")):
            return ("SELECT d.name, COUNT(s.id) AS staff_count FROM staff s "
                    "JOIN departments d ON s.department_id = d.id "
                    "GROUP BY d.name ORDER BY staff_count DESC LIMIT 50")

        # Бюджетные / платные места
        if any(k in q for k in ("мест", "бюджет", "платн")):
            return ("SELECT p.name, p.budget_seats, p.paid_seats FROM programs p "
                    "WHERE p.budget_seats > 0 OR p.paid_seats > 0 LIMIT 50")

        # Направления / программы / факультеты
        if any(k in q for k in ("направлен", "программ", "специальност", "факультет")):
            return ("SELECT f.name, p.code, p.name AS program, p.form FROM programs p "
                    "JOIN faculties f ON p.faculty_id = f.id LIMIT 50")

        return "SELECT name FROM programs LIMIT 50"

    def _mock_check(self, sql: str) -> dict:
        """Эвристическая оценка 0..1 как stand-in для LLM-судьи."""
        hard = self._hard_gate(sql)
        if hard is not None:
            return hard
        stmts = sqlglot.parse(sql, read="postgres")
        has_agg = bool(stmts[0].find(exp.AggFunc)) or stmts[0].args.get("group") is not None
        score = 0.95 if has_agg else 0.90
        return {"score": score, "reason": "корректный SELECT, таблицы в whitelist", "is_valid": True}


def build_client() -> LLMClient:
    return LLMClient()