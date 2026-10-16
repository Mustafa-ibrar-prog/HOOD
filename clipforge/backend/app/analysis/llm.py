"""LLM-based moment detection with structured JSON output.

The model sees the transcript as numbered sentence units with timestamps and
returns moments as *unit id ranges*. That design means:
  * boundaries always land on sentence boundaries we computed ourselves,
  * timestamps can't be hallucinated (we map ids -> times locally),
  * quotes are verified against the transcript before they're shown.

Providers: Anthropic (official SDK) and any OpenAI-compatible chat endpoint.
Both are optional; the pipeline falls back to the heuristic scorer on failure.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import settings
from ..models import PlatformCopy, ScoreBreakdown
from .lexicon import CONTENT_TYPES
from .sentences import Unit

log = logging.getLogger(__name__)

PLATFORMS = ("youtube_shorts", "tiktok", "instagram_reels")
SCORE_KEYS = ("hook", "emotion", "clarity", "payoff", "pacing", "shareability")


class AnalysisError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _platform_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "description", "hashtags"],
        "additionalProperties": False,
    }


MOMENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_id": {"type": "integer"},
                    "end_id": {"type": "integer"},
                    "content_type": {"type": "string", "enum": CONTENT_TYPES + ["conversation"]},
                    "hook_quote": {"type": "string"},
                    "scores": {
                        "type": "object",
                        "properties": {k: {"type": "integer"} for k in SCORE_KEYS},
                        "required": list(SCORE_KEYS),
                        "additionalProperties": False,
                    },
                    "explanation": {"type": "string"},
                    "selection_reason": {"type": "string"},
                    "platforms": {
                        "type": "object",
                        "properties": {p: _platform_schema() for p in PLATFORMS},
                        "required": list(PLATFORMS),
                        "additionalProperties": False,
                    },
                },
                "required": ["start_id", "end_id", "content_type", "hook_quote", "scores", "explanation",
                             "selection_reason", "platforms"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["moments"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a senior short-form video editor. You find the moments in a long video's transcript that are most likely to hold attention as a standalone YouTube Short, TikTok or Instagram Reel.

The transcript is given as numbered sentence units: `[id] start-end  text` (times in seconds). You select a moment by giving the id of its first unit (start_id) and its last unit (end_id), inclusive.

What makes a strong moment:
- A surprising statement or unexpected revelation; a funny moment, joke or reaction; a heated debate, disagreement or controversial opinion; an emotional or relatable story; an impressive gaming play or hype commentary; useful advice, facts or a clear explanation; a strong question, suspense and a satisfying payoff.
- A clear beginning: the first unit must make sense to someone who has not seen the rest of the video. Avoid starting on a connector ("and", "but", "so") or an unresolved pronoun when an earlier unit supplies the context; include that context.
- A satisfying ending: finish on the punchline, answer, conclusion or reaction. Never stop before the payoff.
- No long silences, no rambling setup, and no two moments that repeat the same idea.

Rules:
- Each moment must last between {min_s:.0f} and {max_s:.0f} seconds (end of end_id minus start of start_id). 20-45 seconds is ideal when the moment allows it. Never exceed {max_s:.0f} seconds.
- Moments must not overlap each other.
- hook_quote must be copied verbatim from the moment's first one or two units.
- Use only what is in the transcript. Never invent events, quotes, names or outcomes. Titles and descriptions must describe what is actually said; do not promise anything the clip doesn't contain.
- Scores are integers 0-100 and are your honest estimate for each criterion, not a prediction of views: hook (does the opening grab attention in the first 3 seconds), emotion (emotional or entertainment impact), clarity (understandable standalone), payoff (complete, with a satisfying ending), pacing (dense, no dead air), shareability (likely to be shared or discussed). Use the full range; a mediocre moment should score around 40-55.
- explanation: 1-2 sentences on why the moment works, referring to what is actually said. selection_reason: one short sentence on why it was chosen over nearby alternatives.
- For each platform give a title (under 70 characters), a 1-2 sentence description, and 3-8 relevant hashtags (each starting with #, no spaces).
- Return the strongest moments first. Return fewer moments rather than weak ones."""


