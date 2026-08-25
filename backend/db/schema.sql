-- ============================================================
-- Университетская схема БД (6-8 таблиц)
-- Хакатон 24-28 авг 2026. Драйвер базы: PostgreSQL 15+.
-- Комментарии полей = семантический слой для LLM (Lead AI).
-- ============================================================

-- 1. Сотрудники (преподаватели, деканы, сотрудники) -> ПДн-разрешено к показу: fio
--    email/phone - чувствительные, НЕ выводить студентам/абитуриентам.
CREATE TABLE IF NOT EXISTS staff (
    id            BIGSERIAL PRIMARY KEY,
    fio           TEXT        NOT NULL,              -- ФИО сотрудника (разрешено к показу)
    post          TEXT,                              -- должность: 'декан' | 'преподаватель' | ...
    department_id BIGINT,                            -- FK -> departments
    email         TEXT,                              -- ПДн: контакт - скрыто
    phone         TEXT                               -- ПДн: контакт - скрыто
);

-- 2. Факультеты
CREATE TABLE IF NOT EXISTS faculties (
    id      BIGSERIAL PRIMARY KEY,
    name    TEXT NOT NULL,                           -- Название факультета
    dean_id BIGINT REFERENCES staff(id)              -- Декан (ФИО можно показывать)
);

-- 3. Кафедры
CREATE TABLE IF NOT EXISTS departments (
    id         BIGSERIAL PRIMARY KEY,
    faculty_id BIGINT NOT NULL REFERENCES faculties(id),
    name       TEXT   NOT NULL,                      -- Название кафедры
    head_id    BIGINT REFERENCES staff(id)
);

-- 4. Направления подготовки (программы)
CREATE TABLE IF NOT EXISTS programs (
    id            BIGSERIAL PRIMARY KEY,
    faculty_id    BIGINT  NOT NULL REFERENCES faculties(id),
    code          TEXT    NOT NULL,                  -- Код направления, напр. '09.03.02'
    name          TEXT    NOT NULL,                  -- Название, напр. 'Информационные системы'
    budget_seats  INTEGER NOT NULL DEFAULT 0,        -- Бюджетные места
    paid_seats    INTEGER NOT NULL DEFAULT 0,        -- Платные места
    min_score_prev INTEGER,                          -- Проходной балл прошлых лет
    form          TEXT    DEFAULT 'fulltime'         -- 'fulltime'|'parttime'
);

-- 5. Студенты -> ПДн-чувствительная: fio, student_card_no, email, phone
CREATE TABLE IF NOT EXISTS students (
    id              BIGSERIAL PRIMARY KEY,
    fio             TEXT NOT NULL,                   -- ПДн: СКРЫТО для других студентов
    student_card_no TEXT NOT NULL,                   -- ПДн: зачётка - СКРЫТО
    email           TEXT,                            -- ПДн
    phone           TEXT,                            -- ПДн
    program_id      BIGINT NOT NULL REFERENCES programs(id),
    course          INTEGER NOT NULL,                -- Курс: 1..4/5
    gpa             NUMERIC(4,2),                    -- Средний балл (средний GPA)
    status          TEXT DEFAULT 'active',           -- 'active'|'expelled'|'academic_leave'
    source          TEXT DEFAULT 'budget'            -- 'budget'|'paid'
);

-- 6. Абитуриенты -> ПДн-чувствительная: fio, ege_score - агрегируем
CREATE TABLE IF NOT EXISTS applicants (
    id             BIGSERIAL PRIMARY KEY,
    fio            TEXT NOT NULL,                    -- ПДн: СКРЫТО
    program_id     BIGINT NOT NULL REFERENCES programs(id),
    ege_score      INTEGER,                          -- Балл ЕГЭ
    submitted_date DATE,                             -- Дата подачи документов
    status         TEXT DEFAULT 'submitted',         -- 'submitted'|'enrolled'|'rejected'
    source         TEXT DEFAULT 'budget'             -- 'budget'|'paid'
);

-- 7. Дисциплины (курсы)
CREATE TABLE IF NOT EXISTS courses (
    id          BIGSERIAL PRIMARY KEY,
    teacher_id  BIGINT REFERENCES staff(id),         -- Преподаватель (ФИО разрешено)
    program_id  BIGINT NOT NULL REFERENCES programs(id),
    name        TEXT NOT NULL,                       -- Название дисциплины
    credits     INTEGER DEFAULT 3,                   -- Кредиты
    semester    INTEGER                               -- Четный/нечетный/номер
);

-- 8. Успеваемость (enrollments) -> агрегаты: grade, passed, attendance
CREATE TABLE IF NOT EXISTS enrollments (
    id         BIGSERIAL PRIMARY KEY,
    student_id BIGINT  NOT NULL REFERENCES students(id),
    course_id  BIGINT  NOT NULL REFERENCES courses(id),
    semester   TEXT    NOT NULL,                     -- 'spring'|'fall' год
    grade      NUMERIC(4,2),                         -- Оценка / балл
    passed     BOOLEAN DEFAULT FALSE,                -- bool: сдал/не сдал (задолженность)
    attendance INTEGER                               -- % посещаемости
);

-- ============================================================
-- Индексы для скорости агрегаций и JOIN (производительность)
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_staff_department       ON staff(department_id);
CREATE INDEX IF NOT EXISTS idx_departments_faculty    ON departments(faculty_id);
CREATE INDEX IF NOT EXISTS idx_programs_faculty       ON programs(faculty_id);
CREATE INDEX IF NOT EXISTS idx_students_program       ON students(program_id);
CREATE INDEX IF NOT EXISTS idx_applicants_program     ON applicants(program_id);
CREATE INDEX IF NOT EXISTS idx_courses_teacher        ON courses(teacher_id);
CREATE INDEX IF NOT EXISTS idx_courses_program        ON courses(program_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_student    ON enrollments(student_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_course     ON enrollments(course_id);
-- Составной индекс: JOIN успеваемость <-> студент + фильтр по курсу
CREATE INDEX IF NOT EXISTS idx_enrollments_stud_course ON enrollments(student_id, course_id);
