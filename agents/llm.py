"""LLM backends for the explainer.

- `mock`:    no network. Text comes from templates.py. Lets the whole pipeline run offline.
- `noisy`:   mock, but every 4th answer invents a number as a stray digit. Used to demo and test the verifier.
- `foundry`: Microsoft Agent Framework agent on a Microsoft Foundry (Azure OpenAI) deployment.

Every backend implements `async explain(req, feedback) -> {lang: {"title", "text"}}`.
`feedback` is the verifier's complaint from the previous attempt (or None).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
from pathlib import Path

from . import templates
from .fill import fill
from .verifier import MAX_TEXT_CHARS, MAX_TITLE_CHARS

INSTRUCTIONS = f"""You write on-screen graphics for a live football broadcast.
You get one moment as JSON: what happened, who did it, the score, and `placeholders`: each number
the graphic may show, mapped to how it will read on screen. Write a short title and text for every
language in `langs`.

Numbers:
- Never write a digit, not even "1/1" or "4 of 5", and never a number in words ("two from two",
  "ikide iki", "dos de dos"). Write a number only as a key of `placeholders`,
  exactly as given ("{{distance_m}}", "{{player_passes_completed}}/{{player_passes}}", "{{score}}"...). The
  mapped value is only there so your words fit the number (1/1 is a perfect start, 4/9 is not).
  Use a placeholder only where the number says something; fewer numbers beat a forced one.
  "{{score}}" is the match score: "lead {{score}}", "level at {{score}}", never "wide of {{score}}" or
  "finish with {{score}}".
  Other numbers in `facts` are background: never write them. If no placeholder fits, write no number.
- Code replaces each placeholder with the number AND its unit or sign, in the form of the language:
  "{{distance_m}}" becomes "28 m", "{{speed_kmh}}" "112 km/h" (tr "112 km/sa"), "{{momentum_home}}"
  "62%" (tr "%62", es "62 %"), "{{difficulty}}" "7/10", "{{score}}" "2-1".
  So never write a unit, "%", "yüzde", "por ciento", "/10" or "metre" next to a placeholder: "{{distance_m}} pass", never "{{distance_m}} m pass" or "{{momentum_home}}%".
- Turkish: you cannot see the number, so never put a case suffix on a placeholder ("{{score}}'lik",
  "%{{momentum_home}}'ü" are wrong): rephrase. Only distances and speeds may take a suffix, always after an
  apostrophe and before a noun ("{{distance_m}}'lik pas", never "{{distance_m}}lik" or a bare "{{distance_m}}'lik"). An apostrophe goes only after a name
  or a placeholder, never after a common word ("son üçte birlik bölgeye", never "üçte bir'e").
- "{{difficulty}}" is a stat tag: its own clause after a comma, with its noun: "..., difficulty {{difficulty}}",
  tr "..., zorluk {{difficulty}}", es "..., dificultad {{difficulty}}". Never "a difficult {{difficulty}} pass".

Players:
- Mention only the players named in `actor`, `target`, `setup_by` (the passer who set up a shot) and
  `key_moments` (goals and red cards so far, for half-time and full-time recaps). Copy each name exactly
  as given, initial included, every time, titles too ("K. Aydin", never "Aydin" or "K. Aydın"). In
  Turkish, add case suffixes after an apostrophe ("K. Aydin'den"), in harmony with the name's last written
  vowel and letter: "P. Rowntree'nin", "P. Rowntree'ye" (never "'nun", "'yu"), "A. Kurt'tan", "C. Hollis'e".
  All clubs and players are fictional.
  A `key_moments` entry with no `player` is credited to the team only.
- If `name_players` is false, we are not sure who played the ball: name the team, not a player.
  There is no `actor`; `subject` (the team) is who the text is about ("Bosphorus FC pass").

Length: `text` at most {MAX_TEXT_CHARS} characters, `title` at most {MAX_TITLE_CHARS}, counted with the
numbers filled in; aim for 60 to 90 and 25. One sentence, two short ones at most. No hashtags, no emoji.

Modes:
- "analyst": precise and tactical, may use every placeholder. Explain WHY the moment matters.
  `context` says why, in labels computed by code: `goal_effect` (opener, equaliser, go_ahead,
  extends_lead, pulls_one_back), `score_situation` of the acting team, `lead_in` (how the attack
  came about), `momentum` over the last minutes, `phase` of the match. Use them; do not contradict them.
  Never print a label as it is ("go_ahead", "patient_build_up"): say it in words.
- "casual": warm and simple, like talking to a friend new to football; few numbers.
- "player_focus": about `actor`, in the third person. When there is an `actor`, the title is the
  player's name exactly as given, nothing else ("K. Aydin"). The text says what the player did and how their game is going
  ("Completes {{player_passes_completed}}/{{player_passes}}, this one {{distance_m}}"). Never the first
  person and never quotes: the player is fictional and did not say anything.

