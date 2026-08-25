from __future__ import annotations

# Таблицы и их поля: (имя, тип, PK, FK, чувствительный_ПДн)
# sensitive=True -> столбец СКРЫВАЕТСЯ из схемы, отдаваемой LLM (для всех ролей).
TABLES: dict[str, list[tuple[str, str, bool, bool, bool]]] = {
    "staff": [
        ("id", "BIGSERIAL", True, False, False),
        ("fio", "TEXT", False, False, True),        # ПДн: ФИО скрыто для всех (в т.ч. администрации)
        ("post", "TEXT", False, False, False),
        ("department_id", "BIGINT", False, True, False),
        ("email", "TEXT", False, False, True),       # ПДн: контакт — скрыто
        ("phone", "TEXT", False, False, True),       # ПДн: контакт — скрыто
    ],
    "faculties": [
        ("id", "BIGSERIAL", True, False, False),
        ("name", "TEXT", False, False, False),
        ("dean_id", "BIGINT", False, True, False),
    ],
    "departments": [
        ("id", "BIGSERIAL", True, False, False),
        ("faculty_id", "BIGINT", False, True, False),
        ("name", "TEXT", False, False, False),
        ("head_id", "BIGINT", False, True, False),
    ],
    "programs": [
        ("id", "BIGSERIAL", True, False, False),
        ("faculty_id", "BIGINT", False, True, False),
        ("code", "TEXT", False, False, False),
        ("name", "TEXT", False, False, False),
        ("budget_seats", "INT", False, False, False),
        ("paid_seats", "INT", False, False, False),
        ("min_score_prev", "INT", False, False, False),
        ("form", "TEXT", False, False, False),
    ],
    "students": [
        ("id", "BIGSERIAL", True, False, False),
        ("fio", "TEXT", False, False, True),          # ПДн: СКРЫТО
        ("student_card_no", "TEXT", False, False, True),  # ПДн: СКРЫТО
        ("email", "TEXT", False, False, True),        # ПДн: СКРЫТО
        ("phone", "TEXT", False, False, True),        # ПДн: СКРЫТО
        ("program_id", "BIGINT", False, True, False),
        ("course", "INT", False, False, False),
        ("gpa", "NUMERIC", False, False, False),
        ("status", "TEXT", False, False, False),
        ("source", "TEXT", False, False, False),
    ],
    "applicants": [
        ("id", "BIGSERIAL", True, False, False),
        ("fio", "TEXT", False, False, True),          # ПДн: СКРЫТО
        ("program_id", "BIGINT", False, True, False),
        ("ege_score", "INT", False, False, False),
        ("submitted_date", "DATE", False, False, False),
        ("status", "TEXT", False, False, False),
        ("source", "TEXT", False, False, False),
    ],
    "courses": [
        ("id", "BIGSERIAL", True, False, False),
        ("teacher_id", "BIGINT", False, True, False),
        ("program_id", "BIGINT", False, True, False),
        ("name", "TEXT", False, False, False),
        ("credits", "INT", False, False, False),
        ("semester", "INT", False, False, False),
    ],
    "enrollments": [
        ("id", "BIGSERIAL", True, False, False),
        ("student_id", "BIGINT", False, True, False),
        ("course_id", "BIGINT", False, True, False),
        ("semester", "TEXT", False, False, False),
        ("grade", "NUMERIC", False, False, False),
        ("passed", "BOOL", False, False, False),
        ("attendance", "INT", False, False, False),
    ],
}

# Роли, для которых по таблицам обучающихся действует жёсткое правило «только агрегаты».
# Теперь role только applicant|staff, и обе видят обезличенную аналитику вуза.
ROLE_AGGREGATE_ONLY = {"applicant", "staff"}
# Таблицы, содержащие данные обучающихся (по ним — только агрегаты).
LEARNER_TABLES = {"students", "applicants", "enrollments"}


def _pretty(cols: list[tuple]) -> str:
    visible = [c[0] for c in cols if not c[4]]
    return ", ".join(visible)


def get_sanitized_schema(role: str) -> str:
    """Схема БД без ПДн-столбцов для передачи в LLM.

    - ПДн/контактные столбцы (sensitive=True) не перечисляются ни для какой роли.
    - Для ролей applicant/staff по таблицам обучающихся добавляется инструкция
      «только агрегаты» (обезличенная аналитика вуза).
    """
    lines = ["Схема БД (доступные для запроса поля), PK, FK — для JOIN:"]
    for table, cols in TABLES.items():
        visible = _pretty(cols)
        fk = " ".join(f"{c[0]}->FK({c[3]})" for c in cols if c[3])  # placeholder
        fks = ", ".join(c[0] for c in cols if c[3])
        mark = "  [только агрегаты]" if (role in ROLE_AGGREGATE_ONLY and table in LEARNER_TABLES) else ""
        lines.append(f"- {table} ({visible}){mark}")
        if fks:
            lines.append(f"    внешние ключи: {fks}")

    if role in ROLE_AGGREGATE_ONLY:
        lines.append(
            "\nВАЖНО (роль: %s): по таблицам students, applicants, enrollments допустимы "
            "ТОЛЬКО агрегаты (COUNT, AVG, MIN, MAX, GROUP BY). Не выбирай и не фильтруй "
            "по неагрегированным полям этих таблиц, чтобы нельзя было идентифицировать "
            "конкретного обучающегося. Поля с ПДн недоступны." % role
        )
    return "\n".join(lines)


def build_system_prompt(role: str) -> str:
    """Полный системный промпт для LLM: роль + очищенная схема + правила."""
    prompt = (
        "Ты — SQL-аналитик университета. Отвечай ТОЛЬКО валидным PostgreSQL (SELECT).\n"
        "Правила:\n"
        "- только SELECT; без INSERT/UPDATE/DELETE/DROP/ALTER;\n"
        "- обращайся только к таблицам из схемы ниже;\n"
        "- если данных нет в схеме — верни 'UNKNOWN' (не выдумывай);\n"
        "- сложные запросы: JOIN 3+ таблиц, GROUP BY, оконные функции;\n"
        "- широкий запрос (без фильтра/агрегата) — добавь LIMIT.\n\n"
        + get_sanitized_schema(role)
    )
    return prompt
