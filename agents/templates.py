"""Code-written text for every graphic, mode and language.

Used three ways:
- the `mock` backend (runs everything offline, no Azure needed),
- the fallback when the LLM text fails the verifier twice,
- examples of the expected style inside the LLM prompt.

Only numbers from `values`, the minute and the score may appear here.
"""

from __future__ import annotations

OUTCOME = {
    "en": {"on_target": "on target", "off_target": "off target", "blocked": "blocked", None: ""},
    "tr": {"on_target": "isabetli", "off_target": "isabetsiz", "blocked": "blok yedi", None: ""},
}


def render(req: dict, lang: str) -> dict:
    """Return {'title', 'text'} for one explain request in one language."""
    g, mode, v = req["graphic"], req["mode"], req["values"]
    actor, target = req.get("actor") or "", req.get("target") or ""
    team, home, away = req.get("actor_team") or "", req["home"], req["away"]
    sub, kind = req.get("subtype"), req["event_type"]
    tr = lang == "tr"

    if g == "goal_banner":
        title = f"GOL! {team}" if tr else f"GOAL! {team}"
        score = f"{home} {v['score_home']}-{v['score_away']} {away}"
        if mode == "casual":
            text = f"{actor} ağları sarstı! {score}" if tr else f"{actor} finds the net! {score}"
        else:
            text = f"{actor} golü attı. {score}" if tr else f"{actor} scores. {score}"
        return {"title": title, "text": text}

    if g == "card_banner":
        red = kind == "red_card"
        title = ("Kırmızı kart" if red else "Sarı kart") if tr else ("Red card" if red else "Yellow card")
        if red:
            text = f"{actor} oyundan atıldı, {team} bir kişi eksik" if tr else f"{actor} is sent off, {team} down to ten men"
        else:
            text = f"{actor} sarı kart gördü" if tr else f"{actor} is booked"
        return {"title": title, "text": text}

    if g == "stat_compare":
        ft = kind == "full_time"
        title = ("Maç sonu" if ft else "İlk yarı sonu") if tr else ("Full-time" if ft else "Half-time")
        return {"title": title, "text": f"{home} {v['score_home']}-{v['score_away']} {away}"}

    if g == "momentum_bar":
        pct = max(v["momentum_home"], v["momentum_away"])
        title = "Baskı" if tr else "Momentum"
        text = (f"Son {v['window_min']} dakikada baskı {team} tarafında: %{pct}" if tr
                else f"{team} on top: {pct}% of the threat in the last {v['window_min']} min")
        return {"title": title, "text": text}

    if g == "insight_text":
        if kind == "substitution":
            title = "Oyuncu değişikliği" if tr else "Substitution"
            text = f"{actor} oyuna girdi, {target} çıktı" if tr else f"{actor} on, {target} off"
            return {"title": title, "text": text}
        title = "Top kazanıldı" if tr else "Ball won"
        text = (f"{actor} topu rakip yarıda kaptı, {team} hemen hücumda" if tr
                else f"{actor} wins it high up the pitch, {team} attack at once")
        return {"title": title, "text": text}

    if g == "shot_card":
        out = OUTCOME[lang if lang in OUTCOME else "en"].get(sub, "")
        setup = req.get("setup_by")
        if mode == "casual":
            text = f"{actor} sert vurdu!" if tr else f"What a strike from {actor}!"
        else:
            parts = []
            if "goal_distance_m" in v:
                parts.append(f"{v['goal_distance_m']} m mesafeden" if tr else f"from {v['goal_distance_m']} m")
            if "speed_kmh" in v:
                parts.append(f"{v['speed_kmh']} km/s" if tr else f"{v['speed_kmh']} km/h")
            text = (f"Şut {' '.join(parts)}, {out}" if tr else f"Shot {', '.join(parts)}, {out}").rstrip(", ")
        if setup:
            # "Pas: X" avoids a Turkish genitive suffix that depends on the name's vowels.
            text += f". Pas: {setup}" if tr else f". Set up by {setup}"
        return {"title": actor, "text": text}

    if g == "pass_card":
        if mode == "casual":
            text = "Ne pas ama!" if tr else "What a pass!"
        elif mode == "player_focus" and "player_passes" in v:
            text = (f"{v['player_passes_completed']}/{v['player_passes']} isabetli pas, bu {v['distance_m']} m" if tr
                    else f"{v['player_passes_completed']}/{v['player_passes']} passes completed, this one {v['distance_m']} m")
        else:
            text = (f"{v['distance_m']} m pas, zorluk {v['difficulty']}/10" if tr
                    else f"{v['distance_m']} m pass, difficulty {v['difficulty']}/10")
        return {"title": actor, "text": text}

    return {"title": actor, "text": ""}
