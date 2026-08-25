from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.config import get_settings
from app.core.security import ALLOWED_TABLES
from app.core.schema_sanitizer import build_system_prompt


class LLMClient:
    """Клиент LLM: генерация SQL + оценка логичности (LLM-судья, 0..1).

    Пока используются детерминированные заглушки, чтобы контракт и ветки
    работали без реального API. Реальную модель подключает Lead AI (P1).
    """

    def __init__(self, threshold: float | None = None) -> None:
        s = get_settings()
        self.threshold = threshold if threshold is not None else s.sql_judge_threshold

    async def generate_sql(self, question: str, schema: str, role: str, feedback: str = "") -> tuple[str, dict]:
        """LLM №1: вопрос -> SQL. Возвращает (sql, meta)."""
        # Реальная реализация P1: вызов модели по build_system_prompt(role).
        sql = self._mock_generate(question, role)
        return sql, {"model": "mock-generator", "feedback": feedback}

    async def check_sql(self, sql: str, question: str, schema: str, role: str) -> dict:
        """LLM-судья: оценивает логичность SQL от 0 до 1.

        Возвращает {"score": float, "reason": str, "is_valid": bool}.
        """
        # Реальная реализация P1: вызвать модель с промптом «оцени SQL на согласованность
        # с вопросом и схемой, дай score 0..1 и reason». Заглушка — эвристика на основе AST.
        return self._mock_check(sql)

    async def suggest_narrowing(self, question: str, schema: str, role: str, feedback: str = "") -> str:
        """LLM читает исходный вопрос и предлагает пользователю, как его сузить.

        Вызывается, когда после самоисправления (≤ N) запрос всё равно нелогичен
        или слишком дорог по стоимости/времени. Возвращает подсказку для пользователя.
        """
        # Реальная реализация P1: «По вопросу ... и ошибке ... предложи 1-2 варианта,
        # как уточнить (факультет/год/категория/статус), чтобы я построил корректный запрос».
        return ("Запрос получился слишком общим или противоречивым. Уточни, пожалуйста, "
                "критерии: факультет, год, категорию или статус — и я пересоберу запрос. "
                f"Подсказка от проверки: {feedback}")

    # ---------------- заглушки ----------------
    def _mock_generate(self, question: str, role: str) -> str:
        q = question.lower()
        if "средн" in q or "балл" in q or "gpa" in q:
            return ("SELECT p.name, AVG(e.grade) AS gpa FROM enrollments e "
                    "JOIN courses c ON e.course_id=c.id JOIN programs p ON c.program_id=p.id "
                    "GROUP BY p.name LIMIT 50")
        if "сколько" in q or "заявлен" in q or "мест" in q:
            return ("SELECT p.name, COUNT(*) AS cnt FROM applicants a "
                    "JOIN programs p ON a.program_id=p.id WHERE a.status='submitted' "
                    "GROUP BY p.name LIMIT 50")
        return "SELECT name FROM programs LIMIT 50"

    def _mock_check(self, sql: str) -> dict:
        """Эвристическая оценка 0..1 как stand-in для LLM-судьи."""
        try:
            stmts = sqlglot.parse(sql, read="postgres")
            if len(stmts) != 1 or not isinstance(stmts[0], exp.Select):
                return {"score": 0.1, "reason": "не SELECT / несколько инструкций", "is_valid": False}
            tables = {t.name.lower() for t in stmts[0].find_all(exp.Table)}
            if not tables:
                return {"score": 0.2, "reason": "нет таблиц", "is_valid": False}
            if not tables <= ALLOWED_TABLES:
                return {"score": 0.2, "reason": "таблицы вне whitelist", "is_valid": False}
            has_agg = bool(stmts[0].find(exp.AggFunc)) or stmts[0].args.get("group") is not None
            score = 0.95 if has_agg else 0.90
            return {"score": score, "reason": "корректный SELECT, таблицы в whitelist", "is_valid": True}
        except ParseError:
            return {"score": 0.1, "reason": "SQL не парсится", "is_valid": False}


def build_client() -> LLMClient:
    return LLMClient()
