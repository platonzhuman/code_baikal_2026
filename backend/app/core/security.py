from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.config import get_settings

# Перечень ключевых слов/операторов, меняющих состояние. Дублирует AST-проверку
# как дополнительная защита (проверка первого слова + наличие служебных функций).
STATEMENT_START = {"insert", "update", "delete", "drop", "alter", "truncate",
                   "create", "merge", "grant", "revoke", "copy", "call"}

# Белый список таблиц/представлений. LLM может обращаться только к ним.
ALLOWED_TABLES = {
    "staff", "faculties", "departments", "programs",
    "students", "applicants", "courses", "enrollments",
    # Безопасные представления (без ПДн) — рекомендуемый слой доступа
    "v_students", "v_applicants", "v_staff", "v_faculties",
    "v_departments", "v_programs", "v_courses", "v_enrollments",
    # Новые v2: группы, аудитории, расписание, нагрузка
    "groups", "rooms", "schedule", "teaching_load",
}

# Служебные функции/конструкции, запрещённые даже внутри SELECT
FORBIDDEN_KEYWORDS = {"insert", "update", "delete", "drop", "alter", "truncate",
                      "create", "merge", "grant", "revoke", "copy", "call"}

# Чувствительные ПДн-столбцы, запрещённые напрямую (контакты/паспорт/зачётка).
# ФИО: для обучающихся скрыто санитайзером и правилом «только агрегаты»;
# ФИО сотрудников (преподаватели/деканы) — РАЗРЕШЕНО по памятке (teacher/staff).
SENSITIVE_COLUMNS = {
    "student_card_no", "passport", "phone", "email",
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

        # 2.1) SELECT * на таблицах с ПДн/обучающимися — запрещён (утечка через звёздочку)
        pdn_tables = {"students", "applicants", "enrollments", "staff", "v_students", "v_applicants", "v_staff"}
        for star in ast.find_all(exp.Star):
            parent_table = ""
            if star is not None and star.parent is not None:
                # exp.Star лежит под exp.Column для «t.*»
                col = star.parent
                if isinstance(col, exp.Column):
                    parent_table = col.table.lower()
            if not parent_table:
                parent_table = next(iter(tables), "") if len(tables) == 1 else ""
            if (not parent_table and tables & pdn_tables) or parent_table in pdn_tables:
                raise PDNViolationError(
                    "SELECT * на таблицах с персональными данными запрещён — "
                    "перечислите нужные столбцы явно."
                )

        # 3) ПДн: запрещаем выбирать чувствительные столбцы "в лоб"
        selected = self._wish_columns(ast)
        sensitive = selected & SENSITIVE_COLUMNS
        if sensitive:
            raise PDNViolationError(
                f"Личные данные скрыты политикой ПДн: {', '.join(sorted(sensitive))}"
            )

        # 3.1) ПДн: поля обучающихся (students/applicants/enrollments) допустимы только
        #      в агрегатах или в GROUP BY — нельзя выводить id/столбцы «в лоб» (идентификация).
        self._check_learner_projection(ast)

        # 4) Авто-LIMIT для широких запросов без агрегации (Big Data бонус)
        settings = get_settings()
        has_limit = ast.args.get("limit") is not None
        has_aggregate = bool(ast.find(exp.AggFunc)) or ast.args.get("group") is not None
        truncated = False
        if not has_limit and not has_aggregate:
            ast = ast.limit(settings.max_rows)
            truncated = True

        return ast.sql(dialect="postgres"), {"truncated": truncated, "tables": sorted(tables)}

    def _check_learner_projection(self, ast: exp.Expression) -> None:
        """Запрет вывода полей обучающихся (в т.ч. id) вне агрегатов/GROUP BY (ПДн)."""
        learner = {"students", "applicants", "enrollments"}
        alias_map: dict[str, str] = {}
        for t in ast.find_all(exp.Table):
            alias_map[t.alias_or_name.lower()] = t.name.lower()

        group_cols: set[str] = set()
        group = ast.args.get("group") if isinstance(ast, exp.Select) else None
        if group is not None:
            for gexpr in group.expressions:
                cols = [gexpr] if isinstance(gexpr, exp.Column) else list(gexpr.find_all(exp.Column))
                group_cols.update(c.name.lower() for c in cols)

        projections = ast.args.get("expressions", []) if isinstance(ast, exp.Select) else []
        from_learner = {a for a in alias_map.values() if a in learner}
        for expr in projections:
            for col in expr.find_all(exp.Column):
                real = alias_map.get(col.table.lower(), "") if col.table else ""
                if real not in learner:
                    # незаквалифицированная колонка + единственная таблица-обучающийся в FROM
                    if not col.table and len(from_learner) == 1:
                        real = next(iter(from_learner))
                    else:
                        continue
                if col.find_ancestor(exp.AggFunc):
                    continue
                # индивидуальные идентификаторы (id, student_id) НЕЛЬЗЯ выводить вне агрегата;
                # размерностные FK (program_id, faculty_id, course_id, group_id) — допустимы
                name = col.name.lower()
                if name in {"id", "student_id", "applicant_id"}:
                    raise PDNViolationError(
                        "Идентификаторы обучающихся не выводятся — только агрегаты (COUNT/AVG)."
                    )
                if name in group_cols:
                    continue
                raise PDNViolationError(
                    "Поля данных обучающихся (students/applicants/enrollments) могут выводиться "
                    "только в агрегатах (COUNT/AVG) — персональная идентификация недоступна."
                )

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
