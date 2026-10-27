"""Code-written text for every graphic, mode and language (en, tr, es; unknown languages get en).

Used three ways:
- the `mock` backend (runs everything offline, no Azure needed),
- the fallback when the LLM text fails the verifier twice,
- examples of the expected style inside the LLM prompt.

Numbers are never written here: the text carries placeholders (`{distance_m}`, `{score}`...)
that fill.py formats per language, the same filler the LLM's text goes through. The `context`
labels (context.py) add the "why it matters" in words.
"""

from __future__ import annotations

from .fill import LANGS, fill
from .verifier import MAX_TEXT_CHARS

OUTCOME = {
    "en": {"on_target": "on target", "off_target": "off target", "blocked": "blocked", None: ""},
    "tr": {"on_target": "isabetli", "off_target": "isabetsiz", "blocked": "blok yedi", None: ""},
    "es": {"on_target": "a puerta", "off_target": "desviado", "blocked": "bloqueado", None: ""},
}
GOAL_EFFECT = {  # what the goal did to the game, as a verb phrase after the scorer's name
    "en": {"opener": "opens the scoring", "equaliser": "levels it", "go_ahead": "puts them in front",
           "extends_lead": "extends the lead", "pulls_one_back": "pulls one back"},
    "tr": {"opener": "skoru açtı", "equaliser": "eşitliği getirdi", "go_ahead": "takımını öne geçirdi",
           "extends_lead": "farkı açtı", "pulls_one_back": "farkı azalttı"},
    "es": {"opener": "abre el marcador", "equaliser": "iguala el partido", "go_ahead": "adelanta a los suyos",
           "extends_lead": "amplía la ventaja", "pulls_one_back": "recorta distancias"},
}
LEAD_IN = {  # how the attack came about
    "en": {"counter_attack": "on the counter", "set_piece": "from a set piece",
           "patient_build_up": "after patient build-up"},
    "tr": {"counter_attack": "kontra atakta", "set_piece": "duran toptan",
           "patient_build_up": "sabırlı bir paslaşmayla"},
    "es": {"counter_attack": "al contragolpe", "set_piece": "a balón parado",
           "patient_build_up": "tras una paciente elaboración"},
}
# A team as the scorer: "puts them in front" needs a player as the subject.
TEAM_GOAL_EFFECT = {"en": {"go_ahead": "go in front"}, "tr": {"go_ahead": "öne geçti"},
                    "es": {"go_ahead": "se adelanta"}}
OWN_GOAL = {"en": "og", "tr": "k.k.", "es": "p.p."}


def _l(lang: str) -> str:
    return lang if lang in LANGS else "en"


def pick(lang: str, en: str, tr: str, es: str) -> str:
    return {"en": en, "tr": tr, "es": es}[_l(lang)]


def _fit(req: dict, lang: str, *options: str) -> str:
    """The first (richest) option that fits on the graphic once filled; the last one otherwise."""
    return next((o for o in options if len(fill(o, req["values"], lang, req["facts"])) <= MAX_TEXT_CHARS),
                options[-1])


def render(req: dict, lang: str) -> dict:
    """Return {'title', 'text'} for one explain request in one language, numbers as placeholders.

    A request with no `actor` (a team-only event) gets the team-only wording: no player is named.
    A `player_focus` graphic with an `actor` is titled with the player's name (third-person voice)."""
    out = _render(req, lang)
    if req["mode"] == "player_focus" and req.get("actor"):
        out["title"] = req["actor"]
    return out


