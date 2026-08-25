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
    sql, meta = validator.validate("SELECT program_id, gpa FROM students")
    assert meta["truncated"] is True
    assert "LIMIT" in sql.upper()


def test_no_auto_limit_on_aggregate():
    sql, meta = validator.validate("SELECT program_id, COUNT(*) FROM students GROUP BY program_id")
    assert meta["truncated"] is False
