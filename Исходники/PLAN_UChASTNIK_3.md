# ПЛАН: Участник 3 — Fullstack/Frontend & Product Lead (ОБНОВЛЕНО 25.08)

> Согласовано с P1/P2. Контракт: `role = applicant | staff`. ПДн: маскируем личные поля.

---

## 0. СТАТУС НА СЕГОДНЯ (Чекпоинт)

**Уже сделано (работает):**
- ✅ Стек: **Vite + React**, `frontend/`, `npm run dev` → `http://localhost:5173`.
- ✅ **Прокси на `localhost:8000`**: `/chat`, `/health`, `/logs`.
- ✅ Экраны: главная (логотип GIGACHADS), **чат**, **вход**, **аналитика** (только после входа).
- ✅ **Виджет** `/?embed=1` — сразу чат без шапки.
- ✅ **Роль не выбирает человек**: гость → `applicant`; **фейковый вход на фронте** (пароль на бэк НЕ уходит) → `staff`. Переключателя student/teacher **нет** — это категории вопросов в промпте P1, не UI.
- ✅ **CSV** с таблицы — есть.
- ✅ **ПДн-маска** на UI: `fio, email, phone, passport, student_card → ***` (третья линия).
- ✅ Обработка: `error` → только `error.message` (без трейсбека). Если `/chat` не поднят — фронт отвечает своей заглушкой (UI не стоит), подхватит реальный stub сам.

**Осталось на сегодня:** показать, что фронт соединяется с **живым `/chat` от P2** и вся система работает локально.

---

## 1. КОНТРАКТ (принимаю от P2, не менять)

### `POST /chat`
```json
{ "question": "...", "role": "applicant|staff", "session_id": "uuid",
  "options": { "explain": true, "max_rows": 50 } }
```
### success
```json
{ "status":"success", "text":"...", "sql":"...",
  "result":{ "columns":[...], "rows":[ ...объекты... ], "row_count":0,
             "truncated":false, "warning":null, "suggested_filters":null },
  "explanation":{ "tables":[],"joins":[],"filters":[],"aggregates":[],"constraints":[] },
  "meta":{ "latency_ms":0, "query_id":"..." } }
```
### error
```json
{ "status":"error", "error":{ "code":"...", "message":"..." } }
```

**Что рендерим при success:** `text` (главное), таблицу из `result.columns`+`result.rows` (объекты), `sql`, `explanation`, `warning`, `truncated`, `suggested_filters`.

---

## 2. ПДн на UI
- Маска: `fio`, `email`, `phone`, `passport`, `student_card → ***` (и любые похожие ключи).
- Основное режет бэк (P2) — UI лишь страховка.

---

## 3. СЕГОДНЯ (Чекпоинт) — показать работу локально
1. Поднять бэк P2 (`:8000`), фронт (`:5173`).
2. Войти фейком → роль `staff`; без входа → `applicant`.
3. Отправить вопрос из пула (абитуриент + аналитика вуза) → увидеть `text`, таблицу, `sql`, `explanation`, `meta.judge`.
4. Проверить маску ПДн на личных полях (если придут).
5. Убедиться, что CSV выгружается, виджет `/?embed=1` работает.
6. Если `/chat` упал — фронт показывает свою заглушку (UI жив).

---

## 4. ДОРАБОТАТЬ
| Задача | Крит. | Статус |
|---|---|---|
| Убедиться, что `role` только `applicant\|staff` | контракт | 🔶 |
| Рендер `suggested_filters` (если придут) | Big Data | 🔶 |
| Живой `GET /logs` → страница «Аналитика» | Архитектура | 🔶 ждёт P2 |
| ПДн-маска: расширить ключи (fio/admin) | Безопасность | 🔶 |
| История диалога: localStorage + возобновление после обрыва | UX | ❌ |
| Графики (plotly) для агрегатов | UX | ❌ (опц.) |
| Презентация/слайды к финалу | — | 🔶 |

---

## 5. БЫСТРЫЙ СТАРТ
```bash
cd frontend && npm install && npm run dev   # :5173
# бэк: cd ../II_AGENT && uvicorn app.main:app --reload  # :8000
```
