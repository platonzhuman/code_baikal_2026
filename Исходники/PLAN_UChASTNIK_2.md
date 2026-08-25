# ПЛАН: Участник 2 — Backend & Security Architect (ОБНОВЛЕНО 25.08)

> Согласовано с P1 и P3. Контракт: `role = applicant | staff` (гость→applicant, фейк-вход→staff).
> ПДн ужесточено: **ФИО не отдаём никому, включая администрацию** — только агрегаты/обезличенное.

---

## 0. СТАТУС НА СЕГОДНЯ (Чекпоинт)

**Готово (работает):**
- ✅ Схема БД — 8 таблиц (`db/schema.sql`) + индексы (17) + комментарии-семантика.
- ✅ Датасет — `db/seed.py` (2500 студентов, 3000 абитуриентов, ~8700 отчётов) в `vesna-db7`.
- ✅ FastAPI каркас: `main.py`, `config.py`, `/health`, `/chat`, `/schema`.
- ✅ Асинхронная БД `db.py` — `asyncpg` пул + **READ ONLY + statement_timeout**.
- ✅ **AST-валидатор** `security.py` (sqlglot): только SELECT, whitelist, запрет ПДн-столбцов, защита от инъекций, авто-LIMIT.
- ✅ **LLM-контур (mock)** `llm_client.py`: генератор SQL + **судья 0..1** + порог 0.8 + self-correction + сужение.
- ✅ Оркестрация `orchestrator.py`: вопрос → генерация → судья → AST → БД → ответ.
- ✅ Контракт `schemas.py`, очищенная схема `schema_sanitizer.py`.
- ✅ Тесты: **21 зелёный** (security, app, judge, schema, orchestrator).
- ✅ `.env`/`.env.example`, `docker-compose.yml`, `Dockerfile`, `Makefile`, `pytest.ini`, диаграммы (`*.drawio`).

**Осталось на сегодня (Чекпоинт):** см. раздел «Сегодня» ниже.

---

## 1. СТЕК И АРХИТЕКТУРА (как есть)
- Python 3.11+, FastAPI, uvicorn, `asyncpg` (пул), `pydantic` v2, `sqlglot`, `structlog`.
- Асинхронно, `await`-базировано → параллельные запросы. Конкурентность лимитируется (семафор, есть конфиг).
- Схема потока:
```
[Frontend React] ──JSON──► [FastAPI-оркестратор] ──► [mock/real LLM: генератор+судья]
                                       │                    │
                              [AST-валидатор]      [PostgreSQL READ ONLY]
```

---

## 2. КОНТРАКТ (зафиксирован, P3 его использует)

### `POST /chat`
```json
{ "question": "...", "role": "applicant|staff", "session_id": "uuid",
  "options": { "explain": true, "max_rows": 50 } }
```
### Ответ `success`
```json
{
  "status": "success",
  "text": "человеческий ответ",
  "sql": "SELECT ... LIMIT 50",
  "result": { "columns": [...], "rows": [...], "row_count": 0,
              "truncated": false, "warning": null,
              "suggested_filters": null },
  "explanation": { "tables":[], "joins":[], "filters":[],
                   "aggregates":[], "constraints":[] },
  "meta": { "latency_ms": 0, "query_id": "...", "judge": {"score":0.95} }
}
```
### Ответ `error`
```json
{ "status": "error", "error": { "code": "...", "message": "..." } }
```
> ⚠️ P3 ждёт поле **`suggested_filters`** в `result` — сейчас в бэке его нет. **Добавить.**
> ⚠️ `role` бэк принимает только `applicant | staff`. **Поправить `Role` enum.**

---

## 3. ПДн (ужесточено — согласовать с P1/P3)
- **Не отдаём никому:** `fio`, `email`, `phone`, `passport`, `student_card_no` (в т.ч. администрации).
- В `SENSITIVE_COLUMNS` добавить **`fio`** (сейчас нет) — и в `schema_sanitizer` скрыть `fio` из всех ролей.
- P3 маскирует те же поля (`***`) — третья линия. Основное режем мы на бэке.

---

## 4. СЕГОДНЯ (Чекпоинт 1/2) — показать основную работу локально
Цель: **«вход модели + вся система работает»**. LLM у нас — mock (генератор + судья), это ок для сегодня.
1. Поднять бэк: `uvicorn app.main:app --reload` (+ внешняя БД из `.env`).
2. `GET /health` → `database:true`.
3. `POST /chat` на живых вопросах (applicant и staff): SQL + таблица (`result.rows`), `explanation`, `meta.judge.score`, `warning/truncated`.
4. `GET /schema?role=applicant|staff` — показать очищенную схему (без ПДн).
5. `pytest -q` → зелёные.
6. Показать, что блокируется: INSERT/UPDATE/DROP, чужая таблица, `student_card_no` (PDN).
7. Прогнать вопросы из пула P3 и сверить поля контракта.

**Задел к сдаче (быстро, если успеем):**
- `suggested_filters` в `result`.
- `Role` → `applicant | staff`.
- Заглушка `POST /chat` отдаёт валидный JSON, если что-то падает (не ронять UI).

---

## 5. ДОРАБОТАТЬ (по маршруту к финалу)
| Задача | Балл/крит. | Статус |
|---|---|---|
| `suggested_filters` в `result` | Big Data | 🔶 надо |
| `role` → `applicant\|staff` | контракт | 🔶 надо |
| `fio` в `SENSITIVE_COLUMNS` + sanitizer | Безопасность | 🔶 надо |
| Хранилище `chat_messages` + `GET /history` + дедуп по `query_id` | Архитектура/UX | ❌ |
| `GET /logs` (аналитика запросов) | Архитектура | ❌ |
| Дружелюбный пустой результат (`EMPTY_RESULT`) | Точность | ❌ |
| Rate-limit + семафор (не перегружать) | Безопасность | ❌ |
| `EXPLAIN + Plan` + проверка стоимости (схема [11]/[12]) | Производительность | ❌ опц. |
| Реальный LLM (генератор+судья) — заменить mock | Точность | делает P1 |
| Аудит-логструктура (без ПДн/секретов) | Архитектура | ❌ |
| Обработка: LLM API сбой/таймаут → retry+friendly | Стабильность | ❌ |

---

## 6. ИНТЕГРАЦИЯ (кто от кого что получает)
- **От P3:** `question`, `role(applicant|staff)`, `session_id`, `options`.
- **P3 получает:** контракт (статус/text/sql/result/explanation/meta) + `GET /logs`.
- **P1:** я отдаю схему-семантику + права; принимаю от P1 реальный `generate_sql`/`check_sql` (заменю mock в `llm_client.py`). Объяснение (`explanation`) надёжнее строить на моём AST — P1 дополняет текстом.
- **Не ломать поля контракта.** Роль: `applicant|staff` только.

---

## 7. КОМАНДЫ ДЛЯ ДЕМО
```bash
cd /home/permak07/Desktop/Education/II_AGENT && source .venv/bin/activate
uvicorn app.main:app --reload
pytest -q
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"Сколько студентов на факультете ИТ?","role":"staff"}'
curl "http://127.0.0.1:8000/schema?role=applicant"
```
