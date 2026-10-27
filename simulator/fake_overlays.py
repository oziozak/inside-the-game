"""Fake overlays: a stand-in for the director agent, so the web player has
something to draw in data/fake/. Templates only; the real director (agents/)
replaces this. Not part of the simulator's ground truth.
"""

from __future__ import annotations


def build_overlays(events, info):
    """Template overlays (analyst/en, casual/en, casual/tr) for goals, shots,
    cards and long passes, one graphic at a time."""
    names = {p["id"]: p["name"] for t in ("home", "away") for p in info[t]["players"]}
    tname = {"home": info["home"]["name"], "away": info["away"]["name"]}
    variants = [("analyst", "en"), ("casual", "en"), ("casual", "tr")]
    out = []
    busy_until = -1.0
    for e in events:
        typ = e["type"]
        pid = e.get("from")
        nm = names.get(pid, "")
        item = None
        if typ == "goal":
            s = e["score"]
            item = ("goal_banner", 0.5, 8, 1.0, "top-left", {"home": s["home"], "away": s["away"]}, {
                ("analyst", "en"): f"GOAL {tname[e['team']]}: {nm}. {s['home']}-{s['away']}",
                ("casual", "en"): f"GOAL! {nm} scores for {tname[e['team']]}!",
                ("casual", "tr"): f"GOL! {nm}, {tname[e['team']]} için skoru değiştirdi!"})
        elif typ == "shot":
            v = {"speed_kmh": e["speed_kmh"], "distance_m": e["distance_m"]}
            item = ("shot_card", 0.8, 5, 0.8, "bottom-left", v, {
                ("analyst", "en"): f"Shot {e['speed_kmh']} km/h, {e['subtype'].replace('_', ' ')}",
                ("casual", "en"): f"What a strike from {nm}!",
                ("casual", "tr"): f"{nm} sert vurdu!"})
        elif typ in ("yellow_card", "red_card"):
            color = "Yellow" if typ == "yellow_card" else "Red"
            tr_color = "Sarı" if typ == "yellow_card" else "Kırmızı"
            item = ("card_banner", 1.0, 5, 0.9, "top-right", {}, {
                ("analyst", "en"): f"{color} card: {nm}",
                ("casual", "en"): f"{color} card for {nm}",
                ("casual", "tr"): f"{nm} {tr_color.lower()} kart gördü"})
        elif typ == "pass" and e.get("success") and e.get("distance_m", 0) >= 40:
            v = {"distance_m": e["distance_m"], "speed_kmh": e["speed_kmh"]}
            item = ("pass_card", 1.5, 5, 0.6, "bottom-left", v, {
                ("analyst", "en"): f"{e['distance_m']:.0f} m {e.get('subtype', 'pass')} pass, {e['speed_kmh']} km/h",
                ("casual", "en"): f"Great long ball from {nm}!",
                # No suffix on the name: its vowel harmony depends on the name.
                ("casual", "tr"): f"{nm} harika bir uzun top gönderdi!"})
        if not item:
            continue
        graphic, lag, dur, prio, where, values, texts = item
        start = e["t"] + lag
        if start < busy_until and prio < 1.0:
            continue                               # one graphic at a time
        busy_until = start + dur
        for mode, lang in variants:
            out.append({"start": round(start, 2), "duration": dur, "graphic": graphic,
                        "event_ids": [e["id"]], "player": pid, "priority": prio,
                        "position": where, "title": nm or tname.get(e["team"], ""),
                        "text": texts[(mode, lang)], "values": values,
                        "mode": mode, "lang": lang})
    out.sort(key=lambda o: o["start"])
    return [{"id": f"o{i:04d}", **o} for i, o in enumerate(out, 1)]
