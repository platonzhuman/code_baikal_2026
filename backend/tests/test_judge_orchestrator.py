import pytest

from app.core.db import Database
from app.core.schemas import ChatRequest
from app.services.orchestrator import Orchestrator


@pytest.fixture
def orch():
    return Orchestrator(Database("postgresql://x:y@z:1/nonexistent"))


async def _patch_judge_low(orch):
    async def check_sql(sql, question, schema, role):
        return {"score": 0.2, "reason": "нелогичный SQL", "is_valid": False}
    orch.llm.check_sql = check_sql


def test_orchestrator_rejects_low_score(orch):
    pytest.mark.asyncio
    import asyncio

    async def run():
        await _patch_judge_low(orch)
        r = await orch.chat(ChatRequest(question="что-то странное", role="applicant"))
        assert r.status == "error"
        assert r.error is not None and r.error.code in ("SQL_REJECTED", "NEEDS_REFINEMENT")
        assert "Уточни" in r.text or "уточн" in r.text.lower()

    asyncio.run(run())
