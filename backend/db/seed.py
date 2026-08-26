"""Генерация схемы + тестового датасета в внешнем кластере.

Использование (из корня проекта, с .env):
    python -m db.seed            # создать таблицы + наполнить данными
    python -m db.seed --wipe     # пересоздать схему с нуля (дроп + create)

Детерминированный генератор (fixed seed) -> воспроизводимый датасет.
"""
from __future__ import annotations

import asyncio
import datetime
import random
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
random.seed(42)

FACULTIES = ["Информационные технологии", "Экономика", "Филология", "Физика", "Право"]
DOCTORS = ["Смирнов", "Иванова", "Петров", "Соколова", "Кузнецов", "Морозов"]
DISCIPLINES = ["Базы данных", "Алгоритмы", "Высшая математика", "Программирование",
               "Экономика", "Философия", "Статистика", "Дискретная математика"]
# Реалистичные направления подготовки по факультетам (для корректных ответов на вопросы из памятки)
PROGRAMS_BY_FACULTY = {
    "Информационные технологии": ["Информационные системы и технологии", "Программная инженерия",
                                  "Прикладная информатика"],
    "Экономика": ["Экономика", "Финансы и кредит", "Бизнес-информатика"],
    "Филология": ["Филология", "Лингвистика", "Журналистика"],
    "Физика": ["Физика", "Прикладная математика и физика", "Радиофизика"],
    "Право": ["Юриспруденция", "Правовое обеспечение национальной безопасности"],
}


def sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


async def migrate(conn: asyncpg.Connection) -> None:
    """Дропнуть и создать таблицы по schema.sql.
    schema.sql использует IF NOT EXISTS, поэтому дропаем вручную при --wipe.
    """
    for drop in (
        "DROP TABLE IF EXISTS enrollments CASCADE",
        "DROP TABLE IF EXISTS courses CASCADE",
        "DROP TABLE IF EXISTS applicants CASCADE",
        "DROP TABLE IF EXISTS students CASCADE",
        "DROP TABLE IF EXISTS programs CASCADE",
        "DROP TABLE IF EXISTS departments CASCADE",
        "DROP TABLE IF EXISTS faculties CASCADE",
        "DROP TABLE IF EXISTS staff CASCADE",
    ):
        await conn.execute(drop)
    await conn.execute(sql())


