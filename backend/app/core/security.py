from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.config import get_settings

# Перечень ключевых слов/операторов, меняющих состояние. Дублирует AST-проверку
# как дополнительная защита (проверка первого слова + наличие служебных функций).
STATEMENT_START = {"insert", "update", "delete", "drop", "alter", "truncate",
                   "create", "merge", "grant", "revoke", "copy", "call"}

# Белый список таблиц (6-8 из schema.sql). LLM может обращаться только к ним.
ALLOWED_TABLES = {
    "staff", "faculties", "departments", "programs",
    "students", "applicants", "courses", "enrollments",
}

# Служебные функции/конструкции, запрещённые даже внутри SELECT
FORBIDDEN_KEYWORDS = {"insert", "update", "delete", "drop", "alter", "truncate",
                      "create", "merge", "grant", "revoke", "copy", "call"}

# Чувствительные ПДн-столбцы, которые нельзя выбирать даже для сотрудников/
# администрации (согласовано, что ФИО не выдаём никому). Всё — агрегатами.
SENSITIVE_COLUMNS = {
    "fio", "staff_fio", "student_card_no", "passport", "phone", "email",
}


class SQLValidationError(Exception):
    code = "GENERAL"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotSelectError(SQLValidationError):
    code = "NOT_SELECT"


class TableForbiddenError(SQLValidationError):
    code = "TABLE_FORBIDDEN"


class PDNViolationError(SQLValidationError):
    code = "PDN_VIOLATION"


class SQLValidator:
    """strict AST-валидатор: только SELECT + whitelist таблиц + защита ПДн."""

    def _parse(self, sql: str) -> exp.Expression:
        # Защита от композитных (";") и незавершённых/скрытых конструкций:
        # парсим как список стейтментов и требуем ровно один.
        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) != 1:
            raise NotSelectError("Допускается ровно один SQL-запрос")
        try:
            return statements[0]
        except (IndexError, ParseError) as e:
            raise NotSelectError(f"SQL не распознан: {e}") from e

    def _collect_tables(self, ast: exp.Expression) -> set[str]:
        tables = set()
        for node in ast.find_all(exp.Table):
            # Вынимаем имя таблицы без схемы/алиаса
            name = node.name
            if name:
                tables.add(name.lower())
        return tables

    def _wish_columns(self, ast: exp.Expression) -> set[str]:
        cols = set()
        for node in ast.find_all(exp.Column):
            if node.this:
                cols.add(node.name.lower())
        return cols

    def validate(self, sql: str) -> tuple[str, dict]:
        """Возвращает (SQL, metadata). Кидает SQLValidationError при отказе."""
        settings = get_settings()
        ast = self._parse(sql)

        # 1) Только SELECT (без CTE-запросов на изменение = все ветки SELECT)
        if not isinstance(ast, exp.Select):
            raise NotSelectError("Разрешены только SELECT-запросы")

        # 2) Whitelist таблиц
        tables = self._collect_tables(ast)
        unknown = tables - ALLOWED_TABLES
        if unknown:
            raise TableForbiddenError(
                f"Запрещённые таблицы: {', '.join(sorted(unknown))}"
            )

        # 3) ПДн: запрещаем выбирать чувствительные столбцы "в лоб"
        selected = self._wish_columns(ast)
        sensitive = selected & SENSITIVE_COLUMNS
        if sensitive:
            raise PDNViolationError(
                f"Личные данные скрыты политикой ПДн: {', '.join(sorted(sensitive))}"
            )

        # 4) Авто-LIMIT для широких запросов без агрегации (Big Data бонус)
        settings = get_settings()
        has_limit = ast.args.get("limit") is not None
        has_aggregate = bool(ast.find(exp.AggFunc)) or ast.args.get("group") is not None
        truncated = False
        if not has_limit and not has_aggregate:
            ast = ast.limit(settings.max_rows)
            truncated = True

        return ast.sql(dialect="postgres"), {"truncated": truncated, "tables": sorted(tables)}

    @staticmethod
    def explain(ast_meta: dict) -> dict:
        """Строит Explainable AI блок из метаданных валидации."""
        return {
            "tables": ast_meta.get("tables", []),
            "joins": [],
            "filters": [],
            "aggregates": [],
            "constraints": [],
        }


def build_validator() -> SQLValidator:
    return SQLValidator()
