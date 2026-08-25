"""Пул вопросов по ролям (applicant / staff) для демо и тестов (Lead AI, P1).

Каждый элемент: {"question": str, "keywords": tuple[str, ...]} — keywords задают,
какие таблицы/агрегаты ожидаются в SQL (для быстрой проверки формата).
"""

POOL: dict[str, list[dict]] = {
    "applicant": [
        {
            "question": "Сколько бюджетных мест на направлении «Информационные системы и технологии»?",
            "keywords": ("budget_seats", "programs"),
        },
        {
            "question": "Какой средний проходной балл прошлого года на программы факультета ИТ?",
            "keywords": ("min_score_prev", "AVG"),
        },
        {
            "question": "Сколько заявлений подано на «Экономику» в 2026 году?",
            "keywords": ("applicants", "COUNT"),
        },
        {
            "question": "Какие направления подготовки есть на факультете ИТ?",
            "keywords": ("programs", "faculties"),
        },
        {
            "question": "Сколько платных мест на программе «Прикладная информатика»?",
            "keywords": ("paid_seats", "programs"),
        },
    ],
    "staff": [
        {
            "question": "Сколько студентов обучается на факультете информационных технологий?",
            "keywords": ("students", "COUNT"),
        },
        {
            "question": "Какой средний GPA по факультету за весенний семестр?",
            "keywords": ("enrollments", "AVG"),
        },
        {
            "question": "Сколько студентов имеют академическую задолженность (не сдали экзамен)?",
            "keywords": ("enrollments", "passed"),
        },
        {
            "question": "Какой средний балл ЕГЭ у абитуриентов, подавших документы в 2025 году?",
            "keywords": ("applicants", "AVG"),
        },
        {
            "question": "Покажи динамику набора студентов по факультетам",
            "keywords": ("students", "GROUP BY"),
        },
        {
            "question": "Какая кафедра имеет наибольшее количество преподавателей?",
            "keywords": ("staff", "departments"),
        },
    ],
}


def pool_for(role: str) -> list[dict]:
    """Вопросы для конкретной роли."""
    return POOL.get(role, [])


def all_questions() -> list[dict]:
    """Все вопросы с пометкой роли: {"role": ..., "question": ..., "keywords": ...}."""
    return [dict(item, role=r) for r, qs in POOL.items() for item in qs]