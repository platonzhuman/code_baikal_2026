# University AI Assistant — безопасный чат с PostgreSQL на естественном языке

Интеллектуальный ассистент университета: пользователь задаёт вопрос на естественном языке →
LLM генерирует SQL → запрос проверяется (только SELECT, whitelist таблиц, защита ПДн,
statement_timeout) → выполняется в PostgreSQL → пользователь получает понятный ответ,
SQL и таблицу результата.

Проект хакатона «Код Байкала» (25–28 авг 2026). Роли в команде:
- **P1 — Lead AI & Semantic Engineer**: LLM-генератор SQL, LLM-судья 0..1, суммаризатор,
  Explainable AI, анти-галлюцинации, сужение запроса.
- **P2 — Backend & Security Architect**: FastAPI-оркестратор, AST-валидатор, БД, безопасность.
- **P3 — Fullstack/Frontend & Product Lead**: React-чат, виджет, CSV, маска ПДн.

---

## Архитектура

```
[React-фронтенд :5173] ──JSON──► [FastAPI-оркестратор :8000]
                                        │
                      ┌─────────────────┼───────────────────┐
                      ▼                 ▼                   ▼
             [LLM: генератор + судья]  [AST-валидатор]  [PostgreSQL READ ONLY]
```

- **Асинхронно** (async/await, `asyncpg` пул, семафор), параллельные запросы.
- **Безопасность**: только SELECT, whitelist из 8 таблиц, запрет ПДн-столбцов,
  `statement_timeout`, READ ONLY подключение.
- **ПДн**: `fio`, `email`, `phone`, `student_card_no`, `passport` не отдаются никому.
  По таблицам `students`, `applicants`, `enrollments` — только агрегаты (COUNT/AVG/GROUP BY).

---

## Стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.11+, FastAPI, uvicorn, asyncpg, pydantic v2, sqlglot, structlog, httpx |
| LLM | OpenAI-совместимый API (OpenAI / DeepSeek / Qwen / локальный шлюз), **Yandex AI Studio** |
| Frontend | Vite + React 19, oxlint |
| DB | PostgreSQL 15+ (внешний кластер `vesna-db7` или docker-compose) |
| Тесты | pytest + pytest-asyncio |

---

## Структура проекта

```
backend/
  app/
    main.py                  # FastAPI: /health, /chat, /login, /schema, /logs, /history
    config.py                # настройки из .env (pydantic-settings)
    core/
      schemas.py             # контракт API (pydantic) + роли
      security.py            # AST-валидатор (SELECT / role-aware whitelist / ПДн / авто-LIMIT)
      schema_loader.py       # схема БД из каталога (без хардкода)
      schema_sanitizer.py    # очищенная от ПДн схема + промпты (словарь значений, few-shot)
      auth.py                # /login, HMAC-токены, роль по токену
      audit.py               # аудит-лог запросов в файл (без ПДн)
      db.py                  # asyncpg пул, READ ONLY, statement_timeout, EXPLAIN
      history.py             # история диалогов (perсистентно в chat_messages) + rate-limit
    services/
      llm_client.py          # LLM: генератор, судья 0..1, суммаризатор, сужение, explanation
      orchestrator.py        # цепочка: вопрос → LLM → судья → AST → БД → ответ
      question_pool.py       # пул вопросов по ролям (демо/тесты)
  db/
    schema.sql               # схема БД (8 таблиц) + индексы + семантика
    seed.py                  # демо-датасет (2500 студентов, 3000 абитуриентов)
  tests/                     # pytest (conftest форсит mock-LLM)
  requirements.txt
  .env.example               # шаблон переменных окружения
  Makefile
  docker-compose.yml         # локальные db + backend
frontend/
  src/                       # React: чат, вход, аналитика, виджет
  vite.config.js             # прокси /chat, /health, /logs → :8000
Исходники/                   # ТЗ, планы участников, памятка хакатона
```

---

## Быстрый старт

### 0. Предварительно

