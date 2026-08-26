from app.core.analytics import classify, compute_analytics, normalize

LOGS = [
    {"role": "applicant", "question": "Сколько бюджетных мест?", "status": "success",
     "error": None, "latency_ms": 500},
    {"role": "staff", "question": "Покажи ФИО студентов", "status": "error",
     "error": "PDN_VIOLATION", "latency_ms": 100},
    {"role": "staff", "question": "Сколько студентов обучается на ИТ?", "status": "success",
     "error": None, "latency_ms": 4000},
    {"role": "applicant", "question": "Сколько бюджетных мест в этом году?", "status": "success",
     "error": None, "latency_ms": 600},
    {"role": "staff", "question": "Удали факультет", "status": "error",
     "error": "READ_ONLY", "latency_ms": 50},
]


def test_classify():
    assert classify("Сколько бюджетных мест?") == "приёмная кампания"
    assert classify("Покажи ФИО студентов") == "запрещённые данные (ПДн/изменение)"
    assert classify("Какая аудитория свободна в понедельник?") == "аудитории и расписание"
    assert classify("Странная фраза") == "прочее"


def test_normalize_groups():
    # одинаковая нормализация — поэтому «популярные» объединяются
    assert normalize("Сколько бюджетных мест?") == normalize("Сколько бюджетных мест в этом году?")
    assert "?" not in normalize("сколько мест?")


def test_compute_analytics():
    a = compute_analytics(LOGS)
    assert a["total_queries"] == 5
    m = a["metrics"]
    assert m["refusal_rate"] == 40.0
    assert m["by_role"]["applicant"] == 2
    cats = {c["category"]: c for c in m["by_category"]}
    assert cats["приёмная кампания"]["count"] == 2
    # популярные сгруппированы: «бюджетных мест» встречается 2 раза
    top = {t["question"]: t for t in a["top_questions"]}
    budget = [t for t in a["top_questions"] if "бюджетных мест" in t["question"].lower()]
    assert budget and budget[0]["count"] == 2
    # отказы по кодам
    errs = {r["code"] for r in a["refusals"]}
    assert {"PDN_VIOLATION", "READ_ONLY"}.issubset(errs)
    # последние запросы
    assert len(a["recent_queries"]) == 5
    assert a["metrics"]["latency"]["p95_ms"] == 4000
