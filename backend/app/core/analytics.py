from __future__ import annotations

import re
import statistics

# Категории тем по ключевым словам (порядок важен: специфичнее — раньше).
CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("запрещённые данные (ПДн/изменение)", ("фио", "ф.и.о", "паспорт", "телефон", "почт", "email",
                                            "личные данн", "персональн", "удалит", "удали", "измен", "обнови",
                                            "вставь", "добав", "снести", "подставь", "переменную")),
    ("отчисления", ("отчисл", "expelled")),
    ("успеваемость", ("балл", "gpa", "задолжн", "сдал", "экзамен", "семестр", "неаттест", "оценк", "долг")),
    ("приёмная кампания", ("бюджет", "платн", "проходн", "егэ", "заявл", "абитуриент", "направлен",
                           "направлени", "мест", "поступ", "приём", "прием", "срок подач")),
    ("студенты и численность", ("студент", "численн", "обуча", "учится", "курс")),
    ("преподаватели и нагрузка", ("преподават", "нагрузк", "дисциплин", "кафедр", "группа")),
    ("аудитории и расписание", ("аудитор", "расписан", "корпус", "пара", "понедельник", "расписание")),
    ("прочее", ()),
]

_STOPWORDS = {"пожалуйста", "покажи", "выведи", "скажи", "найди", "мне", "данных", "данные",
              "базы", "база", "посчитай", "помоги", "узнай", "в", "на", "этом", "этом году",
              "году", "лет", "год", "все", "всех", "всем", "сколько", "какие", "какой"}


def classify(question: str) -> str:
    q = (question or "").lower()
    for category, words in CATEGORIES:
        if any(w in q for w in words):
            return category
    return "прочее"


def normalize(question: str) -> str:
    """Нормализация для группировки «популярных запросов»: нижний регистр, без пунктуации и стоп-слов."""
    q = re.sub(r"[!?.,()«»\"'%]", " ", (question or "").lower())
    words = [w for w in q.split() if w not in _STOPWORDS]
    # обрезаем до ключевых первых 8 слов
    return " ".join(words[:8])


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(p / 100 * len(s))))
    return round(s[k], 1)


def compute_analytics(logs: list[dict]) -> dict:
    """Реальная аналитика: темы, роли, популярные запросы (сгруппированные), отказы, латентность."""
    total = len(logs)
    by_role: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_error: dict[str, int] = {}
    by_category: dict[str, int] = {}
    latencies: list[float] = []
    qgroups: dict[str, dict] = {}   # normalized -> {"count","success","last"}
    recent: list[dict] = []

    for e in logs:
        role = e.get("role") or "-"
        status = e.get("status") or "-"
        error = e.get("error")
        cat = classify(e.get("question", ""))
        by_role[role] = by_role.get(role, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        if error:
            by_error[error] = by_error.get(error, 0) + 1
        by_category[cat] = by_category.get(cat, 0) + 1
        if isinstance(e.get("latency_ms"), (int, float)):
            latencies.append(float(e["latency_ms"]))

        q = (e.get("question") or "").strip()
        if q:
            key = normalize(q) or q.lower()
            g = qgroups.setdefault(key, {"count": 0, "success": 0, "last": q})
            g["count"] += 1
            if status == "success":
                g["success"] += 1
            g["last"] = q
        # последние запросы (для «ленты»)
        recent.append({
            "role": role,
            "question": q[:120],
            "status": status,
            "error": error,
            "latency_ms": e.get("latency_ms"),
            "sql_preview": (e.get("sql") or "")[:120],
        })

    refused = by_status.get("error", 0)
    top = sorted(
        ({"question": g["last"], "count": g["count"],
          "success_rate": round(g["success"] / g["count"] * 100, 1)}
         for g in qgroups.values()),
        key=lambda x: -x["count"],
    )[:10]

    return {
        "total_queries": total,
        "metrics": {
            "success": by_status.get("success", 0),
            "errors": refused,
            "refusal_rate": round(refused / total * 100, 1) if total else 0.0,
            "by_role": by_role,
            "by_category": [
                {"category": c, "count": n, "share": round(n / total * 100, 1) if total else 0}
                for c, n in sorted(by_category.items(), key=lambda x: -x[1])
            ],
            "latency": {"p50_ms": _percentile(latencies, 50),
                        "p95_ms": _percentile(latencies, 95),
                        "max_ms": round(max(latencies), 1) if latencies else 0.0},
        },
        "top_questions": top,
        "refusals": [{"code": c, "count": n} for c, n in sorted(by_error.items(), key=lambda x: -x[1])],
        "recent_queries": recent[-10:][::-1],
    }
