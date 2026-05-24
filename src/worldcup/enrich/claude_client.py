"""Thin wrapper over the Anthropic Async SDK.

Provides:
- ClaudeClient — production client backed by anthropic.AsyncAnthropic
- FakeClaudeClient — test double with canned responses + identical interface
- Token-budget tracking (raises TokenBudgetExceeded on over-spend)

Disabled mode: if api_key is empty (no credential configured), the client is
'disabled' — its calls become no-ops returning None. This lets the pipeline
run without Claude even before keys are configured.
"""

import re
from dataclasses import dataclass
from typing import Optional, Protocol

from worldcup.log import get_logger


log = get_logger(__name__)


class TokenBudgetExceeded(Exception):
    """Raised when a call would push cumulative output tokens past the budget."""


@dataclass
class ClaudeCallResult:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass
class SentimentResult:
    score: float
    confidence: float


class _BaseClaudeClient(Protocol):
    async def complete(self, prompt: str, *, model: str, max_tokens: int) -> Optional[ClaudeCallResult]: ...
    async def score_text(self, text: str, *, model: str) -> Optional[SentimentResult]: ...
    def is_disabled(self) -> bool: ...


def _rough_token_count(text: str) -> int:
    """Cheap proxy for tokens. Real Anthropic SDK returns usage info; for accounting
    we accept a rough estimate of ~4 chars/token, capped at 1."""
    return max(1, len(text) // 4)


class ClaudeClient:
    """Production client. Lazily constructs AsyncAnthropic on first call."""

    def __init__(self, api_key: str, token_budget: int):
        self._api_key = api_key
        self._token_budget = token_budget
        self._tokens_used = 0
        self._anthropic = None

    def is_disabled(self) -> bool:
        return not self._api_key

    def _ensure_client(self):
        if self._anthropic is None:
            from anthropic import AsyncAnthropic
            self._anthropic = AsyncAnthropic(api_key=self._api_key)
        return self._anthropic

    def _check_budget(self, projected_output_tokens: int) -> None:
        if self._tokens_used + projected_output_tokens > self._token_budget:
            raise TokenBudgetExceeded(
                f"Would exceed token budget: used {self._tokens_used} + {projected_output_tokens} > {self._token_budget}"
            )

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    async def complete(self, prompt: str, *, model: str, max_tokens: int) -> Optional[ClaudeCallResult]:
        if self.is_disabled():
            log.warning("claude.disabled_complete_skipped")
            return None
        self._check_budget(max_tokens)
        client = self._ensure_client()
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        usage = resp.usage
        out_tokens = getattr(usage, "output_tokens", _rough_token_count(text))
        in_tokens = getattr(usage, "input_tokens", _rough_token_count(prompt))
        self._tokens_used += out_tokens
        return ClaudeCallResult(text=text, input_tokens=in_tokens, output_tokens=out_tokens)

    async def score_text(self, text: str, *, model: str) -> Optional[SentimentResult]:
        if self.is_disabled():
            log.warning("claude.disabled_score_skipped")
            return None
        prompt = (
            "Score the sentiment of this football-related text on a scale from "
            "-1.0 (very negative) to +1.0 (very positive). "
            "Respond with two numbers on one line separated by a space: "
            "the score, then a confidence value in [0, 1]. "
            "No other text.\\n\\n"
            f"Text:\\n{text}"
        )
        result = await self.complete(prompt, model=model, max_tokens=20)
        if result is None:
            return None
        parsed = _parse_score(result.text)
        if parsed is None:
            log.warning("claude.score_parse_failed", text=result.text[:80])
            return SentimentResult(score=0.0, confidence=0.0)
        return parsed


def _parse_score(text: str) -> Optional[SentimentResult]:
    """Parse a 'score confidence' pair from Claude's response.

    Accepts a couple of common formats robustly: lone numbers, comma-separated,
    or labeled. Returns None if no two floats can be found.
    """
    nums = re.findall(r"-?\d+\.?\d*", text)
    if len(nums) < 2:
        return None
    try:
        score = float(nums[0])
        confidence = float(nums[1])
    except ValueError:
        return None
    score = max(-1.0, min(1.0, score))
    confidence = max(0.0, min(1.0, confidence))
    return SentimentResult(score=score, confidence=confidence)


class FakeClaudeClient:
    """Test double — identical interface, no network. Tracks call count + tokens.

    Pass ``raise_on_call`` to simulate API failures: every call to
    ``complete`` or ``score_text`` will raise that exception instead of
    returning a canned response.  Useful for testing error-handling paths.
    """

    def __init__(
        self,
        canned_completion: Optional[str] = "fake-response",
        canned_score: Optional[float] = 0.0,
        token_budget: int = 100_000,
        disabled: bool = False,
        per_call_output_tokens: int = 30,
        raise_on_call: Optional[Exception] = None,
    ):
        self._canned_completion = canned_completion
        self._canned_score = canned_score
        self._token_budget = token_budget
        self._tokens_used = 0
        self._disabled = disabled
        self._per_call_output_tokens = per_call_output_tokens
        self._raise_on_call = raise_on_call
        self.calls = 0

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    def is_disabled(self) -> bool:
        return self._disabled

    def _check_budget(self) -> None:
        if self._tokens_used + self._per_call_output_tokens > self._token_budget:
            raise TokenBudgetExceeded(
                f"Fake budget exceeded: used {self._tokens_used} + {self._per_call_output_tokens} > {self._token_budget}"
            )

    async def complete(self, prompt: str, *, model: str, max_tokens: int) -> Optional[ClaudeCallResult]:
        if self._disabled:
            return None
        if self._raise_on_call is not None:
            raise self._raise_on_call
        self._check_budget()
        self.calls += 1
        self._tokens_used += self._per_call_output_tokens
        return ClaudeCallResult(
            text=self._canned_completion or "",
            input_tokens=_rough_token_count(prompt),
            output_tokens=self._per_call_output_tokens,
        )

    async def score_text(self, text: str, *, model: str) -> Optional[SentimentResult]:
        if self._disabled:
            return None
        if self._raise_on_call is not None:
            raise self._raise_on_call
        if self._canned_score is None:
            return None
        self._check_budget()
        self.calls += 1
        self._tokens_used += self._per_call_output_tokens
        return SentimentResult(score=self._canned_score, confidence=1.0)
