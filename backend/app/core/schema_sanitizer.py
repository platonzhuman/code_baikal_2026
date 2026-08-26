from __future__ import annotations

from typing import Optional

# ============================================================
# Схема БД теперь НЕ хардкодится — она подтягивается из каталога БД
# (schema_loader.load_schema) и сохраняется через set_schema().
# Здесь остаётся ТОЛЬКО семантическая политика:
#   - какие столбцы ПДн (по таблицам);
#   - какие таблицы «только агрегаты»;
#   - какие таблицы видит каждая роль;
#   - few-shot примеры.
# ============================================================

# Хранит загруженную структуру схемы.
_SCHEMA: dict[str, dict] = {}
_DEFAULT: dict[str, dict] = {}


def set_schema(schema: dict[str, dict]) -> None:
    global _SCHEMA
    _SCHEMA = schema or {}


def _columns(table: str) -> list[dict]:
    return _SCHEMA.get(table, {}).get("columns", [])


# --- политика ПДн: столбцы, которые скрываем (по таблицам), для любого роля ---
HIDDEN_COLUMNS: dict[str, set[str]] = {
    "students": {"fio", "student_card_no", "email", "phone", "passport"},
    "applicants": {"fio", "email", "phone", "passport"},
    "staff": {"email", "phone"},
}

# столбцы, скрытые у сотрудников, но разрешённые teacher/admin (по памятке — ФИО персонала)
STAFF_FIO_ROLES = {"teacher", "staff"}


# --- политика ролей ---
ROLE_AGGREGATE_ONLY = {"applicant", "student", "teacher", "staff"}
LEARNER_TABLES = {"students", "applicants", "enrollments"}

# какие таблицы видит каждая роль (whitelist ролей — это политика, не структура)
ROLE_ALLOWED_TABLES: dict[str, set[str]] = {
    "applicant": {"programs", "faculties", "applicants"},
    "student": {"programs", "faculties", "departments", "courses", "enrollments", "students"},
    "teacher": {"staff", "courses", "enrollments", "programs", "faculties", "departments"},
    "staff": {"staff", "faculties", "departments", "programs", "students",
              "applicants", "courses", "enrollments"},
}


def _visible_columns(role: str, table: str) -> list[str]:
    """Колонки таблицы, доступные роли (без ПДн)."""
    cols = _columns(table)
    hidden = HIDDEN_COLUMNS.get(table, set())
    out: list[str] = []
    for c in cols:
        name = c["name"]
        if name in hidden:
            continue
        if table == "staff" and name == "fio" and role not in STAFF_FIO_ROLES:
            continue
        out.append(name)
    return out


def _fks(table: str) -> list[str]:
    return [c["name"] for c in _columns(table) if c.get("is_fk")]


def all_tables() -> list[str]:
    return [t for t in _SCHEMA.keys()]


def get_sanitized_schema(role: str) -> str:
    """Очищенная схема для LLM по роли: только разрешённые таблицы + не-ПДн колонки.

    Строится из загруженной структуры БД (без хардкода таблиц/колонок).
    """
    lines = ["Схема БД (доступные для запроса поля), PK, FK — для JOIN:"]
    allowed = ROLE_ALLOWED_TABLES.get(role, set())
    for table in all_tables():
        if table not in allowed:
            continue
        visible = _visible_columns(role, table)
        fks = _fks(table)
        mark = "  [только агрегаты]" if (role in ROLE_AGGREGATE_ONLY and table in LEARNER_TABLES) else ""
        lines.append(f"- {table} ({', '.join(visible)}){mark}")
        if fks:
            lines.append(f"    внешние ключи: {', '.join(fks)}")

    if role in ROLE_AGGREGATE_ONLY:
        lines.append(
            "\nВАЖНО (роль: %s): по таблицам students, applicants, enrollments допустимы "
            "ТОЛЬКО агрегаты (COUNT, AVG, MIN, MAX, GROUP BY). Не выбирай и не фильтруй "
            "по неагрегированным полям этих таблиц, чтобы нельзя было идентифицировать "
            "конкретного обучающегося. Поля с ПДн недоступны." % role
        )
    return "\n".join(lines)


