import pytest

from worldcup.enrich.claude_client import (
    ClaudeCallResult,
    FakeClaudeClient,
    TokenBudgetExceeded,
)


@pytest.mark.asyncio
async def test_fake_client_returns_canned_completion():
    client = FakeClaudeClient(canned_completion="hello", token_budget=1000)
    result = await client.complete(prompt="ignored", model="m", max_tokens=100)
    assert isinstance(result, ClaudeCallResult)
    assert result.text == "hello"
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert client.calls == 1


@pytest.mark.asyncio
async def test_fake_client_score_text_returns_canned_score():
    client = FakeClaudeClient(canned_score=0.42, token_budget=1000)
    result = await client.score_text(text="some text", model="m")
    assert result.score == 0.42
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_token_budget_exceeded_raises():
    # Budget too small for a single call
    client = FakeClaudeClient(canned_completion="ok", token_budget=5)
    with pytest.raises(TokenBudgetExceeded):
        await client.complete(prompt="some prompt", model="m", max_tokens=200)


@pytest.mark.asyncio
async def test_budget_tracks_cumulative_usage():
    client = FakeClaudeClient(canned_completion="ok", token_budget=100)
    # Each fake call charges 30 tokens output by default; 3 calls = 90, 4th would exceed.
    for _ in range(3):
        await client.complete(prompt="x", model="m", max_tokens=200)
    assert client.tokens_used <= 100
    with pytest.raises(TokenBudgetExceeded):
        await client.complete(prompt="x", model="m", max_tokens=200)


def test_fake_client_disabled_short_circuits():
    """A disabled client (e.g., no API key) returns None from score_text/complete."""
    client = FakeClaudeClient(canned_completion=None, canned_score=None, token_budget=100, disabled=True)
    assert client.is_disabled() is True
