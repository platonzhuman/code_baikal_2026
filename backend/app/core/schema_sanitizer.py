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
    "student": {"programs", "faculties", "departments", "courses", "enrollments", "students",
                "groups"},
    "teacher": {"staff", "courses", "enrollments", "programs", "faculties", "departments",
                "groups", "schedule", "teaching_load", "rooms"},
    "staff": {"staff", "faculties", "departments", "programs", "students",
              "applicants", "courses", "enrollments", "groups", "rooms",
              "schedule", "teaching_load"},
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
    lines = [DATA_STORY, ""]
    lines.append("Схема БД — таблицы, поля и связи (доступные по роли):")
    allowed = ROLE_ALLOWED_TABLES.get(role, set())
    for table in all_tables():
        if table not in allowed:
            continue
        visible = _visible_columns(role, table)
        fks = _fks(table)
        mark = "  [только агрегаты]" if (role in ROLE_AGGREGATE_ONLY and table in LEARNER_TABLES) else ""
        lines.append(f"- {table} ({', '.join(visible)}){mark}")
        desc, col_info = TABLES_INFO.get(table, ("", {}))
        if desc:
            lines.append(f"    {desc}")
        for c in _columns(table):
            if c["name"] not in visible:
                continue
            meaning = col_info.get(c["name"], "")
            marks = []
            if c.get("is_pk"):
                marks.append("PK")
            if c.get("is_fk"):
                marks.append("FK")
            detail = f"{c['name']}({c['type']}{', ' + ', '.join(marks) if marks else ''})"
            if meaning:
                detail += f"={meaning}"
            lines.append(f"    · {detail}")

    # Связи (только для таблиц, доступных роли)
    allowed_rel = [r for r in RELATIONS if r.split(".")[0] in allowed]
    if allowed_rel:
        lines.append("СВЯЗИ: " + "; ".join(allowed_rel))

    if role in ROLE_AGGREGATE_ONLY:
        lines.append(
            "\nВАЖНО (роль: %s): по students/аpplicants/enrollments — ТОЛЬКО агрегаты "
            "(COUNT/AVG/GROUP BY); ПДн-поля недоступны." % role
        )
    return "\n".join(lines)


