"""Code-written text for the analyst report (agents/analyst.py), per topic and language (en, tr, es).

Used as the `mock` backend and as the fallback when the LLM's text fails the verifier twice. Like
templates.py, numbers are placeholders (`{home_line_m}`, `{score}`) that fill.py formats per language,
and no sentence names a player: the report is about teams.

An insight request (analyst.insight_request) gives `topic`, `team` (home, away or both), `labels` (the code's
reading of the facts, sides as "home"/"away") and `placeholders`. `hedged` insights start with a hedge.
"""

from __future__ import annotations

from .templates import pick

TITLES = {
    "shape": ("Shape", "Diziliş", "Dibujo táctico"),
    "defensive_line": ("Line height", "Savunma hattı", "Altura de la línea"),
    "compactness": ("Compactness", "Kompaktlık", "Bloque compacto"),
    "width": ("Width", "Genişlik", "Amplitud"),
    "flanks": ("Attacking flank", "Hücum kanadı", "Banda de ataque"),
    "pressing": ("Pressing height", "Pres yüksekliği", "Altura de la presión"),
    "directness": ("Directness", "Direkt oyun", "Juego directo"),
    "progression": ("Progression", "Topu ileri taşıma", "Progresión"),
}
CHANGE_TITLES = {"goal": ("After the goal", "Golden sonra", "Tras el gol"),
                 "red_card": ("After the red card", "Kırmızı karttan sonra", "Tras la roja")}
FLANK = {"left": ("down the left", "sol kanattan", "por la izquierda"),
         "centre": ("through the middle", "merkezden", "por el centro"),
         "right": ("down the right", "sağ kanattan", "por la derecha")}
HEDGE = ("On limited evidence, ", "Sınırlı veriye göre, ", "Con datos limitados, ")


def _p(key: str) -> str:
    """A placeholder."""
    return "{" + key + "}"


def _sides(req: dict, label: str) -> tuple[str, str] | None:
    """(side the label names, the other side), or None when the label reads level."""
    side = req["labels"].get(label)
    return (side, "away" if side == "home" else "home") if side in ("home", "away") else None


def _lower_first(text: str, names: tuple[str, ...]) -> str:
    """`text` to follow a hedge: its first letter lower case, unless it starts with a team name."""
    if not text or text.startswith(names):
        return text
    return ("i" if text[0] == "İ" else text[0].lower()) + text[1:]


def render(req: dict, lang: str, names: dict[str, str]) -> dict:
    """{'title', 'text'} for one insight request in one language. `names` maps home/away to team names."""
    title, text = _render(req, lang, names)
    if req.get("hedged"):
        text = pick(lang, *HEDGE) + _lower_first(text, tuple(names.values()))
    return {"title": title, "text": text}


def _render(req: dict, lang: str, n: dict[str, str]) -> tuple[str, str]:
    topic, labels = req["topic"], req["labels"]
    home, away = n["home"], n["away"]
    title = pick(lang, *TITLES.get(topic, ("Analysis", "Analiz", "Análisis")))

    if topic == "shape":
        differs = [s for s in ("home", "away") if not labels[f"{s}_as_sheet"]]
        if not differs:
            return title, pick(lang, f"{home} lined up in a {{home_shape}} against {away}'s {{away_shape}}, both as on the team sheet",
                               f"{home} {{home_shape}}, {away} {{away_shape}} dizilişiyle oynadı, kağıt üzerindeki gibi",
                               f"{home} formó con un {{home_shape}} ante el {{away_shape}} de {away}, como en la alineación")
        x = differs[0]
        y = "away" if x == "home" else "home"
        xs, xsh, ys = _p(f"{x}_shape"), _p(f"{x}_sheet_shape"), _p(f"{y}_shape")
        if len(differs) == 2:
            ysh = _p(f"{y}_sheet_shape")
            return title, pick(lang, f"Neither side stood as named: {n[x]} played a {xs} (sheet {xsh}), {n[y]} a {ys} (sheet {ysh})",
                               f"Takımlar kağıt üzerindeki gibi dizilmedi: {n[x]} {xsh} yerine {xs}, {n[y]} {ysh} yerine {ys}",
                               f"Ningún equipo formó como en la alineación: {n[x]} jugó un {xs} (no un {xsh}), {n[y]} un {ys} (no un {ysh})")
        return title, pick(lang, f"{n[x]} were named in a {xsh} but stood in a {xs} on the pitch; {n[y]} played their {ys}",
                           f"{n[x]} kağıt üzerinde {xsh}, sahada ise {xs} dizilişindeydi; {n[y]} {ys} ile oynadı",
                           f"{n[x]} salió con un {xsh} en la alineación, pero en el campo formó un {xs}; {n[y]} jugó con un {ys}")

    if topic in ("defensive_line", "compactness", "width", "directness", "progression", "pressing"):
        return title, _compare(req, lang, n)

    if topic == "flanks":
        s = req["team"]
        way = pick(lang, *FLANK[labels["flank"]])
        pct, count = _p(f"{s}_flank_pct"), _p(f"{s}_passes_to_flank")
        return title, pick(lang, f"{n[s]} attacked mostly {way}: {count} passes, {pct} of all their passes into the final third",
                           f"{n[s]} son üçte birlik bölgeye en çok {way} girdi: {count} pas, bu bölgeye attığı paslarda oran {pct}",
                           f"{n[s]} atacó sobre todo {way}: {count} pases, el {pct} de todos sus pases al último tercio")

    if topic == "change":
        ev = labels["event"]
        title = pick(lang, *CHANGE_TITLES[ev])
        by, t = n[labels["by"]], n[req["team"]]
        b, a = "{line_before_m}", "{line_after_m}"
        after = {"goal": (f"After {by}'s goal", f"{by} golünden sonra", f"Tras el gol de {by}"),
                 "red_card": (f"After {by}'s red card", f"{by} kırmızı kart gördükten sonra", f"Tras la roja a {by}")}[ev]
        en, tr, es = after
        moved = labels["moved"]
        if moved == "level":
            return title, pick(lang, f"{en}, {t} kept their back line where it was: {b} from their own goal before, {a} after",
                               f"{tr} {t} savunma hattını aynı yükseklikte tuttu: önce {b}, sonra {a}",
                               f"{es}, {t} mantuvo su línea defensiva: a {b} de su portería antes, a {a} después")
        higher = moved == "higher"
        return title, pick(lang, f"{en}, {t} defended {'higher up' if higher else 'deeper'}: their back line moved from {b} to {a} from their own goal",
                           f"{tr} {t} savunma hattını {'daha öne taşıdı' if higher else 'daha geriye çekti'}: önce {b}, sonra {a}",
                           f"{es}, {t} {'adelantó' if higher else 'retrasó'} su línea defensiva: de {b} a {a} de su portería")
    return title, ""


