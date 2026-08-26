"""Тесты зоны Lead AI (P1): генератор, судья, суммаризатор, explanation, пул вопросов."""
import sqlglot
import pytest

from app.core.schema_sanitizer import build_system_prompt, get_sanitized_schema
from app.services.llm_client import LLMClient
from app.services.question_pool import POOL, all_questions, pool_for


@pytest.fixture
def client():
    return LLMClient(mode="mock")


@pytest.mark.asyncio
async def test_generate_sql_returns_parseable_sql_for_pool(client):
    """Для всех вопросов пула генератор (mock) возвращает парсимый SELECT или UNKNOWN."""
    for role, questions in POOL.items():
        schema = get_sanitized_schema(role)
        for item in questions:
            sql, meta = await client.generate_sql(item["question"], schema, role)
            assert isinstance(sql, str) and sql, item["question"]
            if sql.upper() != "UNKNOWN":
                stmts = sqlglot.parse(sql, read="postgres")
                assert len(stmts) == 1, item["question"]
                assert stmts[0].sql().upper().startswith("SELECT"), item["question"]


@pytest.mark.asyncio
async def test_generate_sql_is_select_only(client):
    sql, _ = await client.generate_sql("Сколько заявлений подано?", "schema", "staff")
    assert sql.lower().startswith("select")


@pytest.mark.asyncio
async def test_generate_sql_anti_hallucination_non_select(client):
    """Сгенерированный не-SELECT (не бывает от mock, но слой защищает)."""
    c = LLMClient(mode="mock")
    sql = c._sanitize_sql("INSERT INTO students (fio) VALUES ('x')")
    assert sql == "UNKNOWN"


@pytest.mark.asyncio
async def test_sanitize_sql_strips_markdown(client):
    sql = client._sanitize_sql("```sql\nSELECT name FROM programs;\n```")
    assert sql == "SELECT name FROM programs"


@pytest.mark.asyncio
async def test_check_accepts_good_select(client):
    good = ("SELECT p.name, AVG(e.grade) AS gpa FROM enrollments e "
            "JOIN courses c ON e.course_id=c.id JOIN programs p ON c.program_id=p.id GROUP BY p.name")
    r = await client.check_sql(good, "какой средний балл", "", "applicant")
    assert r["is_valid"] is True
    assert r["score"] >= client.threshold


@pytest.mark.asyncio
async def test_check_rejects_manipulation(client):
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
async def test_check_rejects_pdn_column(client):
    # поля-запрещёнки (контакты/паспорт) блокируются и в судье
    r = await client.check_sql("SELECT student_card_no FROM students", "вопрос", "", "staff")
    assert r["is_valid"] is False
    assert r["score"] < client.threshold


def test_validator_blocks_student_fio():
    # студенческое ФИО вне агрегата блокирует ВАЛИДАТОР («только агрегаты»)
    from app.core.security import PDNViolationError, build_validator
    try:
        build_validator().validate("SELECT fio FROM students")
        assert False, "должно быть заблокировано"
    except PDNViolationError:
        pass


@pytest.mark.asyncio
async def test_check_rejects_parse_error(client):
    r = await client.check_sql("SELEC 1; DROP TABLE x;", "вопрос", "", "applicant")
    assert r["is_valid"] is False
    assert r["score"] < client.threshold


@pytest.mark.asyncio
async def test_suggest_narrowing_contains_hint(client):
    msg = await client.suggest_narrowing("покажи всё про студентов", "schema", "staff", "слишком широко")
    assert "уточн" in msg.lower()


@pytest.mark.asyncio
async def test_summarize_fallback(client):
    t = await client.summarize("вопрос про баллы", "SELECT 1", ["name"], [{"name": "x"}])
    assert "вопрос" in t and "записей" in t


def test_explain_sql_extracts_structure():
    c = LLMClient(mode="mock")
    sql = ("SELECT f.name, COUNT(s.id) AS students FROM students s "
           "JOIN programs p ON s.program_id = p.id JOIN faculties f ON p.faculty_id = f.id "
           "WHERE s.status = 'active' GROUP BY f.name LIMIT 50")
    e = c.explain_sql(sql)
    assert "students" in e["tables"] and "faculties" in e["tables"]
    assert len(e["joins"]) >= 2
    assert any("status" in f for f in e["filters"])
    assert e["aggregates"] and any("COUNT" in a for a in e["aggregates"])
    assert any("LIMIT" in x for x in e["constraints"])


def test_build_system_prompt_contains_rules_and_fewshot():
    for role in ("applicant", "staff"):
        p = build_system_prompt(role)
        assert "PostgreSQL" in p and "SELECT" in p
        assert "UNKNOWN" in p
        assert "fio" in p.lower() or "ПДн" in p
        assert "Верни ТОЛЬКО JSON" in p
        assert "ПРИМЕРЫ" in p


def test_pool_has_questions_for_both_roles():
    assert len(pool_for("applicant")) >= 4
    assert len(pool_for("staff")) >= 4
    assert all("role" in q for q in all_questions())
    assert all(q["keywords"] for q in all_questions())