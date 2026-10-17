"""One shared way to ask Claude for structured JSON, used by every AI feature in the app.

call_json() sends a fixed system prompt plus the request, requires the reply to match a JSON
schema, and records tokens and cost in the caller's meter. Anything unusable raises LLMError,
so each feature can fall back to its scripted version.
"""
import json
import os
import time

import anthropic

from . import budget

MODEL = "claude-opus-5-5"
# USD per million tokens for this model (input, output, cache write, cache read).
PRICES = {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20}
WEB_SEARCH_PRICE = 0.01  # USD per web search ($10 per 1,000)


class LLMError(Exception):
    """Anything that means Claude's answer can't be used."""


def claude_enabled(kind: str = "ai") -> bool:
    """Claude when an API key is available, unless HUB_BRAIN=mock forces the scripted versions,
    or (on the public demo) a spending cap has been reached."""
    return (os.environ.get("HUB_BRAIN", "auto") != "mock" and bool(os.environ.get("ANTHROPIC_API_KEY"))
            and budget.allows(kind))


def call_json(client, system: str, content: str, schema: dict, effort: str, meter: list | None,
              version: str, max_tokens: int = 8000) -> dict:
    started = time.monotonic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            # The system prompt never changes, so it's marked for caching.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # If a safety classifier declines, the API retries on a recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIError as error:
        raise LLMError(f"{type(error).__name__}: {error}") from error

    record(meter, response.model, version, response.usage, time.monotonic() - started)
    if response.stop_reason in ("refusal", "max_tokens"):
        raise LLMError(f"stop_reason={response.stop_reason}")
    text = next((block.text for block in response.content if block.type == "text"), None)
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError) as error:
        raise LLMError("reply was not valid JSON") from error
    if not isinstance(data, dict) or not all(key in data for key in schema["required"]):
        raise LLMError("reply did not have the agreed shape")
    return data


def record(meter: list | None, model: str, version: str, usage, seconds: float):
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    server_tools = getattr(usage, "server_tool_use", None)
    searches = (getattr(server_tools, "web_search_requests", 0) or 0) if server_tools else 0
    cost = (usage.input_tokens * PRICES["input"] + usage.output_tokens * PRICES["output"]
            + cache_write * PRICES["cache_write"] + cache_read * PRICES["cache_read"]) / 1_000_000
    cost += searches * WEB_SEARCH_PRICE
    budget.record(cost)  # counts towards the public demo's spending caps (no-op locally)
    if meter is None:
        return
    meter.append({"brain": model, "version": version, "fallback": False, "seconds": round(seconds, 1),
                  "input_tokens": usage.input_tokens + cache_write + cache_read,
                  "output_tokens": usage.output_tokens, "web_searches": searches, "cost_usd": round(cost, 5)})


def fallback_entry(name: str, version: str, error: Exception) -> dict:
    return {"brain": name, "version": version, "fallback": True, "error": str(error)[:300]}