# topic -> (label naming the side, values key ending, then en / tr / es sentences for a side and for level).
# In the side sentences {X} is that side's team and {x} its placeholder, {Y} / {y} the other's.
COMPARE = {
    "defensive_line": ("higher_line", "line_m", (
        "{X} defended higher up the pitch without the ball: a back line {x} from their own goal, against {y} for {Y}",
        "{X} topsuzken savunma hattını daha önde tuttu: kendi kalesinden {x}, {Y} ise {y}",
        "{X} defendió con la línea más adelantada sin balón: a {x} de su portería, por {y} de {Y}"), (
        "Both back lines held a similar height without the ball: {h} for {H}, {a} for {A}",
        "Takımlar topsuzken savunma hattını benzer yükseklikte tuttu: {H} {h}, {A} {a}",
        "Ambas defensas mantuvieron una altura parecida sin balón: {h} para {H}, {a} para {A}")),
    "compactness": ("more_compact", "compact_m", (
        "{X} kept a tighter block without the ball: {x} from defence to attack, against {y} for {Y}",
        "{X} topsuzken daha kompakt kaldı: savunmadan hücuma {x}, {Y} ise {y}",
        "{X} fue un bloque más compacto sin balón: {x} de la defensa al ataque, por {y} de {Y}"), (
        "Both teams kept a similar distance from defence to attack without the ball: {H} {h}, {A} {a}",
        "Takımlar topsuzken benzer bir kompaktlıkta kaldı: {H} {h}, {A} {a}",
        "Ambos equipos mantuvieron un bloque parecido sin balón: {h} para {H}, {a} para {A}")),
    "width": ("wider", "width_m", (
        "{X} spread wider in possession: {x} between their outermost players, against {y} for {Y}",
        "{X} topa sahipken sahayı daha geniş kullandı: oyuncuları arasında {x}, {Y} ise {y}",
        "{X} abrió más el campo con balón: {x} de amplitud, por {y} de {Y}"), (
        "Both teams spread to a similar width in possession: {H} {h}, {A} {a}",
        "Takımlar topa sahipken benzer genişlikte oynadı: {H} {h}, {A} {a}",
        "Ambos equipos dieron una amplitud parecida con balón: {h} para {H}, {a} para {A}")),
    "pressing": ("more_high_regains", "high_regains", (
        "{X} pressed higher: regains in the final third, {x} to {y} for {Y}",
        "{X} daha önde pres yaptı: son üçte birlik bölgede top kazanma {x}, {Y} ise {y}",
        "{X} presionó más arriba: recuperaciones en el último tercio, {x} frente a {y} de {Y}"), (
        "The pressing was even: regains in the final third, {H} {h}, {A} {a}",
        "Pres yüksekliği dengeliydi: son üçte birlik bölgede top kazanma {H} {h}, {A} {a}",
        "La presión estuvo igualada: recuperaciones en el último tercio, {h} para {H} y {a} para {A}")),
    "directness": ("more_direct", "long_pct", (
        "{X} played more directly: {x} of their passes were long balls, against {y} for {Y}",
        "{X} daha direkt oynadı: uzun top oranı {x}, {Y} için {y}",
        "{X} jugó más directo: el {x} de sus pases fueron balones largos, por el {y} de {Y}"), (
        "Both sides mixed in long balls at a similar rate: {H} {h}, {A} {a}",
        "Takımların uzun top oranı benzerdi: {H} {h}, {A} {a}",
        "Ambos equipos jugaron en largo en proporción parecida: {h} para {H}, {a} para {A}")),
    "progression": ("more_progressive", "progressive", (
        "{X} moved the ball forward more: {x} progressive passes to {y} for {Y}",
        "{X} topu ileri daha çok taşıdı: {x} ileri pas, {Y} ise {y}",
        "{X} hizo progresar más el balón: {x} pases progresivos, por {y} de {Y}"), (
        "Progressive passes were even: {H} {h}, {A} {a}",
        "İleri pas sayıları dengeliydi: {H} {h}, {A} {a}",
        "La progresión estuvo igualada: {h} pases progresivos para {H} y {a} para {A}")),
}


