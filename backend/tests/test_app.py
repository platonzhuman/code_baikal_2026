from fastapi.testclient import TestClient

import pytest

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] in ("ok", "error")


def test_chat_success(client):
    res = client.post("/chat", json={"question": "Какой средний балл?", "role": "applicant"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert "sql" in body and "LIMIT" in body["sql"].upper()


def test_chat_validation_empty_question(client):
    res = client.post("/chat", json={"question": "", "role": "applicant"})
    assert res.status_code == 422


def test_chat_validation_bad_role(client):
    res = client.post("/chat", json={"question": "х", "role": "superman"})
    assert res.status_code == 422


def test_logs_and_history(client):
    sid = "sess-test-123"
    res = client.post("/chat", json={"question": "Сколько заявлений?", "role": "staff",
                                     "session_id": sid})
    assert res.status_code == 200

    l = client.get("/logs")
    assert l.status_code == 200 and "items" in l.json()

    h = client.get("/history", params={"session_id": sid})
    assert h.status_code == 200
    items = h.json()["items"]
    assert isinstance(items, list) and len(items) >= 1


def test_chat_pagination_fields(client):
    res = client.post("/chat", json={"question": "Какова численность студентов по факультетам?",
                                     "role": "staff", "session_id": "pag", "page": 1, "max_rows": 5})
    assert res.status_code == 200
    r = res.json()["result"]
    for f in ("page", "page_size", "total", "total_pages"):
        assert f in r


def test_chat_dedup_by_query_id(client):
    body = {"question": "Сколько студентов имеют задолженность?", "role": "staff",
            "session_id": "dedup", "query_id": "fixed-query-1"}
    r1 = client.post("/chat", json=body).json()
    r2 = client.post("/chat", json=body).json()
    assert r1["meta"]["query_id"] == "fixed-query-1"
    assert r1["status"] == r2["status"]
    assert r1.get("text") == r2.get("text")

