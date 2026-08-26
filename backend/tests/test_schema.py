from app.core.schema_sanitizer import (
    LEARNER_TABLES,
    ROLE_AGGREGATE_ONLY,
    get_sanitized_schema,
)


def test_staff_sees_all_tables_no_pii():
    s = get_sanitized_schema("staff")
    # сотрудник/администрация видит все таблицы, но без ПДн обучающихся
    assert "students (" in s and "applicants (" in s and "enrollments (" in s
    assert "students (id, fio" not in s
    assert "applicants (id, fio" not in s
    assert "student_card_no" not in s
    assert "email" not in s and "phone" not in s
    # ФИО сотрудников доступно admin (по памятке)
    assert "staff (id, fio, post, department_id)" in s


def test_applicant_only_reference_tables():
    s = get_sanitized_schema("applicant")
    # абитуриент видит только справочники приёма + статистику
    assert "programs (" in s and "faculties (" in s and "applicants (" in s
    assert "students (" not in s
    assert "staff (" not in s
    assert "departments (" not in s


def test_aggregate_rule_on_learner_tables():
    for role in ("staff", "student", "teacher"):
        s = get_sanitized_schema(role)
        assert "[только агрегаты]" in s
        # enrollments — таблица обучающихся, видна всем трём ролям и помечена
        assert "enrollments (" in s and "[только агрегаты]" in s


def test_teacher_sees_staff_fio():
    s = get_sanitized_schema("teacher")
    assert "staff (id, fio, post, department_id)" in s


def test_no_pii_columns_listed():
    s = get_sanitized_schema("staff")
    assert "students (id, fio" not in s
    assert "applicants (id, fio" not in s
    assert "student_card_no" not in s


def test_visible_aggregate_fields():
    # обезличенные поля доступны для агрегатов
    s = get_sanitized_schema("staff")
    assert "gpa" in s and "budget_seats" in s and "ege_score" in s


def test_roles_constants():
    assert ROLE_AGGREGATE_ONLY == {"applicant", "student", "teacher", "staff"}
    assert "students" in LEARNER_TABLES
