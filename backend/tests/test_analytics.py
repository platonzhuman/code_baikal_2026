from app.core.analytics import classify, compute_analytics

LOGS = [
    {"role": "applicant", "question": "Сколько бюджетных мест?", "status": "success",
     "error": None, "latency_ms": 500},
    {"role": "staff", "question": "Покажи ФИО студентов", "status": "error",
     "error": "PDN_VIOLATION", "latency_ms": 100},
    {"role": "staff", "question": "Сколько студентов обучается на ИТ?", "status": "success",
     "error": None, "latency_ms": 4000},
    {"role": "applicant", "question": "Сколько бюджетных мест?", "status": "success",
     "error": None, "latency_ms": 600},
    {"role": "staff", "question": "Удали факультет", "status": "error",
     "error": "READ_ONLY", "latency_ms": 50},
]


def test_classify():
    assert classify("Сколько бюджетных мест?") == "приёмная кампания"
    assert classify("Покажи ФИО студентов") == "запрещённые данные (ПДн/изменение)"
    assert classify("Сколько студентов обучается на ИТ?") == "студенты и численность"
    assert classify("Какая-то странная фраза") == "прочее"


def test_compute_analytics():
    a = compute_analytics(LOGS)
    assert a["total_queries"] == 5
    assert a["by_status"]["error"] == 2
    assert a["by_error_code"]["PDN_VIOLATION"] == 1
    assert a["refusal_rate"] == 40.0
    assert a["latency"]["p50_ms"] == 500
    assert a["top_questions"][0][0] == "Сколько бюджетных мест?"
    # категории: приёмная кампания встречается 2 раза
    cats = dict(a["by_category"])
    assert cats.get("приёмная кампания", 0) == 2
