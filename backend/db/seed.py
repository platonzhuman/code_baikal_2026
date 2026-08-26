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
    "Экономика": ["Национальная экономика", "Финансы и кредит", "Бизнес-информатика"],
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
        "DROP TABLE IF EXISTS teaching_load CASCADE",
        "DROP TABLE IF EXISTS schedule CASCADE",
        "DROP TABLE IF EXISTS rooms CASCADE",
        "DROP TABLE IF EXISTS groups CASCADE",
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
    # Реалистичные названия кафедр по факультетам (2 на факультет)
    DEPTS_BY_FACULTY = {
        "Информационные технологии": ["Кафедра программной инженерии", "Кафедра информационных систем"],
        "Экономика": ["Кафедра экономики", "Кафедра финансов и кредита"],
        "Филология": ["Кафедра филологии", "Кафедра лингвистики"],
        "Физика": ["Кафедра физики", "Кафедра прикладной математики"],
        "Право": ["Кафедра права", "Кафедра юридических наук"],
    }
    for fac_name in FACULTIES:
        for dname in DEPTS_BY_FACULTY.get(fac_name, ["Кафедра"]):
            dept_rows.append((None, dname, None))

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
        # 2 кафедры на факультет -> i // 2 (именно i//2, а не i%5 — иначе сдвиг!)
        dept_rows[i] = (faculty_ids[i // 2], dname, dean_ids[i // 2])
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

    # ---- 2) Направления (реалистичные названия по факультету + кафедра) ----
    names_by_fac: dict[int, list[str]] = {}
    for i, fac_name in enumerate(FACULTIES):
        names_by_fac[faculty_ids[i]] = PROGRAMS_BY_FACULTY.get(fac_name, [fac_name])
    # кафедры по факультету (id -> список id кафедр)
    depts_rows_db = await conn.fetch("SELECT id, faculty_id FROM departments ORDER BY id")
    depts_by_fac: dict[int, list[int]] = {}
    for r in depts_rows_db:
        depts_by_fac.setdefault(r["faculty_id"], []).append(r["id"])

    prog_rows = []
    for route in range(len(faculty_ids) * 3):
        fac_id = faculty_ids[route % len(faculty_ids)]
        pool = names_by_fac[fac_id]
        pname = pool[route // len(faculty_ids) % len(pool)]
        dept_pool = depts_by_fac.get(fac_id, [None])
        dep_id = dept_pool[(route // len(faculty_ids)) % len(dept_pool)]
        prog_rows.append((fac_id, dep_id,
                          f"{random.randint(9,15):02d}.{random.randint(2,4):02d}.{random.randint(2,4):02d}",
                          pname,
                          random.randint(20, 60), random.randint(10, 40),
                          random.randint(150, 250),
                          random.choice(["fulltime", "parttime"])))
    await conn.executemany(
        "INSERT INTO programs (faculty_id, department_id, code, name, budget_seats, paid_seats, min_score_prev, form) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        prog_rows)
    program_ids = [r["id"] for r in await conn.fetch("SELECT id FROM programs ORDER BY id")]

    # ---- 3) Студенты ----
    stud_rows = []
    for i in range(2500):
        enrolled_year = random.choice([2021, 2022, 2023, 2024, 2025])
        status = random.choices(["active", "expelled", "academic_leave"], weights=[90, 6, 4])[0]
        # год смены статуса: для exp/leave — год после поступления (или null для active)
        status_since_year = random.randint(enrolled_year, 2026) if status != "active" else None
        stud_rows.append(
            (f"Студент {random.choice(DOCTORS)} {i}", f"SC-{random.randint(100000,999999)}",
             f"s{i}@student.uni.ru",
             f"+7 950 {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10,99)}",
             random.choice(program_ids), random.randint(1, 5),
             round(random.uniform(2.0, 5.0), 2),
             status,
             random.choices(["budget", "paid"], weights=[70, 30])[0],
             enrolled_year, status_since_year)
        )
    await conn.executemany(
        "INSERT INTO students (fio, student_card_no, email, phone, program_id, course, gpa, status, source, "
        "enrolled_year, status_since_year) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
        stud_rows)
    student_ids = [r["id"] for r in await conn.fetch("SELECT id FROM students ORDER BY id")]

    # ---- 4) Абитуриенты (годы 2021–2026 — для «динамики за 5 лет») ----
    appl_rows = []
    for _ in range(3000):
        y = random.choice([2021, 2022, 2023, 2024, 2025, 2026])
        score = random.randint(120, 280)
        ege_math = min(300, int(score * random.uniform(0.45, 0.55)))
        appl_rows.append((f"Абитуриент {random.choice(DOCTORS)} {random.randint(1000,9999)}",
                          random.choice(program_ids), score,
                          datetime.date(y, random.randint(6, 9), random.randint(1, 28)),
                          random.choices(["submitted", "enrolled", "rejected"], weights=[60, 25, 15])[0],
                          random.choices(["budget", "paid"], weights=[60, 40])[0],
                          ege_math, score - ege_math))
    await conn.executemany(
        "INSERT INTO applicants (fio, program_id, ege_score, submitted_date, status, source, ege_math, ege_rus) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        appl_rows)

    # ---- 5) Дисциплины (курсы) ----
    course_rows = [
        (random.choice(teacher_ids), random.choice(program_ids),
         random.choice(DISCIPLINES), random.choice([2, 3, 4, 5]), random.choice([1, 2]),
         random.choice([2024, 2025, 2026]))
        for _ in range(40)
    ]
    await conn.executemany(
        "INSERT INTO courses (teacher_id, program_id, name, credits, semester, year) "
        "VALUES ($1,$2,$3,$4,$5,$6)",
        course_rows)
    course_ids = [r["id"] for r in await conn.fetch("SELECT id FROM courses ORDER BY id")]

    # ---- 6) Успеваемость (с попыткой) ----
    enrol_rows = []
    for sid in student_ids:
        for _ in range(random.randint(2, 5)):
            grade = round(random.uniform(2.0, 5.0), 2)
            passed = grade >= 3
            enrol_rows.append((sid, random.choice(course_ids),
                               random.choice(["2025 spring", "2025 fall", "2026 spring"]),
                               grade, passed, random.randint(40, 100),
                               1 if passed else random.choice([1, 2])))
    await conn.executemany(
        "INSERT INTO enrollments (student_id, course_id, semester, grade, passed, attendance, attempt) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7)",
        enrol_rows)

    # ---- 7) Группы (реалистичные имена для демо) + привязка студентов ----
    GROUPS_BY_PROG = {
        "Информационные системы и технологии": ["ИВТ-101", "ИВТ-102", "ИВТ-103"],
        "Бизнес-информатика": ["БИВ-211", "БИВ-212"],
        "Программная инженерия": ["ПИ-201", "ПИ-202"],
    }
    prog_name = dict(await conn.fetch("SELECT id, name FROM programs"))
    group_rows = []
    for pid, pname in prog_name.items():
        base = GROUPS_BY_PROG.get(pname)
        if base is None:
            abbrev = "".join(w[0].upper() for w in pname.split())[:3] or "ГР"
            base = [f"{abbrev}-{pid}01", f"{abbrev}-{pid}02", f"{abbrev}-{pid}03"]
        for nm in base:
            group_rows.append((nm, pid, random.randint(1, 5)))
    await conn.executemany("INSERT INTO groups (name, program_id, course) VALUES ($1,$2,$3)", group_rows)
    # назначить студентам группу направления set-based (по остатку id — быстро, без построчных UPDATE)
    await conn.execute(
        "WITH grp AS (SELECT g.id, g.program_id, "
        "row_number() OVER (PARTITION BY g.program_id ORDER BY g.id) rn, "
        "count(*) OVER (PARTITION BY g.program_id) cnt FROM groups g) "
        "UPDATE students s SET group_id = g.id FROM grp g "
        "WHERE g.program_id = s.program_id AND g.rn = (s.id % g.cnt) + 1")

    # ---- 8) Аудитории (корпуса А/Б по факультетам) ----
    room_rows = [
        (f"ауд-{fid}{i}", "А" if i % 2 else "Б", 30 + i * 10, fid)
        for i in range(1, 7)
        for fid in faculty_ids
    ]
    await conn.executemany("INSERT INTO rooms (name, building, capacity, faculty_id) VALUES ($1,$2,$3,$4)", room_rows)
    room_ids = await conn.fetch("SELECT id, faculty_id FROM rooms ORDER BY id")
    rooms_by_fac: dict[int, list[int]] = {}
    for r in room_ids:
        rooms_by_fac.setdefault(r["faculty_id"], []).append(r["id"])

    # ---- 9) Расписание (по дисциплинам: аудитория факультета, день, пара) ----
    course_fac = dict(await conn.fetch(
        "SELECT c.id, p.faculty_id FROM courses c JOIN programs p ON c.program_id = p.id"))
    sched_rows = []
    for cid, fac in course_fac.items():
        rooms_pool = rooms_by_fac.get(fac) or [None]
        sched_rows.append((random.choice(rooms_pool), cid,
                           random.choice(["Пн", "Вт", "Ср", "Чт", "Пт"]),
                           random.choice([1, 2, 3]),
                           random.choice(["2025 spring", "2025 fall", "2026 spring"])))
    await conn.executemany(
        "INSERT INTO schedule (room_id, course_id, day_of_week, pair, semester) VALUES ($1,$2,$3,$4,$5)",
        sched_rows)

    # ---- 10) Нагрузка преподавателей (часы) ----
    course_teacher = dict(await conn.fetch("SELECT id, teacher_id FROM courses"))
    load_rows = [
        (tid, cid, 150 + (cid % 6) * 50, "2025 spring")
        for cid, tid in course_teacher.items()
        if tid is not None
    ]
    await conn.executemany(
        "INSERT INTO teaching_load (staff_id, course_id, hours, semester) VALUES ($1,$2,$3,$4)",
        load_rows)

    # ---- 11) Год квот программ ----
    await conn.execute("UPDATE programs SET year = 2026 WHERE year IS NULL")

    print(f"OK. staff={len(staff_rows)+len(teacher_rows)}, faculties={len(faculty_ids)}, "
          f"departments={len(dept_ids)}, programs={len(program_ids)}, "
          f"students={len(student_ids)}, applicants={len(appl_rows)}, "
          f"courses={len(course_ids)}, enrollments={len(enrol_rows)}, "
          f"groups={len(group_rows)}, rooms={len(room_rows)}, schedule={len(sched_rows)}")


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
