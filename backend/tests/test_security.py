import pytest

from app.core.security import (
    NotSelectError,
    PDNViolationError,
    TableForbiddenError,
    build_validator,
)

validator = build_validator()


def test_allows_select():
    sql, meta = validator.validate("SELECT name FROM programs LIMIT 5")
    assert "LIMIT" in sql.upper()
    assert meta["tables"] == ["programs"]


def test_blocks_manipulations():
    for bad in (
        "INSERT INTO programs (name) VALUES ('x')",
        "UPDATE programs SET name='x'",
        "DELETE FROM programs",
        "DROP TABLE programs",
        "ALTER TABLE programs ADD COLUMN c INT",
        "TRUNCATE TABLE programs",
    ):
        with pytest.raises(NotSelectError):
            validator.validate(bad)


def test_blocks_forbidden_tables():
    with pytest.raises(TableForbiddenError):
        validator.validate("SELECT * FROM secret_users")


def test_blocks_sensitive_pdn_columns():
    with pytest.raises(PDNViolationError):
        validator.validate("SELECT student_card_no FROM students")


def test_sql_injection_composite():
    with pytest.raises(NotSelectError):
        validator.validate("SELECT 1; DROP TABLE students")


def test_auto_limit_on_wide_query():
    sql, meta = validator.validate("SELECT name, code FROM programs")
    assert meta["truncated"] is True
    assert "LIMIT" in sql.upper()


def test_no_auto_limit_on_aggregate():
    sql, meta = validator.validate(
        "SELECT p.name, COUNT(s.id) FROM students s "
        "JOIN programs p ON s.program_id = p.id GROUP BY p.name")
    assert meta["truncated"] is False


def test_blocks_raw_student_columns():
    # «сырые» поля студентов (вне агрегатов) — запрещены
    import pytest
    from app.core.security import PDNViolationError
    for bad in ("SELECT gpa FROM students", "SELECT fio FROM students",
                "SELECT e.student_id FROM enrollments e"):
        with pytest.raises(PDNViolationError):
            validator.validate(bad)


def test_allows_dimensional_group():
    # агрегат по направлениям (FK-размерность) — допустим
    sql, meta = validator.validate(
        "SELECT s.program_id, COUNT(s.id) FROM students s GROUP BY s.program_id")
    assert meta["truncated"] is False