def _render(req: dict, lang: str) -> dict:
    g, mode, v = req["graphic"], req["mode"], req["values"]
    actor, target = req.get("actor") or "", req.get("target") or ""
    team, home, away = req.get("actor_team") or "", req["home"], req["away"]
    who = actor or team  # the subject of the sentence
    sub, kind = req.get("subtype"), req["event_type"]
    ctx = req.get("context") or {}
    L = _l(lang)
    how = LEAD_IN[L].get(ctx.get("lead_in"), "")

    if g == "goal_banner":
        title = pick(lang, f"GOAL! {team}", f"GOL! {team}", f"¡GOL! {team}")
        score = f"{home} {{score}} {away}"
        if sub == "own_goal":
            if not actor:
                return {"title": title, "text": pick(lang, f"Own goal. {score}", f"Kendi kalesine gol. {score}",
                                                     f"Gol en propia puerta. {score}")}
            return {"title": title, "text": pick(lang, f"Own goal by {actor}. {score}",
                                                 f"{actor} kendi kalesine attı. {score}",
                                                 f"Gol en propia puerta de {actor}. {score}")}
        if mode == "casual":
            text = pick(lang, f"{who} finds the net! {score}", f"{who} ağları sarstı! {score}",
                        f"¡{who} marca! {score}")
            return {"title": title, "text": text}
        effects = GOAL_EFFECT[L] if actor else {**GOAL_EFFECT[L], **TEAM_GOAL_EFFECT[L]}
        effect = effects.get(ctx.get("goal_effect"), pick(lang, "scores", "golü attı", "marca"))
        if sub == "penalty":
            how = pick(lang, "from the spot", "penaltıdan", "de penalti")
        short = f"{who} {effect}. {score}"
        if L == "tr" and how:
            return {"title": title, "text": _fit(req, lang, f"{who} {how} {effect}. {score}", short)}
        return {"title": title, "text": _fit(req, lang, f"{who} {effect} {how}. {score}" if how else short, short)}

    if g == "card_banner":
        red = kind == "red_card"
        title = pick(lang, "Red card" if red else "Yellow card", "Kırmızı kart" if red else "Sarı kart",
                     "Tarjeta roja" if red else "Tarjeta amarilla")
        if not actor:
            text = (pick(lang, f"{team} are a man down", f"{team} bir kişi eksik kaldı", f"{team} se queda con uno menos")
                    if red else pick(lang, f"Booking for {team}", f"{team} oyuncusuna sarı kart", f"Amarilla para {team}"))
        elif red:
            text = pick(lang, f"{actor} is sent off, {team} are a man down",
                        f"{actor} oyundan atıldı, {team} bir kişi eksik",
                        f"{actor} expulsado, {team} se queda con uno menos")
        else:
            text = pick(lang, f"{actor} is booked", f"{actor} sarı kart gördü", f"Amarilla para {actor}")
        return {"title": title, "text": text}

    if g == "stat_compare":
        ft = kind == "full_time"
        title = pick(lang, "Full-time" if ft else "Half-time", "Maç sonu" if ft else "İlk yarı sonu",
                     "Final del partido" if ft else "Descanso")
        score = f"{home} {{score}} {away}"
        # Each scorer once: "x2" would be a number the verifier cannot back.
        scorers = ", ".join(dict.fromkeys(k["player"] + (f" ({OWN_GOAL[L]})" if k["own_goal"] else "")
                                          for k in req.get("key_moments", []) if k["type"] == "goal" and k["player"]))
        goals = pick(lang, "Scorers: ", "Golcüler: ", "Goleadores: ") + scorers if scorers else ""
        options = [score]
        if "shots_home" in v:
            shots = pick(lang, "Shots {shots_home}-{shots_away}, on target {on_target_home}-{on_target_away}",
                         "Şut {shots_home}-{shots_away}, isabetli {on_target_home}-{on_target_away}",
                         "Tiros {shots_home}-{shots_away}, a puerta {on_target_home}-{on_target_away}")
            options = [f"{score}. {shots}"] + options
            if goals:
                options = [f"{score}. {shots}. {goals}", f"{shots}. {goals}"] + options
        elif goals:
            options = [f"{score}. {goals}"] + options
        return {"title": title, "text": _fit(req, lang, *options)}

    if g == "momentum_bar":
        pct = "{momentum_home}" if v["momentum_home"] >= v["momentum_away"] else "{momentum_away}"
        title = pick(lang, "Momentum", "Baskı", "Dominio")
        text = pick(lang, f"{team} on top: {pct} of the threat in the last {{window_min}} min",
                    f"Son {{window_min}} dakikada baskı {team} tarafında: {pct}",
                    f"{team} domina: {pct} del peligro en los últimos {{window_min}} min")
        return {"title": title, "text": text}

    if g == "insight_text":
        if kind == "substitution":
            title = pick(lang, "Substitution", "Oyuncu değişikliği", "Cambio")
            if not actor:
                text = pick(lang, f"{team} make a change", f"{team} oyuncu değişikliği yaptı", f"Cambio en {team}")
            else:
                text = pick(lang, f"{actor} on, {target} off", f"{actor} oyuna girdi, {target} çıktı",
                            f"Entra {actor}, sale {target}")
            return {"title": title, "text": text}
        title = pick(lang, "Ball won", "Top kazanıldı", "Balón recuperado")
        if not actor:
            if ctx.get("score_situation") == "trailing":
                text = pick(lang, f"{team} win it high up, a chance to hit back",
                            f"{team} topu rakip yarıda kaptı, geri dönmek için hücumda",
                            f"{team} roba arriba y busca la remontada")
            else:
                text = pick(lang, f"{team} win it high up the pitch and attack at once",
                            f"{team} topu rakip yarıda kaptı, hemen hücumda",
                            f"{team} roba arriba y ataca de inmediato")
        elif ctx.get("score_situation") == "trailing":
            text = pick(lang, f"{actor} wins it high up, a chance for {team} to hit back",
                        f"{actor} topu rakip yarıda kaptı, {team} geri dönmek için hücumda",
                        f"{actor} roba arriba, {team} busca la remontada")
        else:
            text = pick(lang, f"{actor} wins it high up the pitch, {team} attack at once",
                        f"{actor} topu rakip yarıda kaptı, {team} hemen hücumda",
                        f"{actor} roba arriba, {team} ataca de inmediato")
        return {"title": title, "text": text}

    if g == "shot_card":
        out = OUTCOME[L].get(sub, "")
        setup = req.get("setup_by")
        if mode == "casual" and "speed_kmh" in v:
            text = pick(lang, f"{who} hits it at {{speed_kmh}}!", f"{who} {{speed_kmh}} hızla vurdu!",
                        f"¡Disparo de {who} a {{speed_kmh}}!")
        elif mode == "casual":
            text = pick(lang, f"What a strike from {who}!", f"{who} sert vurdu!", f"¡Qué disparo de {who}!")
        else:
            parts = []
            if "goal_distance_m" in v:
                parts.append(pick(lang, "from {goal_distance_m}", "{goal_distance_m} mesafeden",
                                  "desde {goal_distance_m}"))
            if "speed_kmh" in v:
                parts.append("{speed_kmh}")
            head = pick(lang, "Shot", "Şut", "Disparo")
            if parts:
                head += " " + (" " if L == "tr" else ", ").join(parts)
            text = ", ".join(x for x in (head, out, how) if x)
        if setup:
            # "Pas: X" avoids a Turkish genitive suffix that depends on the name's vowels.
            stop = "" if text.endswith("!") else "."
            text += stop + pick(lang, f" Set up by {setup}", f" Pas: {setup}", f" Asistencia de {setup}")
        return {"title": who, "text": text}

    if g == "pass_card":
        if mode == "casual":
            text = pick(lang, "What a pass!", "Ne pas ama!", "¡Qué pase!")
        elif mode == "player_focus" and "player_passes" in v:
            text = pick(lang, "{player_passes_completed}/{player_passes} passes completed, this one {distance_m}",
                        "{player_passes_completed}/{player_passes} isabetli pas, bu {distance_m}",
                        "{player_passes_completed}/{player_passes} pases completados, este de {distance_m}")
        else:
            text = pick(lang, "{distance_m} pass, difficulty {difficulty}",
                        "{distance_m} pas, zorluk {difficulty}",
                        "Pase de {distance_m}, dificultad {difficulty}")
        return {"title": who, "text": text}

    return {"title": who, "text": ""}
