from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.db import Database
from app.core.history import HistoryStore, build_store
from app.core.schemas import ChatRequest, ChatResponse, HealthResponse
from app.core.schema_sanitizer import get_sanitized_schema
from app.services.orchestrator import Orchestrator

log = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.database_url)
    await db.connect()
    app.state.db = db
    app.state.orchestrator = Orchestrator(db)
    app.state.store = build_store()
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
async def chat(req: ChatRequest):
    response = await app.state.orchestrator.chat(req)
    await app.state.store.record(
        session_id=req.session_id, query_id=response.meta.query_id,
        role=req.role.value, question=req.question, response=response,
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


@app.get("/history")
async def history(session_id: str = Query(...)):
    """История диалога по session_id (возобновление после обрыва сети)."""
    return {"session_id": session_id, "items": await app.state.store.get_thread(session_id)}
