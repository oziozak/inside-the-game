"""Code-written text for every graphic, mode and language (en, tr, es; unknown languages get en).

Used three ways:
- the `mock` backend (runs everything offline, no Azure needed),
- the fallback when the LLM text fails the verifier twice,
- examples of the expected style inside the LLM prompt.

Only numbers from `values`, the minute and the score may appear here. The `context` labels
(context.py) add the "why it matters" in words.
"""

from __future__ import annotations

from .verifier import MAX_TEXT_CHARS

LANGS = ("en", "tr", "es")

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
OWN_GOAL = {"en": "og", "tr": "k.k.", "es": "p.p."}


def _l(lang: str) -> str:
    return lang if lang in LANGS else "en"


def pick(lang: str, en: str, tr: str, es: str) -> str:
    return {"en": en, "tr": tr, "es": es}[_l(lang)]


def _fit(*options: str) -> str:
    """The first (richest) option that fits on the graphic; the last one otherwise."""
    return next((o for o in options if len(o) <= MAX_TEXT_CHARS), options[-1])


def render(req: dict, lang: str) -> dict:
    """Return {'title', 'text'} for one explain request in one language."""
    g, mode, v = req["graphic"], req["mode"], req["values"]
    actor, target = req.get("actor") or "", req.get("target") or ""
    team, home, away = req.get("actor_team") or "", req["home"], req["away"]
    sub, kind = req.get("subtype"), req["event_type"]
    ctx = req.get("context") or {}
    L = _l(lang)
    how = LEAD_IN[L].get(ctx.get("lead_in"), "")

    if g == "goal_banner":
        title = pick(lang, f"GOAL! {team}", f"GOL! {team}", f"¡GOL! {team}")
        score = f"{home} {v['score_home']}-{v['score_away']} {away}"
        if sub == "own_goal":
            return {"title": title, "text": pick(lang, f"Own goal by {actor}. {score}",
                                                 f"{actor} kendi kalesine attı. {score}",
                                                 f"Gol en propia puerta de {actor}. {score}")}
        if mode == "casual":
            text = pick(lang, f"{actor} finds the net! {score}", f"{actor} ağları sarstı! {score}",
                        f"¡{actor} marca! {score}")
            return {"title": title, "text": text}
        effect = GOAL_EFFECT[L].get(ctx.get("goal_effect"), pick(lang, "scores", "golü attı", "marca"))
        if sub == "penalty":
            how = pick(lang, "from the spot", "penaltıdan", "de penalti")
        short = f"{actor} {effect}. {score}"
        if L == "tr" and how:
            return {"title": title, "text": _fit(f"{actor} {how} {effect}. {score}", short)}
        return {"title": title, "text": _fit(f"{actor} {effect} {how}. {score}" if how else short, short)}

    if g == "card_banner":
        red = kind == "red_card"
        title = pick(lang, "Red card" if red else "Yellow card", "Kırmızı kart" if red else "Sarı kart",
                     "Tarjeta roja" if red else "Tarjeta amarilla")
        if red:
            text = pick(lang, f"{actor} is sent off, {team} down to ten men",
                        f"{actor} oyundan atıldı, {team} bir kişi eksik",
                        f"{actor} expulsado, {team} se queda con diez")
        else:
            text = pick(lang, f"{actor} is booked", f"{actor} sarı kart gördü", f"Amarilla para {actor}")
        return {"title": title, "text": text}

    if g == "stat_compare":
        ft = kind == "full_time"
        title = pick(lang, "Full-time" if ft else "Half-time", "Maç sonu" if ft else "İlk yarı sonu",
                     "Final del partido" if ft else "Descanso")
        score = f"{home} {v['score_home']}-{v['score_away']} {away}"
        # Each scorer once: "x2" would be a number the verifier cannot back.
        scorers = ", ".join(dict.fromkeys(k["player"] + (f" ({OWN_GOAL[L]})" if k["own_goal"] else "")
                                          for k in req.get("key_moments", []) if k["type"] == "goal" and k["player"]))
        goals = pick(lang, "Scorers: ", "Golcüler: ", "Goleadores: ") + scorers if scorers else ""
        options = [score]
        if "shots_home" in v:
            shots = pick(lang, f"Shots {v['shots_home']}-{v['shots_away']}, on target {v['on_target_home']}-{v['on_target_away']}",
                         f"Şut {v['shots_home']}-{v['shots_away']}, isabetli {v['on_target_home']}-{v['on_target_away']}",
                         f"Tiros {v['shots_home']}-{v['shots_away']}, a puerta {v['on_target_home']}-{v['on_target_away']}")
            options = [f"{score}. {shots}"] + options
            if goals:
                options = [f"{score}. {shots}. {goals}", f"{shots}. {goals}"] + options
        elif goals:
            options = [f"{score}. {goals}"] + options
        return {"title": title, "text": _fit(*options)}

    if g == "momentum_bar":
        pct = max(v["momentum_home"], v["momentum_away"])
        title = pick(lang, "Momentum", "Baskı", "Dominio")
        text = pick(lang, f"{team} on top: {pct}% of the threat in the last {v['window_min']} min",
                    f"Son {v['window_min']} dakikada baskı {team} tarafında: %{pct}",
                    f"{team} domina: {pct}% del peligro en los últimos {v['window_min']} min")
        return {"title": title, "text": text}

    if g == "insight_text":
        if kind == "substitution":
            title = pick(lang, "Substitution", "Oyuncu değişikliği", "Cambio")
            text = pick(lang, f"{actor} on, {target} off", f"{actor} oyuna girdi, {target} çıktı",
                        f"Entra {actor}, sale {target}")
            return {"title": title, "text": text}
        title = pick(lang, "Ball won", "Top kazanıldı", "Balón recuperado")
        if ctx.get("score_situation") == "trailing":
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
        if mode == "casual":
            text = pick(lang, f"What a strike from {actor}!", f"{actor} sert vurdu!", f"¡Qué disparo de {actor}!")
        else:
            parts = []
            if "goal_distance_m" in v:
                parts.append(pick(lang, f"from {v['goal_distance_m']} m", f"{v['goal_distance_m']} m mesafeden",
                                  f"desde {v['goal_distance_m']} m"))
            if "speed_kmh" in v:
                parts.append(pick(lang, f"{v['speed_kmh']} km/h", f"{v['speed_kmh']} km/s", f"{v['speed_kmh']} km/h"))
            head = pick(lang, "Shot", "Şut", "Disparo")
            if parts:
                head += " " + (" " if L == "tr" else ", ").join(parts)
            text = ", ".join(x for x in (head, out, how) if x)
        if setup:
            # "Pas: X" avoids a Turkish genitive suffix that depends on the name's vowels.
            text += pick(lang, f". Set up by {setup}", f". Pas: {setup}", f". Asistencia de {setup}")
        return {"title": actor, "text": text}

    if g == "pass_card":
        if mode == "casual":
            text = pick(lang, "What a pass!", "Ne pas ama!", "¡Qué pase!")
        elif mode == "player_focus" and "player_passes" in v:
            done, total, dist = v["player_passes_completed"], v["player_passes"], v["distance_m"]
            text = pick(lang, f"{done}/{total} passes completed, this one {dist} m",
                        f"{done}/{total} isabetli pas, bu {dist} m",
                        f"{done}/{total} pases completados, este de {dist} m")
        else:
            text = pick(lang, f"{v['distance_m']} m pass, difficulty {v['difficulty']}/10",
                        f"{v['distance_m']} m pas, zorluk {v['difficulty']}/10",
                        f"Pase de {v['distance_m']} m, dificultad {v['difficulty']}/10")
        return {"title": actor, "text": text}

    return {"title": actor, "text": ""}