# ============================================================
# СЕМАНТИКА БД (что означает каждая таблица/поле, как таблицы связаны)
# ============================================================
TABLES_INFO: dict[str, tuple[str, dict[str, str]]] = {
    "faculties": (
        "факультеты университета",
        {"id": "идентификатор", "name": "название факультета",
         "dean_id": "декан"},
    ),
    "departments": (
        "кафедры, входят в факультет",
        {"id": "идентификатор", "faculty_id": "факультет",
         "name": "название кафедры", "head_id": "завкафедрой"},
    ),
    "programs": (
        "направления подготовки (специальности), закреплены за кафедрой",
        {"id": "идентификатор", "faculty_id": "факультет",
         "department_id": "кафедра (ведёт направление)",
         "code": "код направления (напр. 09.03.02)", "name": "название направления",
         "budget_seats": "бюджетные места", "paid_seats": "платные места",
         "min_score_prev": "проходной балл прошлых лет",
         "form": "форма обучения: fulltime=очная, parttime=заочная"},
    ),
    "students": (
        "обучающиеся университета (личные поля скрыты политикой ПДн)",
        {"id": "идентификатор", "program_id": "направление",
         "course": "номер курса (1..5)", "gpa": "средний балл (GPA)",
         "status": "active=учится, expelled=отчислен, academic_leave=академ. отпуск",
         "source": "budget=бюджет, paid=платно",
         "enrolled_year": "год поступления",
         "status_since_year": "год смены статуса (отчисление/академ)"},
    ),
    "applicants": (
        "абитуриенты (личные поля скрыты политикой ПДн)",
        {"id": "идентификатор", "program_id": "направление",
         "ege_score": "суммарный балл ЕГЭ", "submitted_date": "дата подачи документов",
         "status": "submitted=подан, enrolled=зачислен, rejected=отклонён",
         "source": "budget=бюджет, paid=платно"},
    ),
    "courses": (
        "дисциплины (учебные курсы)",
        {"id": "идентификатор", "teacher_id": "преподаватель",
         "program_id": "направление", "name": "название дисциплины",
         "credits": "кредиты", "semester": "номер семестра (1..2)"},
    ),
    "enrollments": (
        "успеваемость/оценки по дисциплинам (связка студентов и курсов)",
        {"id": "идентификатор", "student_id": "студент",
         "course_id": "дисциплина",
         "semester": "'<год> spring|fall' (пример '2025 spring')",
         "grade": "оценка (балл)", "passed": "сдал=true, не сдал=false",
         "attendance": "посещаемость (%)"},
    ),
    "staff": (
        "сотрудники: преподаватели, деканы, завкафедрами",
        {"id": "идентификатор", "post": "должность (декан/преподаватель/...)",
         "department_id": "кафедра → departments.id"},
    ),
    "groups": (
        "учебные группы студентов",
        {"id": "идентификатор", "name": "название группы (напр. ИВТ-101)",
         "program_id": "направление → programs.id", "course": "курс"},
    ),
    "rooms": (
        "аудитории и здания",
        {"id": "идентификатор", "name": "номер аудитории",
         "building": "корпус (А/Б)", "capacity": "вместимость",
         "faculty_id": "факультет → faculties.id"},
    ),
    "schedule": (
        "расписание занятий (аудитория+дисциплина+день+пара)",
        {"id": "идентификатор", "room_id": "аудитория → rooms.id",
         "course_id": "дисциплина → courses.id",
         "day_of_week": "день недели (Пн..Пт)", "pair": "пара (1..3)",
         "semester": "семестр <год> spring/fall"},
    ),
    "teaching_load": (
        "учебная нагрузка преподавателей (в часах)",
        {"id": "идентификатор", "staff_id": "преподаватель → staff.id",
         "course_id": "дисциплина → courses.id", "hours": "часы нагрузки",
         "semester": "семестр"},
    ),
}

# Связи между таблицами (для JOIN) — человекочитаемо
RELATIONS = [
    "departments.faculty_id → faculties.id",
    "programs.faculty_id → faculties.id",
    "programs.department_id → departments.id",
    "students.program_id → programs.id",
    "applicants.program_id → programs.id",
    "courses.program_id → programs.id",
    "courses.teacher_id → staff.id",
    "staff.department_id → departments.id",
    "enrollments.student_id → students.id",
    "enrollments.course_id → courses.id",
    "faculties.dean_id → staff.id",
    "departments.head_id → staff.id",
    "groups.program_id → programs.id",
    "students.group_id → groups.id",
    "rooms.faculty_id → faculties.id",
    "schedule.room_id → rooms.id",
    "schedule.course_id → courses.id",
    "teaching_load.staff_id → staff.id",
    "teaching_load.course_id → courses.id",
]

# Основной «сюжет» данных (для контекста)
DATA_STORY = (
    "Логика: факультеты → кафедры и направления; студенты/абитуриенты → направления; "
    "студенты → группы (groups); дисциплины → направления; успеваемость → студенты+дисциплины; "
    "аудитории (rooms) → факультеты; расписание (schedule) → аудитории+дисциплины; "
    "нагрузка преподавателей (teaching_load) → staff+дисциплины; персонал в staff."
)