- Python 3.11+, Node.js 20.19+ (Vite 8 требует Node 20.19+/22), (опц.) Docker.
- Внешняя БД PostgreSQL (кластер `vesna-db7`) или поднять локальную через docker.

### 1. Настройка окружения (переменные и доступы)

```bash
cd backend
cp .env.example .env     # затем заполни своими данными
```

Все секреты хранятся ТОЛЬКО в `backend/.env` (файл в `.gitignore`, в git не попадает).
Заполняются две группы переменных:

**БД (обязательно):**
```ini
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB_NAME
POSTGRES_DB=vesna-db7
POSTGRES_USER=vdb7_user
POSTGRES_PASSWORD=secret
POSTGRES_HOST=185.241.193.203
POSTGRES_PORT=5432
```

**LLM (обязательно для реальной генерации).** Два варианта:

Вариант А — **Yandex AI Studio (DeepSeek)** (рекомендуется):
```ini
LLM_API_KEY=AQVN...                  # API-ключ Yandex AI Studio
LLM_MODEL=gpt://FOLDER_ID/deepseek-v4-flash/latest
LLM_BASE_URL=https://llm.api.cloud.yandex.net/v1
LLM_MODE=real
LLM_AUTH=auto                        # Yandex → Api-Key, остальные → Bearer
```
`gpt://FOLDER_ID/deepseek-v4-flash/latest` — URI модели, `FOLDER_ID` — каталог (можно задать и через `YANDEX_CLOUD_FOLDER`, тогда `LLM_MODEL` пишется как `deepseek-v4-flash/latest` — префикс добавится сам).

Вариант Б — **любой OpenAI-совместимый API** (OpenAI, DeepSeek, Qwen, vLLM…):
```ini
LLM_API_KEY=sk-...
LLM_MODEL=имя_модели
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODE=real
LLM_AUTH=bearer
```

Режимы LLM:
- `LLM_MODE=real` — только реальная модель;
- `LLM_MODE=mock` — детерминированные заглушки (офлайн-демо, тесты);
- `LLM_MODE=auto` — реальная при наличии ключа, иначе mock.

### 2. Установка зависимостей

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Подготовка БД

Вариант 1 — **внешний кластер** (уже заполнен в `.env`): схема и данные должны быть загружены.
Вариант 2 — **локально через docker** (схема поднимется автоматически из `db/schema.sql`):
```bash
cd backend
docker compose up -d db            # или: make db-up
.venv/bin/python -m db.seed        # демо-данные: make seed
```

### 4. Запуск бэкенда

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000     # или: make run
```

Проверка: `curl http://127.0.0.1:8000/health` → `{"status":"ok","database":true}`.
Документация API: http://127.0.0.1:8000/docs

### 5. Запуск фронтенда

```bash
cd frontend
npm install
npm run dev                          # → http://localhost:5173
```

- Чат открывается сразу; без входа роль — `applicant` (абитуриент).
- **Вход** — `POST /login` (общие логины `student`/`teacher`/`staff` → токен). Роль определяет
  **сервер**: фронт передаёт `Authorization: Bearer <token>`, клиент роль не подменяет.
- Встраиваемый виджет: `http://localhost:5173/?embed=1`.

---

## Проверка контура через API

```bash
# Здоровье
curl http://127.0.0.1:8000/health

# Вопрос абитуриента
curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"Сколько бюджетных мест осталось?","role":"applicant"}'

# Вопрос администрации
curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"Сколько студентов на факультете ИТ?","role":"staff"}'

# Вход (общий логин на роль) -> токен
curl -X POST http://127.0.0.1:8000/login -H 'Content-Type: application/json' \
  -d '{"login":"staff","password":"staff"}'
# → { "role": "staff", "token": "…" }

# Вопрос под ролью (токен в Authorization) — роль берёт сервер
TOK=<вставь токен выше>
curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOK" \
  -d '{"question":"Численность студентов по факультетам?","role":"applicant"}'

# Очищенная схема (без ПДн)
curl "http://127.0.0.1:8000/schema?role=applicant"

# История диалога и логи
curl "http://127.0.0.1:8000/history?session_id=test"
curl http://127.0.0.1:8000/logs
```