def _compare(req: dict, lang: str, n: dict[str, str]) -> str:
    """A both-teams comparison: the side the label names first, or both level."""
    label, key, side_text, level_text = COMPARE[req["topic"]]
    sides = _sides(req, label)
    if sides:
        x, y = sides
        return pick(lang, *side_text).format(X=n[x], Y=n[y], x=_p(f"{x}_{key}"), y=_p(f"{y}_{key}"))
    return pick(lang, *level_text).format(H=n["home"], A=n["away"], h=_p(f"home_{key}"), a=_p(f"away_{key}"))


# The headline's phrase per topic, after "<home> <score> <away>: ". {X} as in COMPARE.
HEADLINE = {
    "defensive_line": (("{X} defended higher", "{X} daha önde savundu", "{X} defendió más arriba"),
                       ("evenly matched back lines", "savunma hatları dengeli", "defensas a la par")),
    "compactness": (("{X} the more compact side", "{X} daha kompakttı", "{X}, el bloque más compacto"),
                    ("equally compact blocks", "bloklar eşit derecede kompakt", "bloques igual de compactos")),
    "width": (("{X} the wider side", "{X} sahayı daha geniş kullandı", "{X} abrió más el campo"),
              ("a similar width", "genişlik dengeli", "amplitud pareja")),
    "pressing": (("{X} pressed higher", "{X} daha önde pres yaptı", "{X} presionó más arriba"),
                 ("even pressing", "pres dengeli", "presión igualada")),
    "directness": (("{X} the more direct side", "{X} daha direkt oynadı", "{X} jugó más directo"),
                   ("a similar directness", "direkt oyun dengeli", "juego directo parejo")),
    "progression": (("{X} moved the ball forward more", "{X} topu ileri daha çok taşıdı", "{X} hizo progresar más el balón"),
                    ("even progression", "topu ileri taşıma dengeli", "progresión igualada")),
}


def headline(req: dict, lang: str, names: dict[str, str]) -> str:
    """The headline: the score line, then what the top insight (req["top"]) says, in a phrase."""
    home, away = names["home"], names["away"]
    top = req["top"]
    topic, labels = top["topic"], top["labels"]
    if topic == "shape":
        phrase = pick(lang, "{home_shape} against {away_shape}", "{home_shape} ile {away_shape} karşı karşıya",
                      "{home_shape} contra {away_shape}")
    elif topic == "flanks":
        way = pick(lang, *FLANK[labels["flank"]])
        phrase = pick(lang, f"{names[top['team']]} attacked {way}", f"{names[top['team']]} hücuma {way} çıktı",
                      f"{names[top['team']]} atacó {way}")
    elif topic == "change":
        t, moved = names[top["team"]], labels["moved"]
        ev = pick(lang, *(("the goal", "golden", "el gol") if labels["event"] == "goal" else
                          ("the red card", "kırmızı karttan", "la roja")))
        if moved == "level":
            phrase = pick(lang, f"{t} held their line after {ev}", f"{t} {ev} sonra hattını korudu",
                          f"{t} mantuvo su línea tras {ev}")
        else:
            hi = moved == "higher"
            phrase = pick(lang, f"{t} defended {'higher' if hi else 'deeper'} after {ev}",
                          f"{t} {ev} sonra {'daha önde' if hi else 'daha geride'} savundu",
                          f"{t} defendió más {'arriba' if hi else 'atrás'} tras {ev}")
    else:
        sides = _sides(top, COMPARE[topic][0])
        side_text, level_text = HEADLINE[topic]
        phrase = pick(lang, *side_text).format(X=names[sides[0]]) if sides else pick(lang, *level_text)
    return f"{home} {{score}} {away}: {phrase}"