# Few-shot примеры по ролям: (вопрос, корректный SQL). Столбцы/таблицы берутся из схемы.
FEW_SHOT: dict[str, list[tuple[str, str]]] = {
    "applicant": [
        ("Сколько бюджетных мест на направлении «Информационные системы и технологии»?",
         "SELECT p.name, p.budget_seats FROM programs p WHERE lower(p.name) LIKE '%информационн%' LIMIT 50"),
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
        ("Сколько студентов отчислено на факультете информационных технологий в 2024 году?",
         "SELECT f.name, COUNT(s.id) AS expelled FROM students s "
         "JOIN programs p ON s.program_id = p.id JOIN faculties f ON p.faculty_id = f.id "
         "WHERE s.status = 'expelled' AND lower(f.name) LIKE '%информационн%' "
         "AND s.status_since_year = 2024 GROUP BY f.name LIMIT 50"),
        ("Сколько студентов факультета информационных технологий сдали все экзамены во 2 семестре 2025?",
         "SELECT f.name, COUNT(DISTINCT s.id) AS passed_all FROM students s "
         "JOIN programs p ON s.program_id = p.id JOIN faculties f ON p.faculty_id = f.id "
         "WHERE f.name = 'Информационные технологии' AND s.status = 'active' AND NOT EXISTS "
         "(SELECT 1 FROM enrollments e WHERE e.student_id = s.id AND e.semester = '2025 spring' "
         "AND e.passed = false) GROUP BY f.name"),
        ("Сколько студентов учится на бюджете на факультете информационных технологий в этом году?",
         "SELECT f.name, COUNT(s.id) AS students FROM students s "
         "JOIN programs p ON s.program_id = p.id JOIN faculties f ON p.faculty_id = f.id "
         "WHERE f.name = 'Информационные технологии' AND s.status = 'active' "
         "AND s.source = 'budget' GROUP BY f.name"),
        ("Сколько должников учится на кафедре Программная инженерия?",
         "SELECT d.name, COUNT(DISTINCT e.student_id) AS debtors FROM enrollments e "
         "JOIN students s ON e.student_id = s.id JOIN programs p ON s.program_id = p.id "
         "JOIN departments d ON p.department_id = d.id "
         "WHERE e.passed = false AND lower(d.name) LIKE '%программн%инженер%' GROUP BY d.name"),
        ("Выведи топ-3 преподавателей с наибольшим количеством студентов во 2-м семестре",
         "SELECT st.id, COUNT(DISTINCT e.student_id) AS students FROM enrollments e "
         "JOIN courses c ON e.course_id = c.id JOIN staff st ON c.teacher_id = st.id "
         "WHERE e.semester = '2026 spring' GROUP BY st.id ORDER BY students DESC LIMIT 3"),
        ("Найди преподавателей, которые не ведут ни одной дисциплины в текущем семестре",
         "SELECT st.id FROM staff st WHERE st.post = 'преподаватель' AND NOT EXISTS "
         "(SELECT 1 FROM courses c WHERE c.teacher_id = st.id AND c.semester = 1)"),
        ("У какого студента из группы БИВ-211 больше всего академических задолженностей?",
         "SELECT COUNT(CASE WHEN e.passed = false THEN 1 END) AS debts FROM students s "
         "JOIN groups g ON s.group_id = g.id LEFT JOIN enrollments e ON e.student_id = s.id "
         "WHERE g.name = 'БИВ-211'"),
    ],
}

ROLE_LABEL = {"applicant": "абитуриент", "student": "студент",
              "teacher": "преподаватель", "staff": "сотрудник/администрация"}

