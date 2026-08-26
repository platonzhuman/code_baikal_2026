from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..")

# app.log — структурированные логи по спецификации (JSON-строки)
_APP_LOG = logging.getLogger("university.app")
if not _APP_LOG.handlers:
    _APP_LOG.setLevel(logging.INFO)
    _h = logging.FileHandler(os.path.join(_LOG_DIR, "app.log"), encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(message)s"))
    _APP_LOG.addHandler(_h)

# audit.log — аудит-записи (без ПДн)
_AUDIT = logging.getLogger("university.audit")
if not _AUDIT.handlers:
    _AUDIT.setLevel(logging.INFO)
    _ha = logging.FileHandler(os.path.join(_LOG_DIR, "audit.log"), encoding="utf-8")
    _ha.setFormatter(logging.Formatter("%(message)s"))
    _AUDIT.addHandler(_ha)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def new_id() -> str:
    return str(uuid.uuid4())


def _json(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, default=str)


def emit(level: str, component: str, message: str, *, trace_id: str | None = None,
         span_id: str | None = None, parent_span_id: str | None = None,
         session_id: str | None = None, query_id: str | None = None, role: str | None = None,
         data: dict | None = None, start_ts: str | None = None,
         duration_ms: float | None = None) -> None:
    """Единая структурированная лог-запись (спецификация: trace_id/span_id, JSON)."""
    rec = {
        "timestamp": now_iso(),
        "level": level.upper(),
        "service": "backend",
        "component": component,
        "trace_id": trace_id or new_id(),
        "span_id": span_id or new_id(),
        "session_id": session_id or "",
        "query_id": query_id or "",
        "role": role or "",
        "message": message,
    }
    if parent_span_id:
        rec["parent_span_id"] = parent_span_id
    if data:
        rec["data"] = data
    if start_ts:
        rec["start_ts"] = start_ts
    if duration_ms is not None:
        rec["duration_ms"] = round(duration_ms, 2)
    _APP_LOG.info(_json(rec))


def audit_append(rec: dict) -> None:
    _AUDIT.info(_json(rec))


def log_llm_response(model: str, usage: dict | None, latency_ms: float, trace_id: str | None) -> None:
    data = {"model": model, "latency_ms": round(latency_ms, 2)}
    if isinstance(usage, dict):
        data.update({"prompt_tokens": usage.get("prompt_tokens"),
                     "completion_tokens": usage.get("completion_tokens"),
                     "total_tokens": usage.get("total_tokens")})
    emit("INFO", "llm_client", "LLM response", trace_id=trace_id, data=data)


def log_llm_failure(err: Exception | str, retry: int, trace_id: str | None, stage: str = "generate"):
    emit("WARN", "llm_client", "LLM failure", trace_id=trace_id,
         data={"error": str(err)[:200], "retry_count": retry, "stage": stage})