async def seed(conn: asyncpg.Connection) -> None:
    # ---- 1) Кафедры и деканы -> сотрудники ----
    dept_ids: list[int] = []
    staff_rows: list[tuple] = []
    fac_rows: list[tuple] = []
    for fac_name in FACULTIES:
        staff_rows.append((f"{random.choice(DOCTORS)} {random.choice(['А.В.','Е.С.','М.П.'])}",
                           "декан", None,
                           f"dean{fac_name[:3].lower()}@uni.ru",
                           f"+7 900 {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10,99)}"))
        fac_rows.append((fac_name, None))

    dept_rows = []
    for fac_name in FACULTIES:
        for _ in range(2):
            dept_rows.append((None, f"Кафедра {random.choice(DOCTORS)}", None))

    await conn.executemany(
        "INSERT INTO staff (fio, post, department_id, email, phone) VALUES ($1,$2,$3,$4,$5)",
        staff_rows)
    dean_ids = await conn.fetch("SELECT id FROM staff WHERE post='декан' ORDER BY id")
    dean_ids = [r["id"] for r in dean_ids]

    # проставим dean_id в faculties, а head_id в departments
    await conn.executemany(
        "INSERT INTO faculties (name, dean_id) VALUES ($1,$2)",
        [(f, dean_ids[i]) for i, f in enumerate(FACULTIES)])
    faculty_ids = await conn.fetch("SELECT id FROM faculties ORDER BY id")
    faculty_ids = [r["id"] for r in faculty_ids]

    for i, (_, dname, _) in enumerate(dept_rows):
        dept_rows[i] = (faculty_ids[i % len(faculty_ids)], dname, dean_ids[i % len(dean_ids)])
    await conn.executemany(
        "INSERT INTO departments (faculty_id, name, head_id) VALUES ($1,$2,$3)",
        dept_rows)
    dept_ids = [r["id"] for r in await conn.fetch("SELECT id FROM departments ORDER BY id")]

    # ---- Преподаватели ----
    teacher_rows = [
        (f"{random.choice(DOCTORS)} {random.choice(['Н.Н.','В.В.','Т.А.'])}", "преподаватель",
         random.choice(dept_ids), f"t{random.randint(1000,9999)}@uni.ru",
         f"+7 900 {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10,99)}")
        for _ in range(60)
    ]
    await conn.executemany(
        "INSERT INTO staff (fio, post, department_id, email, phone) VALUES ($1,$2,$3,$4,$5)",
        teacher_rows)
    teacher_ids = [r["id"] for r in await conn.fetch("SELECT id FROM staff WHERE post='преподаватель' ORDER BY id")]

    # ---- 2) Направления (реалистичные названия по факультету) ----
    names_by_fac: dict[int, list[str]] = {}
    for i, fac_name in enumerate(FACULTIES):
        names_by_fac[faculty_ids[i]] = PROGRAMS_BY_FACULTY.get(fac_name, [fac_name])
    prog_rows = []
    for route in range(len(faculty_ids) * 3):
        fac_id = faculty_ids[route % len(faculty_ids)]
        pool = names_by_fac[fac_id]
        pname = pool[route // len(faculty_ids) % len(pool)]
        prog_rows.append((fac_id,
                          f"{random.randint(9,15):02d}.{random.randint(2,4):02d}.{random.randint(2,4):02d}",
                          pname,
                          random.randint(20, 60), random.randint(10, 40),
                          random.randint(150, 250),
                          random.choice(["fulltime", "parttime"])))
    await conn.executemany(
        "INSERT INTO programs (faculty_id, code, name, budget_seats, paid_seats, min_score_prev, form) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7)",
        prog_rows)
    program_ids = [r["id"] for r in await conn.fetch("SELECT id FROM programs ORDER BY id")]

    # ---- 3) Студенты ----
    stud_rows = [
        (f"Студент {random.choice(DOCTORS)} {i}", f"SC-{random.randint(100000,999999)}",
         f"s{i}@student.uni.ru", f"+7 950 {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10,99)}",
         random.choice(program_ids), random.randint(1, 5),
         round(random.uniform(2.0, 5.0), 2),
         random.choices(["active", "expelled", "academic_leave"], weights=[90, 6, 4])[0],
         random.choices(["budget", "paid"], weights=[70, 30])[0])
        for i in range(2500)
    ]
    await conn.executemany(
        "INSERT INTO students (fio, student_card_no, email, phone, program_id, course, gpa, status, source) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
        stud_rows)
    student_ids = [r["id"] for r in await conn.fetch("SELECT id FROM students ORDER BY id")]

    # ---- 4) Абитуриенты ----
    appl_rows = [
        (f"Абитуриент {random.choice(DOCTORS)} {random.randint(1000,9999)}",
         random.choice(program_ids), random.randint(120, 280),
         datetime.date(random.choice([2025, 2026]), random.randint(6, 7), random.randint(1, 28)),
         random.choices(["submitted", "enrolled", "rejected"], weights=[60, 25, 15])[0],
         random.choices(["budget", "paid"], weights=[60, 40])[0])
        for _ in range(3000)
    ]
    await conn.executemany(
        "INSERT INTO applicants (fio, program_id, ege_score, submitted_date, status, source) "
        "VALUES ($1,$2,$3,$4,$5,$6)",
        appl_rows)

    # ---- 5) Дисциплины ----
    course_rows = [
        (random.choice(teacher_ids), random.choice(program_ids),
         random.choice(DISCIPLINES), random.choice([2, 3, 4, 5]), random.choice([1, 2]))
        for _ in range(40)
    ]
    await conn.executemany(
        "INSERT INTO courses (teacher_id, program_id, name, credits, semester) VALUES ($1,$2,$3,$4,$5)",
        course_rows)
    course_ids = [r["id"] for r in await conn.fetch("SELECT id FROM courses ORDER BY id")]

    # ---- 6) Успеваемость ----
    enrol_rows = []
    for sid in student_ids:
        for _ in range(random.randint(2, 5)):
            grade = round(random.uniform(2.0, 5.0), 2)
            enrol_rows.append((sid, random.choice(course_ids),
                               random.choice(["2025 spring", "2025 fall", "2026 spring"]),
                               grade, grade >= 3, random.randint(40, 100)))
    await conn.executemany(
        "INSERT INTO enrollments (student_id, course_id, semester, grade, passed, attendance) "
        "VALUES ($1,$2,$3,$4,$5,$6)",
        enrol_rows)

    print(f"OK. staff={len(staff_rows)+len(teacher_rows)}, faculties={len(faculty_ids)}, "
          f"departments={len(dept_ids)}, programs={len(program_ids)}, "
          f"students={len(student_ids)}, applicants={len(appl_rows)}, "
          f"courses={len(course_ids)}, enrollments={len(enrol_rows)}")


async def main() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url, command_timeout=30)
    try:
        if "--wipe" in sys.argv:
            await migrate(conn)
            print("Schema recreated.")
        else:
            await conn.execute(sql())
        await seed(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
