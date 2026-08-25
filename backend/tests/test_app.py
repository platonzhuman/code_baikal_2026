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
    res = client.post("/chat", json={"question": "х", "role": "student"})
    assert res.status_code == 422


def test_logs_and_history(client):
    # после успешного запроса должно появиться в /logs и /history
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

