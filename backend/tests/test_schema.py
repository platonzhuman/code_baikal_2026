from app.core.schema_sanitizer import (
    LEARNER_TABLES,
    ROLE_AGGREGATE_ONLY,
    get_sanitized_schema,
)


def test_pii_hidden_for_all_roles():
    for role in ("applicant", "staff"):
        s = get_sanitized_schema(role)
        assert "students (id, fio" not in s
        assert "applicants (id, fio" not in s
        assert "staff (id, fio" not in s
        assert "student_card_no" not in s
        assert "email" not in s
        assert "phone" not in s


def test_aggregate_rule_for_both_roles():
    for role in ("applicant", "staff"):
        s = get_sanitized_schema(role)
        assert "[только агрегаты]" in s
        assert "students (id, program_id, course, gpa, status, source)  [только агрегаты]" in s


def test_learner_tables_marked():
    s = get_sanitized_schema("applicant")
    for t in ("students", "applicants", "enrollments"):
        assert t in s and "[только агрегаты]" in s


def test_no_pii_columns_listed():
    s = get_sanitized_schema("staff")
    assert "students (id, fio" not in s
    assert "applicants (id, fio" not in s
    assert "staff (id, fio" not in s
    assert "student_card_no" not in s


def test_alias_visible_fields():
    # Обезличенные поля остаются доступными для агрегатов
    s = get_sanitized_schema("applicant")
    assert "gpa" in s and "budget_seats" in s and "ege_score" in s


def test_roles_constants():
    assert ROLE_AGGREGATE_ONLY == {"applicant", "staff"}
    assert "students" in LEARNER_TABLES
