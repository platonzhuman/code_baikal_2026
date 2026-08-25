import pytest

from app.config import get_settings
from app.services.llm_client import LLMClient


@pytest.fixture
def client():
    return LLMClient()


def test_threshold_default():
    assert get_settings().sql_judge_threshold == 0.8


@pytest.mark.asyncio
async def test_check_accepts_good_select(client):
    good = ("SELECT p.name, AVG(e.grade) AS gpa FROM enrollments e "
            "JOIN courses c ON e.course_id=c.id JOIN programs p ON c.program_id=p.id GROUP BY p.name")
    r = await client.check_sql(good, "какой средний балл", "", "applicant")
    assert r["is_valid"] is True
    assert r["score"] >= client.threshold


@pytest.mark.asyncio
async def test_check_rejects_non_select(client):
    for bad in ("INSERT INTO programs DEFAULT VALUES", "UPDATE programs SET name='x'", "DROP TABLE students"):
        r = await client.check_sql(bad, "вопрос", "", "staff")
        assert r["is_valid"] is False
        assert r["score"] < client.threshold


@pytest.mark.asyncio
async def test_check_rejects_forbidden_table(client):
    r = await client.check_sql("SELECT * FROM secret_users", "вопрос", "", "staff")
    assert r["is_valid"] is False
    assert r["score"] < client.threshold


@pytest.mark.asyncio
async def test_check_rejects_parse_error(client):
    r = await client.check_sql("SELEC 1; DROP TABLE x;", "вопрос", "", "applicant")
    assert r["is_valid"] is False
    assert r["score"] < client.threshold
