import pytest

from app.core.history import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_up_to_limit():
    rl = RateLimiter(per_minute=2)
    assert await rl.allow("u1") is True
    assert await rl.allow("u1") is True
    assert await rl.allow("u1") is False  # превысили


@pytest.mark.asyncio
async def test_rate_limiter_per_key_independent():
    rl = RateLimiter(per_minute=2)
    assert await rl.allow("a") is True
    assert await rl.allow("a") is True
    assert await rl.allow("a") is False
    assert await rl.allow("b") is True  # другой ключ — свой лимит
