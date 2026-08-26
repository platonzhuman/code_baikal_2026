import pytest

from app.core.auth import check_login, make_token, verify_token
from app.config import get_settings


def test_check_login_valid_roles():
    assert check_login("student", "student2026") == "student"
    assert check_login("teacher", "teacher2026") == "teacher"
    assert check_login("staff", "admin2026") == "staff"


def test_check_login_invalid():
    assert check_login("student", "wrong") is None
    assert check_login("admin", "admin") is None


def test_token_roundtrip():
    t = make_token("staff")
    assert verify_token(t) == "staff"


def test_token_tampered():
    t = make_token("student")
    tampered = t[:-1] + ("0" if t[-1] != "0" else "1")
    assert verify_token(tampered) is None or verify_token(tampered) != "student"


def test_token_garbage():
    assert verify_token("garbage") is None


def test_role_credentials_present():
    creds = get_settings().role_credentials
    assert "student" in creds and "staff" in creds and "teacher" in creds
