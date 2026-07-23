"""The reasoning socket. Everything talks to LLMClient, never to Gemini directly,
so the model is swappable and the rest of the platform never notices.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from abc import ABC, abstractmethod


class LLMClient(ABC):
    """One job: turn a prompt into text."""

    @abstractmethod
    def ask(self, prompt: str) -> str: ...


class GeminiClient(LLMClient):
    """Real plug. Uses plain urllib to stay dependency-light."""

    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model: str = "gemini-2.5-flash", timeout: int = 30):
        self.model = model
        self.timeout = timeout
        self.key = os.environ["GEMINI_API_KEY"]  # raises early if missing

    def ask(self, prompt: str) -> str:
        url = f"{self.ENDPOINT}/{self.model}:generateContent"
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0},
            }
        ).encode()
        # Pass the key as a header (x-goog-api-key). This works for both the new
        # AQ.* "auth keys" and legacy AIza keys, and keeps the key out of URLs/logs.
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.load(r)
        return data["candidates"][0]["content"]["parts"][0]["text"]


class ScriptedLLMClient(LLMClient):
    """Test/demo plug: returns canned responses (or raises to simulate an outage)."""

    def __init__(self, responses=None, raise_error: Exception | None = None):
        self._responses = list(responses or [])
        self._raise = raise_error
        self.calls: list[str] = []

    def ask(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self._raise is not None:
            raise self._raise
        if not self._responses:
            raise RuntimeError("ScriptedLLMClient ran out of responses")
        return self._responses.pop(0)


def ask_json(client: LLMClient, prompt: str, fallback: dict) -> dict:
    """Ask for JSON, but NEVER raise: on any error (429, bad JSON, timeout)
    return the provided fallback. This is what keeps the agent alive when the
    model is unavailable.
    """
    try:
        raw = client.ask(prompt + "\n\nReturn ONLY valid JSON, no markdown, no prose.")
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:  # noqa: BLE001 - deliberately broad; we must not crash
        # stderr, so diagnostics never pollute stdout that a caller may capture
        # (e.g. `config=$(python -m ai.propose_config ...)` in CI).
        print(f"[ai] falling back (reason: {e})", file=sys.stderr)
        return dict(fallback)
