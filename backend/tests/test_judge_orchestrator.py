import pytest

from app.config import get_settings
from app.core.db import Database
from app.core.schemas import ChatRequest
from app.services.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_orchestrator_rejects_low_score():
    db = Database(get_settings().database_url)
    await db.connect()
    try:
        orch = Orchestrator(db)

        async def gen(question, schema, role, feedback="", history=None):
            return "SELECT name FROM programs LIMIT 50", {
                "score": 0.2, "reason": "нелогичный SQL", "is_valid": False,
            }
        orch.llm.generate_and_judge = gen

        r = await orch.chat(ChatRequest(question="что-то странное", role="applicant"))
        assert r.status == "error"
        assert r.error is not None and r.error.code in ("SQL_REJECTED", "NEEDS_REFINEMENT")
    finally:
        await db.close()