@dataclass
class LLMMoment:
    start_id: int
    end_id: int
    content_type: str
    hook_quote: str
    scores: ScoreBreakdown
    explanation: str
    selection_reason: str
    platforms: dict[str, PlatformCopy] = field(default_factory=dict)


def format_units(units: list[Unit]) -> str:
    return "\n".join(f"[{u.id}] {u.start:.1f}-{u.end:.1f}  {u.text}" for u in units)


def chunk_units(units: list[Unit], max_chars: int = 200_000, overlap: int = 25) -> list[list[Unit]]:
    """Split very long transcripts into overlapping chunks that fit comfortably in context."""
    chunks: list[list[Unit]] = []
    cur: list[Unit] = []
    size = 0
    for u in units:
        line = len(u.text) + 24
        if cur and size + line > max_chars:
            chunks.append(cur)
            cur = cur[-overlap:]
            size = sum(len(x.text) + 24 for x in cur)
        cur.append(u)
        size += line
    if cur:
        chunks.append(cur)
    return chunks


def _clean_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = re.sub(r"[^\w#]", "", t.strip().replace(" ", ""))
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        if len(t) > 1 and t.lower() not in {x.lower() for x in out}:
            out.append(t[:40])
    return out[:8]


def parse_moments(payload: dict) -> list[LLMMoment]:
    out: list[LLMMoment] = []
    for m in payload.get("moments", []) or []:
        try:
            scores = ScoreBreakdown(**{k: max(0, min(100, int(m["scores"][k]))) for k in SCORE_KEYS})
            platforms = {}
            for p in PLATFORMS:
                pc = (m.get("platforms") or {}).get(p)
                if pc:
                    platforms[p] = PlatformCopy(
                        title=str(pc.get("title", ""))[:100].strip(),
                        description=str(pc.get("description", ""))[:500].strip(),
                        hashtags=_clean_hashtags(list(pc.get("hashtags", []))),
                    )
            ctype = m.get("content_type", "conversation")
            out.append(
                LLMMoment(
                    start_id=int(m["start_id"]),
                    end_id=int(m["end_id"]),
                    content_type=ctype if ctype in CONTENT_TYPES else "conversation",
                    hook_quote=str(m.get("hook_quote", "")).strip(),
                    scores=scores,
                    explanation=str(m.get("explanation", "")).strip()[:600],
                    selection_reason=str(m.get("selection_reason", "")).strip()[:300],
                    platforms=platforms,
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            log.warning("dropping malformed moment from LLM: %s (%s)", m, e)
    return out


class LLMAnalyzer:
    name = "llm"
    model = ""

    def _complete(self, system: str, user: str) -> dict:  # pragma: no cover - interface
        raise NotImplementedError

    def find_moments(self, units: list[Unit], *, title: str, duration: Optional[float], n_wanted: int,
                     min_s: float, max_s: float) -> list[LLMMoment]:
        system = SYSTEM_PROMPT.format(min_s=min_s, max_s=max_s)
        results: list[LLMMoment] = []
        chunks = chunk_units(units)
        for idx, chunk in enumerate(chunks):
            span = f"units {chunk[0].id}-{chunk[-1].id}" + (f" (part {idx+1} of {len(chunks)})" if len(chunks) > 1 else "")
            user = (
                f"Video title: {title or 'unknown'}\n"
                f"Video length: {duration or units[-1].end:.0f} seconds\n"
                f"Transcript {span}:\n\n{format_units(chunk)}\n\n"
                f"Find up to {min(n_wanted * 2, 24)} of the strongest non-overlapping moments in this transcript."
            )
            payload = self._complete(system, user)
            results.extend(parse_moments(payload))
        return results


class AnthropicAnalyzer(LLMAnalyzer):
    """Claude via the official Anthropic SDK, using structured outputs."""

    name = "anthropic"
    # Models that support server-side refusal fallbacks ("fallbacks": "default").
    _FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise AnalysisError("ANTHROPIC_API_KEY is not set")
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds, max_retries=3
        )
        self.model = settings.anthropic_model

    def _complete(self, system: str, user: str) -> dict:
        anthropic = self._anthropic
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=32000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": settings.anthropic_effort,
                "format": {"type": "json_schema", "schema": MOMENTS_SCHEMA},
            },
        )
        use_fallbacks = settings.anthropic_fallbacks and self.model in self._FALLBACK_MODELS
        try:
            if use_fallbacks:
                with self.client.beta.messages.stream(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                ) as stream:
                    msg = stream.get_final_message()
            else:
                with self.client.messages.stream(**kwargs) as stream:
                    msg = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise AnalysisError("Anthropic rejected the API key (check ANTHROPIC_API_KEY).") from e
        except anthropic.PermissionDeniedError as e:
            raise AnalysisError(f"Anthropic API permission denied: {e.message}") from e
        except anthropic.NotFoundError as e:
            raise AnalysisError(f"Anthropic model '{self.model}' not found (check ANTHROPIC_MODEL).") from e
        except anthropic.BadRequestError as e:
            raise AnalysisError(f"Anthropic rejected the request: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise AnalysisError("Anthropic rate limit reached; try again shortly.", retryable=True) from e
        except anthropic.APIStatusError as e:
            raise AnalysisError(f"Anthropic API error {e.status_code}", retryable=e.status_code >= 500) from e
        except anthropic.APITimeoutError as e:
            raise AnalysisError("Anthropic API timed out.", retryable=True) from e
        except anthropic.APIConnectionError as e:
            raise AnalysisError("Could not connect to the Anthropic API.", retryable=True) from e

        if msg.stop_reason == "refusal":
            raise AnalysisError("The model declined to analyse this transcript.")
        if msg.stop_reason == "max_tokens":
            raise AnalysisError("The model's response was cut off (max_tokens).", retryable=True)
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise AnalysisError(f"Model returned invalid JSON: {e}") from e


class OpenAICompatibleAnalyzer(LLMAnalyzer):
    """Any OpenAI-compatible /chat/completions endpoint with JSON-schema output
    (OpenAI, or local servers such as Ollama / vLLM via OPENAI_BASE_URL)."""

    name = "openai"

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise AnalysisError("OPENAI_API_KEY is not set")
        self.model = settings.openai_model

    def _complete(self, system: str, user: str) -> dict:
        import httpx

        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "moments", "schema": MOMENTS_SCHEMA, "strict": True}},
        }
        try:
            r = httpx.post(
                f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=body,
                timeout=settings.llm_timeout_seconds,
            )
        except httpx.TimeoutException as e:
            raise AnalysisError("LLM API timed out.", retryable=True) from e
        except httpx.HTTPError as e:
            raise AnalysisError(f"Could not reach the LLM API: {e}", retryable=True) from e
        if r.status_code == 401:
            raise AnalysisError("The LLM API rejected the API key (check OPENAI_API_KEY).")
        if r.status_code == 429 or r.status_code >= 500:
            raise AnalysisError(f"LLM API HTTP {r.status_code}", retryable=True)
        if r.status_code >= 400:
            raise AnalysisError(f"LLM API error {r.status_code}: {r.text[:300]}")
        try:
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as e:
            raise AnalysisError(f"LLM returned an unexpected response: {e}") from e


def get_llm_analyzer() -> Optional[LLMAnalyzer]:
    provider = settings.resolved_analysis_provider()
    if provider == "anthropic":
        return AnthropicAnalyzer()
    if provider == "openai":
        return OpenAICompatibleAnalyzer()
    return None
