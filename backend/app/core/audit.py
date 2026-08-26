from __future__ import annotations

import hashlib
import json
import logging
import os
import time

# Отдельный логгер «аудит» -> пишет в файл backend/audit.log (без ПДн).
_AUDIT_LOG = logging.getLogger("university.audit")
_AUDIT_LOG.setLevel(logging.INFO)

_AUDIT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "audit.log")
if not _AUDIT_LOG.handlers:
    _fh = logging.FileHandler(_AUDIT_PATH, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(message)s"))
    _AUDIT_LOG.addHandler(_fh)


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def log_query(session_id: str, query_id: str, role: str, question: str,
              status: str, sql: str, latency_ms: int, error: str | None = None) -> None:
    """Запись аудита запроса. Вопрос логируем как хэш (не храним исходный текст ПДн)."""
    record = {
        "ts": time.time(),
        "session_id": session_id,
        "query_id": query_id,
        "role": role,
        "question_sha256": _hash(question),
        "status": status,
        "latency_ms": latency_ms,
        "sql": sql or "",
        "error": error,
    }
    _AUDIT_LOG.info(json.dumps(record, ensure_ascii=False))


def get_audit_path() -> str:
    return _AUDIT_PATH