# Few-shot примеры по ролям: (вопрос, корректный SQL). Столбцы/таблицы берутся из схемы.
FEW_SHOT: dict[str, list[tuple[str, str]]] = {
    "applicant": [
        ("Сколько бюджетных мест на направлении «Информационные системы и технологии»?",
         "SELECT p.name, p.budget_seats FROM programs p WHERE lower(p.name) LIKE '%информационн%' LIMIT 50"),
        ("Какой средний проходной балл прошлого года на программы факультета ИТ?",
         "SELECT f.name, AVG(p.min_score_prev) AS avg_score FROM programs p "
         "JOIN faculties f ON p.faculty_id = f.id WHERE lower(f.name) LIKE '%информационн%' "
         "GROUP BY f.name LIMIT 50"),
        ("Сколько заявлений подано на «Экономику» в 2026 году?",
         "SELECT p.name, COUNT(a.id) AS applications FROM applicants a "
         "JOIN programs p ON a.program_id = p.id "
         "WHERE EXTRACT(YEAR FROM a.submitted_date) = 2026 AND lower(p.name) LIKE '%экономик%' "
         "GROUP BY p.name LIMIT 50"),
    ],
    "staff": [
        ("Сколько студентов обучается на факультете информационных технологий?",
         "SELECT f.name, COUNT(s.id) AS students FROM students s "
         "JOIN programs p ON s.program_id = p.id JOIN faculties f ON p.faculty_id = f.id "
         "WHERE lower(f.name) LIKE '%информационн%' AND s.status = 'active' GROUP BY f.name LIMIT 50"),
        ("Какой средний GPA по факультету за весенний семестр?",
         "SELECT f.name, AVG(e.grade) AS avg_gpa FROM enrollments e "
         "JOIN courses c ON e.course_id = c.id JOIN programs p ON c.program_id = p.id "
         "JOIN faculties f ON p.faculty_id = f.id "
         "WHERE lower(e.semester) LIKE '%весн%' GROUP BY f.name LIMIT 50"),
        ("Сколько студентов имеют академическую задолженность (не сдали экзамен)?",
         "SELECT COUNT(DISTINCT e.student_id) AS debtors FROM enrollments e WHERE e.passed = false"),
        ("Сколько студентов отчислено на факультете информационных технологий в 2024 году?",
         "SELECT f.name, COUNT(s.id) AS expelled FROM students s "
         "JOIN programs p ON s.program_id = p.id JOIN faculties f ON p.faculty_id = f.id "
         "WHERE s.status = 'expelled' AND lower(f.name) LIKE '%информационн%' "
         "AND s.status_since_year = 2024 GROUP BY f.name LIMIT 50"),
        ("Сколько абитуриентов зачислено на бюджет в 2024 году?",
         "SELECT COUNT(*) AS enrolled_budget FROM applicants a "
         "WHERE a.status = 'enrolled' AND a.source = 'budget' "
         "AND EXTRACT(YEAR FROM a.submitted_date) = 2024"),
    ],
}

ROLE_LABEL = {"applicant": "абитуриент", "student": "студент",
              "teacher": "преподаватель", "staff": "сотрудник/администрация"}

# Словарь значений полей (русский термин -> значение в БД). КРИТИЧНО: модель не должна
# угадывать статусы/типы сама — иначе путает 'active' и 'отчислен'.
VALUE_MAP = (
    "СЛОВАРЬ ЗНАЧЕНИЙ (используй ТОЛЬКО эти значения, не выдумывай):\n"
    "- students.status: активный/обучается/учится='active', ОТЧИСЛЕН='expelled', "
    "академ. отпуск='academic_leave';\n"
    "- applicants.status: подан='submitted', зачислен='enrolled', отклонён='rejected';\n"
    "- source: бюджет='budget', платно='paid';\n"
    "- enrollments.passed: сдал=true, не сдал/задолженность=false;\n"
    "- programs.form: очная='fulltime', заочная='parttime';\n"
    "- семестр в enrollments.semester содержит 'spring'/'fall' и год, напр. '2026 spring';\n"
    "- ГОДЫ для студентов: students.enrolled_year — год поступления; "
    "students.status_since_year — год изменения статуса (отчисление/академ). "
    "Для «в … году/2024 год» используй эти поля;\n"
    "- факультеты (названия ТОЧНО как в БД, не сокращай): Информационные технологии, "
    "Экономика, Филология, Физика, Право."
)


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
        VALUE_MAP,
        "- ПРАВИЛО 'active' применяй ТОЛЬКО к вопросам вида «сколько студентов ОБУЧАЕТСЯ / "
        "учатся / численность студентов»: добавляй s.status='active' и группируй по факультету. "
        "Для «ОТЧИСЛЕН» используй s.status='expelled'; для «задолженность» — e.passed=false; "
        "для «зачислен на бюджет» — a.status='enrolled' AND a.source='budget'.",
        "- Если пользователь пишет по-русски (например, «отчислен», «бюджет») — подставь "
        "соответствующее значение из СЛОВАРЯ ЗНАЧЕНИЙ выше.",
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