# Словарь значений полей (русский термин -> значение в БД). КРИТИЧНО: модель не должна
# угадывать статусы/типы сама — иначе путает 'active' и 'отчислен'.
VALUE_MAP = (
    "СЛОВАРЬ ЗНАЧЕНИЙ:\n"
    "status(students): active=учится, expelled=ОТЧИСЛЕН, academic_leave=академ;\n"
    "status(applicants): submitted=подан, enrolled=зачислен, rejected=отклонён;\n"
    "source: budget=бюджет, paid=платно;\n"
    "passed: true=сдал, false=не сдал/долг;\n"
    "form: fulltime=очная, parttime=заочная;\n"
    "семестр: 1-й/осенний='... fall', 2-й/весенний='... spring' (2026  весна='2026 spring');\n"
    "годы: enrolled_year=год поступления, status_since_year=год отчисления/академа;\n"
    "факультеты: Информационные технологии, Экономика, Филология, Физика, Право (не сокращай);\n"
    "факультет→faculties.name; направление/программа→programs.name; кафедра→departments.name "
    "(или programs.department_id).\n"
    "LIKE по названиям — по КОРНЯМ (иной падеж!): «программная инженерия» → LIKE '%программн%инженер%'.\n"
    "ПО УМОЛЧАНИЮ (если в вопросе не указано):\n"
    "· год → 2026 (НЕ переспрашивай — просто бери 2026);\n"
    "· «текущий семестр»/«первый/осенний» → 1 (или '... fall'); «второй/весенний» → 2 (или '... spring');\n"
    "· «обучается/учится» → status='active' БЕЗ фильтра по году;\n"
    "· «бюджет/платно/места» без уточнения → считай ОБА;\n"
    "· «форма обучения» без указания → не фильтруй;\n"
    "· «должники/задолженность» без семестра → за ВСЕ семестры;\n"
    "· «средний балл/проходной» без уточнения → по всем направлениям.\n"
    "ТЕХНИЧЕСКОЕ:\n"
    "· НЕ используй :плейсхолдеры или $1 в SQL — подставляй конкретные значения;\n"
    "· «Базы данных» (название дисциплины) → LIKE '%баз%данн%' (падежи!).\n"
    "СИНОНИМЫ (переводи так):\n"
    "· ученик/учащийся/учат(ся)/зачислен → students; абитуриент/поступающий → applicants;\n"
    "· педагог/преподаватель/лектор → staff (post='преподаватель');\n"
    "· оценка/отметка/балл → enrollments.grade; сессия/успеваемость → enrollments;\n"
    "· направление/специальность/специализация → programs;\n"
    "· факультет/институт → faculties; кафедра/отделение → departments;\n"
    "· бюджет/бюджетник → source='budget'; платно/платник → source='paid';\n"
    "· задолженность/хвост → e.passed=false; отчислен/вылетел → status='expelled';\n"
    "· ИТ/айтишники/программисты → 'Информационные технологии';\n"
    "· «за последние N дней» → submitted_date >= (max(submitted_date) - N дней); "
    "«за последние N лет» → год >= (максимальный год - N + 1);\n"
    "· «второй семестр» → '... spring'; «первый/осенний» → '... fall';\n"
    "· группа (ИВТ-101/БИВ-211) → groups.name; аудитория/кабинет → rooms; "
    "корпус → rooms.building; расписание → schedule;\n"    "· нагрузка (часы) → teaching_load.hours; «сколько часов» → SUM(teaching_load.hours);\n"
    "· «по математике/русскому» → applicants.ege_math / ege_rus;\n"
    "· «с первой попытки» → enrollments.attempt=1; «сколько сдал с 1-й попытки» → WHERE attempt=1 AND passed;\n"
    "· ⛔ ИДЕНТИФИКАТОРЫ НЕЛЬЗЯ: вопросы «кто/у кого/список студентов» → отвечай КОЛИЧЕСТВОМ "
    "(COUNT) или агрегатом; НЕ выводи students.id / student_id / fio (запрещено).\n"
    "· «2-я пара/понедельник» → schedule.pair=2, schedule.day_of_week='Пн'."
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
        "",
        # Примеры ближе к началу — модели их заметно виднее, чем в конце.
        f"ПРИМЕРЫ (few-shot) для роли {role}:",
    ]
    for q, sql in FEW_SHOT.get(role, []):
        lines.append(f'Вопрос: "{q}"')
        lines.append(f"SQL: {sql}")
    lines.append("")
    lines.append(VALUE_MAP)
    lines.append("- Если пользователь пишет по-русски (например, «отчислен», «бюджет») — подставь "
                 "соответствующее значение из СЛОВАРЯ ЗНАЧЕНИЙ выше.")
    lines.append("")
    lines.append(get_sanitized_schema(role))
    lines.append("")
    lines.append(
        "Верни ТОЛЬКО JSON без markdown-обёрток в формате: "
        '{"sql": "<запрос>", "explanation": {"logic": "<кратко о логике запроса>"}, '
        '"score": <0..1 — насколько SQL уверенно соответствует вопросу>, '
        '"reason": "<краткая причина оценки>"}.'
    )
    return "\n".join(lines)
