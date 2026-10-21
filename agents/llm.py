"""LLM backends for the explainer.

- `mock`:    no network. Text comes from templates.py. Lets the whole pipeline run offline.
- `noisy`:   mock, but every 4th answer invents a number. Used to demo and test the verifier.
- `foundry`: Microsoft Agent Framework agent on a Microsoft Foundry (Azure OpenAI) deployment.

Every backend implements `async explain(req, feedback) -> {lang: {"title", "text"}}`.
`feedback` is the verifier's complaint from the previous attempt (or None).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import templates

INSTRUCTIONS = """You write on-screen graphics for a live football broadcast.
You get one moment as JSON: what happened, who did it, the score, and `values` (the numbers
the graphic shows). Write a short title and text for every language in `langs`.

Hard rules:
- Use ONLY numbers that appear in `values`, `minute`, `score_home` or `score_away`. Never invent,
  round differently, or convert a number. If unsure, write no number.
- Mention only the players named in `actor`, `target` and `setup_by` (the passer who set up a
  shot). Copy each name exactly as given, initial included ("K. Aydin", never "Aydin" or "K. Aydın").
  In Turkish, add case suffixes after an apostrophe ("K. Aydin'den"). All clubs and players are fictional.
- `text` at most 100 characters, `title` at most 35.
- mode "analyst": precise and tactical, may use the numbers. Explain WHY the moment matters.
- mode "casual": warm and simple, like talking to a friend new to football; avoid numbers except the score.
- mode "player_focus": everything from the point of view of `actor`.
- Write natural, native text in each language (not a word-by-word translation).

Reply with JSON only, no markdown: {"<lang>": {"title": "...", "text": "..."}, ...}"""


class MockBackend:
    name = "mock"

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        return {lang: templates.render(req, lang) for lang in req["langs"]}


class NoisyBackend(MockBackend):
    """Behaves like a careless LLM: sometimes invents a statistic."""

    name = "noisy"

    def __init__(self) -> None:
        self.calls = 0

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        self.calls += 1
        out = await super().explain(req, feedback)
        if feedback is None and self.calls % 4 == 0:
            for lang in out:
                out[lang]["text"] = (out[lang]["text"] + " (87% xG)")[:100]
        return out


class FoundryBackend:
    """Explainer agent on Microsoft Foundry, built with Microsoft Agent Framework.

    Needs in .env: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT and either
    AZURE_OPENAI_API_KEY or an `az login` session (DefaultAzureCredential).
    Answers are cached on disk so re-runs cost nothing.
    """

    name = "foundry"

    def __init__(self, cache_path: str | Path = "data/generated/llm_cache.json") -> None:
        from agent_framework import Agent
        from agent_framework.openai import OpenAIChatCompletionClient

        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        kwargs = {"model": deployment, "azure_endpoint": endpoint,
                  "api_version": os.environ.get("AZURE_OPENAI_API_VERSION") or None}
        if os.environ.get("AZURE_OPENAI_API_KEY"):
            kwargs["api_key"] = os.environ["AZURE_OPENAI_API_KEY"]
        else:
            from azure.identity import DefaultAzureCredential
            kwargs["credential"] = DefaultAzureCredential()
        client = OpenAIChatCompletionClient(**{k: v for k, v in kwargs.items() if v is not None})
        self.agent = Agent(client, instructions=INSTRUCTIONS, name="explainer")
        self.deployment = deployment
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text("utf-8")) if self.cache_path.exists() else {}

    def save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        prompt = json.dumps(req, ensure_ascii=False)
        if feedback:
            prompt += f"\n\nYour previous answer was rejected by the verifier: {feedback}\nFix it."
        key = cache_key(self.deployment, prompt)
        if key not in self.cache:
            resp = await self.agent.run(prompt)
            self.cache[key] = resp.text
        return parse_json_reply(self.cache[key], req["langs"])


def cache_key(deployment: str, prompt: str, instructions: str = INSTRUCTIONS) -> str:
    """Changing the instructions or the model must not return answers cached from the old ones."""
    return hashlib.sha256("\0".join((instructions, deployment, prompt)).encode()).hexdigest()


def parse_json_reply(raw: str, langs: list[str]) -> dict:
    """Parse the model's JSON, tolerating ```json fences. Missing languages -> empty text."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    return {lang: {"title": str(data.get(lang, {}).get("title", "")),
                   "text": str(data.get(lang, {}).get("text", ""))} for lang in langs}


def make_backend(name: str):
    if name == "mock":
        return MockBackend()
    if name == "noisy":
        return NoisyBackend()
    if name == "foundry":
        return FoundryBackend()
    raise ValueError(f"unknown backend {name!r} (mock | noisy | foundry)")
