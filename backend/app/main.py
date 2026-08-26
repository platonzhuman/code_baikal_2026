from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.analytics import compute_analytics
from app.core.audit import log_query
from app.core.auth import check_login, make_token, verify_token
from app.core.db import Database
from app.core.history import HistoryStore, RateLimiter, build_store
from app.core.logging import emit, sha
from app.core.schemas import (ChatRequest, ChatResponse, HealthResponse,
                              LoginRequest, LoginResponse, Role)
from app.core.schema_loader import load_schema
from app.core.schema_sanitizer import (
    all_tables, get_sanitized_schema, set_schema,
)
from app.services.orchestrator import Orchestrator

log = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.database_url)
    await db.connect()
    app.state.db = db
    # Схема подтягивается из каталога БД (без хардкода). Если БД недоступна — пустая.
    try:
        schema = await load_schema(db)
        set_schema(schema)
        log.info("schema_loaded", tables=len(all_tables()))
    except Exception as e:
        set_schema({})
        log.warning("schema_load_failed", err=str(e)[:120])
    app.state.orchestrator = Orchestrator(db)
    app.state.store = build_store(db=db)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    log.info("backend_started", db_url_shadow="...")
    try:
        yield
    finally:
        await db.close()
        log.info("backend_stopped")


app = FastAPI(title="University AI Assistant", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ограничь доменом университета в проде
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    ok = await app.state.db.healthcheck()
    return HealthResponse(status="ok" if ok else "error", database=ok)


@app.get("/")
async def root():
    return {"service": "university-ai-assistant", "docs": "/docs"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    # Сквозной trace: x-trace-id от фронта или query_id (одинаков во всех компонентах).
    trace_id = request.headers.get("x-trace-id") or req.query_id or str(uuid4())
    qid = trace_id
    ip = request.client.host if request.client else "anon"
    ua = request.headers.get("user-agent", "")
    auth_method = "token" if request.headers.get("authorization") else "guest"

    # Rate-limit по session_id (или IP). Сбой: слишком часто -> 429.
    key = req.session_id or ip
    if not await app.state.rate_limiter.allow(key):
        emit("WARN", "main", "rate_limit_exceeded", trace_id=trace_id, session_id=req.session_id,
             role=req.role.value, data={"key": key, "limit": settings.rate_limit_per_minute})
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте чуть позже.")

    emit("INFO", "main", "chat_received", trace_id=trace_id, query_id=req.query_id,
         session_id=req.session_id, role=req.role.value,
         data={"client_ip": ip, "user_agent": ua[:120], "auth_method": auth_method,
               "question_hash": sha(req.question)})

    # Дедупликация: если такой query_id уже обработан — вернуть готовый ответ.
    if req.query_id:
        cached = await app.state.store.get_cached(req.query_id)
        if cached is not None:
            emit("DEBUG", "main", "dedup_cache_hit", trace_id=trace_id, query_id=req.query_id)
            return cached

    # Роль определяет СЕРВЕР: по токену из заголовка Authorization; иначе роль клиента.
    req.role = await _resolve_role(req, request)

    # Статус «в обработке» (чтобы при обрыве фронт видел незавершённый запрос).
    await app.state.store.begin(req.session_id, qid, req.role.value, req.question)

    # Контекст разговора: только УСПЕШНЫЕ ходы (без отказов/ошибок — иначе они
    # "отравляют" следующий запрос). Не более 4 последних (сжато для скорости).
    thread = await app.state.store.get_thread(req.session_id)
    history = [
        {"question": m.get("question", ""), "answer": m.get("answer", "")}
        for m in thread[-5:-1]
        if m.get("status", "success") == "success"
    ][-2:]

    try:
        response = await app.state.orchestrator.chat(req, query_id=qid, history=history)
    except Exception as e:
        emit("ERROR", "main", "chat_error", trace_id=trace_id, query_id=qid,
             session_id=req.session_id, role=req.role.value,
             data={"error": str(e)[:200]})
        raise
    await app.state.store.emit(
        session_id=req.session_id, req_question=req.question, req_role=req.role.value,
        response=response,
    )
    emit("INFO", "main", "chat_completed", trace_id=trace_id, query_id=response.meta.query_id,
         session_id=req.session_id, role=req.role.value,
         data={"status": response.status, "total_latency_ms": response.meta.latency_ms,
               "sql_preview": (response.sql or "")[:200],
               "row_count": response.result.row_count if response.result else 0})
    log_query(
        session_id=req.session_id, query_id=response.meta.query_id, role=req.role.value,
        question=req.question, status=response.status, sql=response.sql,
        latency_ms=response.meta.latency_ms,
        error=response.error.message if response.error else None,
    )
    log_query(
        session_id=req.session_id, query_id=response.meta.query_id, role=req.role.value,
        question=req.question, status=response.status, sql=response.sql,
        latency_ms=response.meta.latency_ms,
        error=response.error.message if response.error else None,
    )
    return response


@app.get("/schema")
async def schema(role: str = Query("applicant")):
    """Очищенная от ПДн схема БД для передачи в LLM (по роли)."""
    return {"role": role, "schema": get_sanitized_schema(role)}


@app.get("/logs")
async def logs():
    """Аналитика запросов (для страницы «Аналитика» у P3)."""
    return {"items": await app.state.store.all_logs()}


@app.get("/analytics")
async def analytics():
    """Сводная аналитика: темы, роли, отказы, латентность p50/p95, топ-вопросы."""
    return compute_analytics(await app.state.store.all_logs())


@app.get("/history")
async def history(session_id: str = Query(...)):
    """История диалога по session_id (возобновление после обрыва сети)."""
    return {"session_id": session_id, "items": await app.state.store.get_thread(session_id)}


@app.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Вход по общему логину/паролю роли -> роль + токен.
    Абитуриент — гость (вход не нужен). Студент/преподаватель/сотрудник — по кредам из .env."""
    role = check_login(req.login, req.password)
    emit("INFO", "auth", "login_attempt", role=role or "-",
         data={"login": req.login[:32], "success": role is not None, "role": role or "-"})
    if not role:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return LoginResponse(role=role, token=make_token(role))


async def _resolve_role(req: ChatRequest, request: Request) -> Role:
    """Роль на сервере: если в заголовке Authorization есть валидный токен — берём роль из него;
    иначе оставляем роль клиента (обратная совместимость с P3)."""
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if token:
        role = verify_token(token)
        if role in {r.value for r in Role}:
            return Role(role)
    return req.role