Style: write each language as a native commentator of that language would, not a translation of the
English: en like a British TV graphic, tr like a Turkish broadcast, es like a Spanish one. Use the
football words of each language: final third = tr "son üçte birlik bölge" / es "último tercio"; switch of play =
tr "oyunun yönünü değiştiren pas" / es "cambio de orientación"; long ball = tr "uzun top" / es "balón
largo"; the box = tr "ceza sahası" (never "kutu") / es "el área"; on target = tr "isabetli" / es "a puerta";
opens the scoring = tr "skoru açtı" / es "abre el marcador"; momentum = tr "baskı" / es "dominio";
after a red card = "a man down", tr "eksik kaldı", es "con uno menos" (never "down to ten": a count). Natural word order (tr verb last: "T. Castell,
C. Hollis'i buldu"). Titles start with a capital letter, the rest lower case except names ("Half-time
picture", not "Half-Time Picture"). No full stop at the end of a text.

Example. Input: {{"mode": "player_focus", "actor": "H. Koc", "target": "T. Sahin", "subtype": "long",
"placeholders": {{"{{distance_m}}": "29 m", "{{player_passes}}": "1", "{{player_passes_completed}}": "1", ...}}}}
Reply: {{"en": {{"title": "H. Koc", "text": "Perfect start: {{player_passes_completed}}/{{player_passes}}, this one a {{distance_m}} ball to T. Sahin"}},
"tr": {{"title": "H. Koc", "text": "Kusursuz başlangıç: {{player_passes_completed}}/{{player_passes}}, T. Sahin'e {{distance_m}}'lik uzun top"}},
"es": {{"title": "H. Koc", "text": "Arranque perfecto: {{player_passes_completed}}/{{player_passes}}, balón largo de {{distance_m}} a T. Sahin"}}}}
Before replying, check: no digit 0-9 anywhere outside a placeholder.

Reply with JSON only, no markdown: {{"<lang>": {{"title": "...", "text": "..."}}, ...}}"""

# Wait before each retry after a rate limit (HTTP 429), in seconds; jitter is added on top.
RATE_LIMIT_DELAYS_S = (2, 4, 8, 16, 32, 60)


class MockBackend:
    name = "mock"

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        return {lang: templates.render(req, lang) for lang in req["langs"]}


class NoisyBackend(MockBackend):
    """Behaves like a careless LLM: sometimes invents a statistic, written as digits instead of a placeholder."""

    name = "noisy"

    def __init__(self) -> None:
        self.calls = 0

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        self.calls += 1
        out = await super().explain(req, feedback)
        if feedback is None and self.calls % 4 == 0:
            for lang in out:
                out[lang]["text"] += " (87% xG)"
        return out


class FoundryBackend:
    """Explainer agent on Microsoft Foundry, built with Microsoft Agent Framework.

    Needs in .env: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT and either
    AZURE_OPENAI_API_KEY or an `az login` session (DefaultAzureCredential).
    Answers are cached on disk after every new answer, so a crash keeps what was paid for
    and re-runs cost nothing. Rate limits (429) are retried with exponential backoff.
    `agent` and `deployment` replace the env-built agent (tests pass a fake).
    """

    name = "foundry"

    def __init__(self, cache_path: str | Path = "data/generated/llm_cache.json",
                 agent=None, deployment: str | None = None) -> None:
        if agent is None:
            agent, deployment = self._agent_from_env()
        self.agent = agent
        self.deployment = deployment
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text("utf-8")) if self.cache_path.exists() else {}
        # Paid calls this run (cache hits cost nothing), for the cost line in agents_report.json.
        self.usage = {"calls": 0, "cached": 0, "input_tokens": 0, "output_tokens": 0}

    @staticmethod
    def _agent_from_env():
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
        return Agent(client, instructions=INSTRUCTIONS, name="explainer"), deployment

    def save_cache(self) -> None:
        """Write via a temp file and rename, so a crash mid-write never corrupts the cache."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.cache_path)

    async def run_with_retry(self, prompt: str) -> str:
        """agent.run, retried on rate limits after RATE_LIMIT_DELAYS_S (+ up to 1 s jitter)."""
        for delay in (*RATE_LIMIT_DELAYS_S, None):
            try:
                response = await self.agent.run(prompt)
                used = getattr(response, "usage_details", None) or {}
                self.usage["calls"] += 1
                self.usage["input_tokens"] += used.get("input_token_count") or 0
                self.usage["output_tokens"] += used.get("output_token_count") or 0
                return response.text
            except Exception as ex:
                if delay is None or not is_rate_limit(ex):
                    raise
                await asyncio.sleep(delay + random.uniform(0, 1))

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        prompt = json.dumps(prompt_view(req), ensure_ascii=False)
        if feedback:
            prompt += f"\n\nYour previous answer was rejected by the verifier: {feedback}\nFix it."
        key = cache_key(self.deployment, prompt)
        if key not in self.cache:
            self.cache[key] = await self.run_with_retry(prompt)
            self.save_cache()
        else:
            self.usage["cached"] += 1
        return parse_json_reply(self.cache[key], req["langs"])


def prompt_view(req: dict) -> dict:
    """The request as the model sees it: `placeholders` maps each placeholder to what it reads on
    screen ("{distance_m}" -> "28 m"), so the number sits next to the only way to write it and the
    unit is visibly part of it. Not "{minute}": the broadcast clock already shows it, and offered, the
    model wrote "at 1'" on pass cards and "must settle down at 4'" on a booking. `values` is left out:
    it would repeat the numbers without the placeholders."""
    view = {k: v for k, v in req.items() if k not in ("values", "placeholders")}
    view["placeholders"] = {p: fill(p, req["values"], "en", req["facts"]) for p in req["placeholders"]
                            if p != "{minute}"}
    return view


def is_rate_limit(ex: BaseException) -> bool:
    """True for HTTP 429 / openai.RateLimitError, also when wrapped (e.g. a ChatClientException
    whose cause is one). Duck-typed so this module does not import openai."""
    seen = set()
    while ex is not None and id(ex) not in seen:
        seen.add(id(ex))
        status = getattr(ex, "status_code", None) or getattr(getattr(ex, "response", None), "status_code", None)
        if type(ex).__name__ == "RateLimitError" or status == 429:
            return True
        ex = ex.__cause__ or ex.__context__
    return False


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
