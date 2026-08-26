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
ROLE_AGGREGATE_ONLY = {"applicant", "student", "teacher", "staff"}
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


# Few-shot примеры по ролям: (вопрос, корректный SQL). Реальные данные и имена столбцов
# берутся из схемы — LLM должен подражать стилю, а не копировать условие.
FEW_SHOT: dict[str, list[tuple[str, str]]] = {
    "applicant": [
        (
            "Сколько бюджетных мест на направлении «Информационные системы и технологии»?",
            "SELECT p.name, p.budget_seats FROM programs p "
            "WHERE lower(p.name) LIKE '%информационн%' LIMIT 50",
        ),
        (
            "Какой средний проходной балл прошлого года на программы факультета ИТ?",
            "SELECT f.name, AVG(p.min_score_prev) AS avg_score FROM programs p "
            "JOIN faculties f ON p.faculty_id = f.id WHERE lower(f.name) LIKE '%информационн%' "
            "GROUP BY f.name LIMIT 50",
        ),
        (
            "Сколько заявлений подано на «Экономику» в 2026 году?",
            "SELECT p.name, COUNT(a.id) AS applications FROM applicants a "
            "JOIN programs p ON a.program_id = p.id "
            "WHERE EXTRACT(YEAR FROM a.submitted_date) = 2026 AND lower(p.name) LIKE '%экономик%' "
            "GROUP BY p.name LIMIT 50",
        ),
    ],
    "staff": [
        (
            "Сколько студентов обучается на факультете информационных технологий?",
            "SELECT f.name, COUNT(s.id) AS students FROM students s "
            "JOIN programs p ON s.program_id = p.id JOIN faculties f ON p.faculty_id = f.id "
            "WHERE lower(f.name) LIKE '%информационн%' AND s.status = 'active' GROUP BY f.name LIMIT 50",
        ),
        (
            "Какой средний GPA по факультету за весенний семестр?",
            "SELECT f.name, AVG(e.grade) AS avg_gpa FROM enrollments e "
            "JOIN courses c ON e.course_id = c.id JOIN programs p ON c.program_id = p.id "
            "JOIN faculties f ON p.faculty_id = f.id "
            "WHERE lower(e.semester) LIKE '%весн%' GROUP BY f.name LIMIT 50",
        ),
        (
            "Сколько студентов имеют академическую задолженность (не сдали экзамен)?",
            "SELECT COUNT(DISTINCT e.student_id) AS debtors FROM enrollments e "
            "WHERE e.passed = false",
        ),
    ],
}

# Имена ролей для «человеческого» заголовка в промпте
ROLE_LABEL = {"applicant": "абитуриент", "student": "студент",
              "teacher": "преподаватель", "staff": "сотрудник/администрация"}


def build_system_prompt(role: str) -> str:
    """Полный системный промпт для LLM: роль + few-shot + очищенная схема + правила."""
    lines = [
        "Ты — SQL-аналитик университета. Отвечаешь ТОЛЬКО валидным PostgreSQL (SELECT).",
        f"Твоя роль: {ROLE_LABEL.get(role, role)} ({role}).",
        "",
        "ЖЁСТКИЕ ПРАВИЛА:",
        "- только SELECT; без INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE и т.п.;",
        "- обращайся только к таблицам из схемы ниже (имена таблиц/столбцов — только из схемы);",
        "- ПДн: поля fio, email, phone, student_card_no, passport недоступны — по таблицам "
        "students, applicants, enrollments допустимы ТОЛЬКО агрегаты (COUNT, AVG, MIN, MAX, GROUP BY);",
        "- если данных нет в схеме или вопрос не про БД — верни \"UNKNOWN\" (не выдумывай);",
        "- сложные запросы: JOIN 3+ таблиц, GROUP BY, оконные функции;",
        "- широкий запрос (без фильтра/агрегата) — добавь LIMIT.",
        "- Вопросы вида «сколько студентов ОБУЧАЕТСЯ / учатся / численность студентов» — "
        "обязательно добавляй фильтр s.status='active' (считаем только активных) и группируй "
        "по факультету или направлению.",
        "- Есть безопасные представления v_students, v_applicants, v_staff, v_enrollments "
        "(без ПДн-полей) — предпочтительно использовать их вместо таблиц students/applicants/staff.",
        "",
        f"ПРИМЕРЫ (few-shot) для роли {role}:",
    ]
    for q, sql in FEW_SHOT.get(role, []):
        lines.append(f'Вопрос: "{q}"')
        lines.append(f"SQL: {sql}")
    lines.append("")
    lines.append(get_sanitized_schema(role))
    lines.append("")
    lines.append(
        "Верни ТОЛЬКО JSON без markdown-обёрток в формате: "
        '{"sql": "<запрос>", "explanation": {"logic": "<кратко о логике запроса>"}}.'
    )
    return "\n".join(lines)