### Контракт `POST /chat`

Запрос:
```json
{ "question": "…", "role": "applicant|student|teacher|staff", "session_id": "uuid",
  "options": { "explain": true, "max_rows": 50 } }
```
Ответ `success`:
```json
{ "status": "success", "text": "…", "sql": "SELECT … LIMIT 50",
  "result": { "columns": [], "rows": [], "row_count": 0, "truncated": false,
              "warning": null, "suggested_filters": null },
  "explanation": { "tables": [], "joins": [], "filters": [],
                   "aggregates": [], "constraints": [] },
  "meta": { "latency_ms": 0, "query_id": "…", "judge": { "score": 0.95 } } }
```
Ответ `error`:
```json
{ "status": "error", "error": { "code": "…", "message": "…" } }
```

---

## Тесты

```bash
cd backend
.venv/bin/python -m pytest -q        # или: make test
```
Тесты не ходят в реальный LLM: `tests/conftest.py` принудительно включает mock-режим.
Тесты, требующие живую БД (`test_app.py`), требуют работающего PostgreSQL в `.env`.

---

## Роли и политика ПДн

- `applicant` — абитуриент (гость, по умолчанию): направления, места, проходные баллы, статистика приёма.
- `student` — студент (по логину): успеваемость, средний балл, задолженности, дисциплины.
- `teacher` — преподаватель (по логину): дисциплины, группы, средний балл, % неаттестованных.
- `staff` — сотрудник/администрация (по логину): численность, приём, динамика, кафедры, аудитории, отчисления.

Роль определяет **сервер по токену** после `POST /login` (гость = абитуриент; клиент роль не подменяет).

**Правила:**
- только `SELECT`; запрещены INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE;
- доступны только таблицы из whitelist **роли** (у администрации — все 8, у остальных — свои);
- `fio`, `email`, `phone`, `student_card_no`, `passport` — не выдаются никому;
- по `students`/`applicants`/`enrollments` — только агрегаты (COUNT/AVG/MIN/MAX/GROUP BY);
- широкий запрос без фильтра/агрегата → автоматический `LIMIT` + предупреждение + `suggested_filters`;
- при ошибке/галлюцинации — понятное сообщение, данные не «придумываются» (`UNKNOWN`/отказ).

---

## Режим без ключа LLM (офлайн-демо)

Если `LLM_API_KEY` не задан (или `LLM_MODE=mock`), генератор и судья работают на
детерминированных заглушках — весь контур (вопрос → SQL → проверка → БД → ответ)
функционирует, в `meta` будет `"model": "mock-generator"`. Удобно для чекпоинта/демо.

---

## Полезные команды (Makefile, в `backend/`)

```bash
make install   # установка зависимостей в .venv
make run       # uvicorn на :8000
make test      # pytest
make seed      # загрузка демо-данных
make db-up     # локальная БД в docker (schema.sql автоматически)
make db-down   # остановить docker
```

---

## Возможные проблемы

| Проблема | Решение |
|---|---|
| `/health` → `"database": false` | Проверь `DATABASE_URL` в `.env`, доступность кластера и порт 5432 |
| LLM всегда `mock-generator` в `meta` | Впиши `LLM_API_KEY`+`LLM_MODEL`, поставь `LLM_MODE=real`; проверь `LLM_BASE_URL` |
| API 400 `Failed to parse model URI` | Укажи полный URI: `gpt://FOLDER_ID/deepseek-v4-flash/latest` |
| API 401 | Ключ неверный/протух; для Yandex заголовок должен быть `Api-Key` (это авто-режим) |
| Фронт отвечает заглушкой | Бэк на `:8000` не поднят — подними его; фронт работает автономно |
| `pytest` падает на `test_app.py` | Нет живой БД — эти тесты требуют рабочего PostgreSQL |