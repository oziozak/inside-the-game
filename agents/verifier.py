"""Verifier: checks every piece of LLM text before it can reach the screen.

The model writes placeholders (`{distance_m}`, `{score}`...), never digits; fill.py writes the
numbers. The verifier runs in two stages on one language of an answer:

Stage 1, on the raw model text:
1. Every placeholder is one this overlay knows (a `values` key, `minute`, `score`), written exactly.
   No digit outside a placeholder; the problem names the placeholder to use instead.

Stage 2, on the text after fill.py (what the viewer would see):
2. Text must be non-empty, say more than a player name (not just the title again) and be short enough
   for a broadcast graphic, units included.
3. Every number must equal a number in the overlay's `values` or facts (minute, score).
   A safety net: with stage 1 passed, only the filler wrote numbers.
4. Every player name in the text must be a player involved in the cited event, written in full
   ("A. Kurt", never "Kurt"). When naming is off (the vision AI is not sure who played the ball),
   no player name at all, bare surnames included.
5. Turkish only: a case suffix on a player name follows the name's last written vowel and letter
   ("P. Rowntree'nin", never "P. Rowntree'nun"; "A. Kurt'tan", never "A. Kurt'dan").

Returns a list of problems; an empty list means the text passed.
"""

from __future__ import annotations

import re

from .fill import PLACEHOLDER_RE, fill, kind_of, known

MAX_TEXT_CHARS = 110
MAX_TITLE_CHARS = 40
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
# A unit or sign right after a placeholder ("{distance_m} m", "{momentum_home}%", "{difficulty}/10",
# "{distance_m} metrelik"), or a % sign right before one (Turkish "%{momentum_home}", "yüzde {...}").
# A lone "m" only in lower case, so "{score} M. Aydin" is a name, not metres.
UNIT_AFTER_RE = re.compile(r"\s*(?:%|/\s*10\b|m\b|(?i:km\s*/\s*(?:h|sa)\b|kmh\b|kph\b|km\b|mt\b"
                           r"|met(?:re|er|ro)\w*|percent\b|per cent\b|por ciento\b))")
UNIT_BEFORE_RE = re.compile(r"(%|\byüzde)\s*$", re.I)
# Numbers spelled out ("two from two", "ikide iki", "dos de dos") dodge the digit check. Not "one",
# "bir", "un(o)": they are also articles; nor "yedi" ("blok yedi": was blocked). Terms that only
# look like numbers are cut first ("por ciento" is caught as a unit).
NUMBER_WORD_RE = {
    "en": re.compile(r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                     r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|hundred|dozen)\b", re.I),
    "tr": re.compile(r"\b(?:(?:iki|üç|dört|beş|sekiz|dokuz|yirmi|otuz|kırk|elli)\w*|on|altı)\b", re.I),
    "es": re.compile(r"\b(?:dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|"
                     r"dieci\w+|veinte|veinti\w+|treinta|cuarenta|cincuenta|cien|ciento)\b", re.I),
}
NOT_A_NUMBER_RE = re.compile(r"one-two|üçte bir\w*|tres cuartos|por ciento", re.I)
# "{difficulty}" reads "7/10": it needs its noun right before it, at the start of a clause ("..., difficulty
# 7/10"), or es "de dificultad 7/10". Not "a difficult 7/10 26 m pass", nor "a difficulty 7/10 long pass".
DIFFICULTY_NOUN_RE = re.compile(r"(?:^|[,.;:(—–-]\s*|\bde\s+)(?:difficulty|zorluk(?: derecesi)?|dificultad(?: de)?)"
                                r":?\s*$", re.I)
# Turkish puts an apostrophe before a suffix only after a proper name, a number or a unit:
# "K. Aydin'den", "28 m'lik", never "son üçte bir'e".
TR_SUFFIX_RE = re.compile(r"([^\W\d_]+)['’][^\W\d_]")
UNIT_WORDS = {"m", "sa", "h"}
MINUTE_WORD_RE = re.compile(r"\.?\s*(?:min\w*|dk\b|dakika\w*)", re.I)  # only after {minute}: "{window_min} min" is fine
# What is left of a placeholder the model mistyped ("{ distance_m }", "{distance-m}", "{distance_m").
MALFORMED_RE = re.compile(r"\{[^{}]*\}?|\}")
# Roster names look like "K. Aydin". Any script's letters, so "Ç. Uydurma" and "K. Aydın" are seen too.
NAME_RE = re.compile(r"\b([^\W\d_])\. ([^\W\d_][\w'’-]*)")
APOSTROPHES = "'’"
# Turkish case suffixes on a name follow its last written vowel (front e/i/ö/ü or back a/ı/o/u; for
# 4-way suffixes also rounded o/ö/u/ü or not) and its last letter (a buffer n/y after a vowel).
# Each case: the shape of its first letters, any vowel or buffer, so a wrong one is still recognised, and its
# right form: {n}/{y} the buffer after a vowel, {i} the 4-way vowel, {e} the 2-way one, {d} d or t.
TR_VOWELS = "aeıioöuü"
TR_HARD = "fstkçşhp"  # -da/-dan become -ta/-tan after these
TR_CASES = {"genitive": (re.compile(r"n?[iıuü]n"), "{n}{i}n"), "accusative": (re.compile(r"y?[iıuü]"), "{y}{i}"),
            "dative": (re.compile(r"y?[ae]"), "{y}{e}"), "ablative": (re.compile(r"[dt][ae]n"), "{d}{e}n"),
            "locative": (re.compile(r"[dt][ae]"), "{d}{e}")}


def names_in(s: str, roster_names: set[str]) -> set[str]:
    """Player-like names in `s`. A Turkish case suffix after an apostrophe ("K. Aydin'den")
    is stripped unless the full form is itself a roster name."""
    out = set()
    for m in NAME_RE.finditer(s):
        initial, surname = m.groups()
        if not (initial.isupper() and surname[0].isupper()):
            continue
        name = f"{initial}. {surname}".rstrip(APOSTROPHES + "-")
        while name not in roster_names and any(a in name for a in APOSTROPHES):
            name = name[:max(name.rfind(a) for a in APOSTROPHES)]  # drop the last suffix
        out.add(name)
    return out


def bare_surnames(s: str, roster_names: set[str]) -> dict[str, set[str]]:
    """Roster surnames written without their initial ("finds Kurt", Turkish "Kurt'u") -> the roster
    names they could be. "A. Kurt" itself is not a bare surname."""
    out: dict[str, set[str]] = {}
    for full in roster_names:
        surname = full.split(". ", 1)[-1]
        if surname != full and re.search(rf"(?<![^\W\d_]\. )(?<!\w){re.escape(surname)}(?![^\W\d_])", s):
            out.setdefault(surname, set()).add(full)
    return out


def names_only(s: str, roster_names: set[str]) -> bool:
    """Whether `s` is player names and nothing else ("T. Castell"): no word or number besides them."""
    rest = s
    for name in names_in(s, roster_names):
        rest = rest.replace(name, " ")
    return rest != s and not re.search(r"[^\W_]", rest)


def as_numbers(v) -> list[float]:
    """The numbers a value writes: itself, or those in a string ("4-3-3": 4, 3, 3); none for a bool."""
    if isinstance(v, str):
        return [float(n.replace(",", ".")) for n in NUMBER_RE.findall(v)]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [v]
    return []


def allowed_numbers(values: dict, facts: dict) -> set[float]:
    nums = set()
    # `values` wins over the moment's facts, as in fill.py.
    for k, v in {**{k: facts[k] for k in ("minute", "score_home", "score_away") if k in facts}, **values}.items():
        for n in as_numbers(v):
            nums.add(round(float(n), 1))
            nums.add(float(round(n)))
    return nums


def stray_digit_problem(raw: str, numbers: dict, allowed: str) -> str:
    """Tell the model which placeholder writes this number, or that no placeholder does.
    `numbers` maps each placeholder to its number (fill.known)."""
    n = round(float(raw.replace(",", ".")), 1)
    keys = [k for k, v in numbers.items()
            if any(n in (round(float(x), 1), float(round(x)))
                   for part in (v if isinstance(v, tuple) else (v,)) for x in as_numbers(part))]
    if keys:
        use = " or ".join(f"{{{k}}}" for k in keys)
        return f"digit {raw} outside a placeholder: write {use} instead (code adds the number and unit)"
    return f"digit {raw} outside a placeholder: no number of this graphic is {raw}, remove it (placeholders: {allowed})"


def unit_problems(raw: str, values: dict, facts: dict, lang: str) -> list[str]:
    """A unit, % or /10 written next to a placeholder whose format already writes it ("{distance_m} m"
    -> "23 m m"), a minute word or apostrophe after {minute}, a suffix after a number read aloud
    (Turkish "{score}'lik": the vowel depends on the number, which the model cannot see), a letter
    glued to a placeholder, and {difficulty} without its noun."""
    numbers = known(values, facts)
    problems = []
    for m in PLACEHOLDER_RE.finditer(raw):
        key = m.group(1)
        if key not in numbers:
            continue  # reported as unknown
        shown = fill(m.group(0), values, lang, facts)
        after, before = raw[m.end():], raw[:m.start()]
        unit = UNIT_AFTER_RE.match(after) or (key == "minute" and MINUTE_WORD_RE.match(after))
        sign = UNIT_BEFORE_RE.search(before)
        if unit or sign:
            written = (unit.group(0).strip() if unit else sign.group(1))
            problems.append(f"'{written}' next to {{{key}}}: code writes the unit, {{{key}}} already reads "
                            f"'{shown}', remove '{written}'")
        elif after.startswith(tuple(APOSTROPHES)):
            if key == "minute":
                problems.append(f"apostrophe after {{minute}}: it already reads '{shown}', write nothing after it")
            elif kind_of(key) not in ("distance", "speed"):
                problems.append(f"suffix after {{{key}}}: its form depends on the number, which you cannot see; "
                                "rephrase without a suffix")
        elif after[:1].isalpha():  # Turkish "{distance_m}lik" -> "23 mlik"
            fix = f", or an apostrophe before a suffix ({{{key}}}'lik)" if kind_of(key) in ("distance", "speed") else ""
            problems.append(f"letter right after {{{key}}}: it reads '{shown}', put a space after it{fix}")
        if key == "difficulty" and not DIFFICULTY_NOUN_RE.search(before):
            problems.append(f"{{difficulty}} reads '{shown}': write it as its own clause after a comma, "
                            "'..., difficulty {difficulty}', tr '..., zorluk {difficulty}', es '..., dificultad {difficulty}'")
    return problems


def check_raw(text: str, title: str, values: dict, facts: dict, lang: str = "en") -> list[str]:
    """Stage 1: the model's text before filling."""
    numbers = known(values, facts)
    allowed = ", ".join(f"{{{k}}}" for k in sorted(numbers)) or "none"
    raw = f"{title} {text}"
    problems = [f"unknown placeholder {{{key}}} (allowed: {allowed})"
                for key in dict.fromkeys(PLACEHOLDER_RE.findall(raw)) if key not in numbers]
    problems += unit_problems(title, values, facts, lang) + unit_problems(text, values, facts, lang)
    bare = PLACEHOLDER_RE.sub(" ", raw)
    words = NUMBER_WORD_RE.get(lang, NUMBER_WORD_RE["en"]).findall(NOT_A_NUMBER_RE.sub(" ", bare))
    problems += [f"number word '{w}': write a number only as a placeholder ({allowed}), never in words"
                 for w in dict.fromkeys(words)]
    if lang == "tr":
        problems += [f"apostrophe after the common word '{w}': in Turkish only a name or number takes one, "
                     f"join the suffix to the word"
                     for w in dict.fromkeys(TR_SUFFIX_RE.findall(bare)) if w.islower() and w not in UNIT_WORDS]
    problems += [f"malformed placeholder '{m}': write one exactly as listed, braces included ({allowed})"
                 for m in MALFORMED_RE.findall(bare)]
    return problems + [stray_digit_problem(n, numbers, allowed) for n in NUMBER_RE.findall(bare)]


def check_filled(text: str, title: str, values: dict, facts: dict, involved_names: set[str],
                 roster_names: set[str], name_players: bool = True, lang: str = "en",
                 max_text: int = MAX_TEXT_CHARS, max_title: int = MAX_TITLE_CHARS) -> list[str]:
    """Stage 2: the text as the viewer would see it. A graphic's length limits unless given."""
    problems = []
    if not text.strip():
        problems.append("empty text")
    elif text.strip() == title.strip() or names_only(text, roster_names):
        problems.append(f"text '{text}' only repeats the title or a name: say what the player did")
    if len(text) > max_text:
        problems.append(f"text too long ({len(text)} > {max_text} chars)")
    if len(title) > max_title:
        problems.append(f"title too long ({len(title)} > {max_title} chars)")

    ok_nums = allowed_numbers(values, facts)
    for raw in NUMBER_RE.findall(f"{title} {text}"):
        n = round(float(raw.replace(",", ".")), 1)
        if n not in ok_nums:
            problems.append(f"number {raw} is not backed by the event data (allowed: {sorted(ok_nums)})")

    return problems + name_problems(f"{title} {text}", involved_names, roster_names, name_players, lang)


def name_problems(s: str, involved_names: set[str], roster_names: set[str], name_players: bool = True,
                  lang: str = "en") -> list[str]:
    """Player names in `s` that are not allowed: not involved, not on the roster, written without the
    initial, or any name at all when naming is off; in Turkish, a suffix out of harmony with the name.
    Placeholders do not change names, so this runs on raw or filled text alike."""
    problems = []
    for name in names_in(s, roster_names):
        if not name_players:
            problems.append(f"player '{name}' is named, but who played the ball is uncertain: name the team")
        elif name not in roster_names:
            problems.append(f"unknown player name '{name}'")
        elif name not in involved_names:
            problems.append(f"player '{name}' is not part of the cited event")
    for surname, fulls in bare_surnames(s, roster_names).items():
        if not name_players:
            problems.append(f"player '{surname}' is named, but who played the ball is uncertain: name the team")
        elif fulls & involved_names:
            problems.append(f"surname '{surname}' without its initial: write "
                            + " or ".join(f"'{n}'" for n in sorted(fulls & involved_names)))
        else:
            problems.append(f"player '{surname}' is not part of the cited event")
    return problems + (harmony_problems(s, roster_names) if lang == "tr" else [])


def tr_suffix(name: str, case: str) -> str | None:
    """The case suffix Turkish puts on `name` after the apostrophe ("P. Rowntree" genitive -> "nin");
    None for a name with no vowel to follow."""
    letters = name.lower()
    if letters.endswith("y") and letters[-2] not in "aıoöuü":  # a final "y" after a consonant or "e" reads "i":
        letters = letters[:-1] + "i"                           # "Ashby'nin", "Hartley'ye"; "Aksoy'un" keeps its y
    vowel = next((c for c in reversed(letters) if c in TR_VOWELS), None)
    if vowel is None:
        return None
    after_vowel, last = letters[-1] in TR_VOWELS, letters[-1]
    return TR_CASES[case][1].format(
        n="n" if after_vowel else "", y="y" if after_vowel else "",
        i="i" if vowel in "ei" else "ü" if vowel in "öü" else "ı" if vowel in "aı" else "u",
        e="e" if vowel in "eiöü" else "a", d="t" if last in TR_HARD else "d")


def harmony_problems(s: str, roster_names: set[str]) -> list[str]:
    """Turkish case suffixes on roster names that break vowel harmony, the buffer letter or t/d:
    "P. Rowntree'nun" -> write "P. Rowntree'nin"."""
    problems = []
    for name in roster_names:
        for m in re.finditer(rf"(?<!\w){re.escape(name)}([{APOSTROPHES}])([^\W\d_]+)", s):
            apostrophe, suffix = m.groups()
            case, written = next(((c, w.group(0)) for c, (shape, _) in TR_CASES.items()
                                  if (w := shape.match(suffix))), (None, None))
            right = case and tr_suffix(name, case)
            if right and written != right:
                problems.append(f"suffix after '{name}' breaks vowel harmony: write "
                                f"{name}{apostrophe}{right}{suffix[len(written):]}, not {name}{apostrophe}{suffix}")
    return problems


def check(text: str, title: str, values: dict, facts: dict, involved_names: set[str],
          roster_names: set[str], lang: str, name_players: bool = True,
          max_text: int = MAX_TEXT_CHARS, max_title: int = MAX_TITLE_CHARS) -> list[str]:
    """Both stages on one language of the model's raw (placeholder) text."""
    problems = check_raw(text, title, values, facts, lang)
    if problems:  # cannot fill yet; name problems are reported now so one retry can fix everything
        return problems + name_problems(f"{title} {text}", involved_names, roster_names, name_players, lang)
    text, title = fill(text, values, lang, facts), fill(title, values, lang, facts)
    return check_filled(text, title, values, facts, involved_names, roster_names, name_players, lang,
                        max_text, max_title)


# Analyst report (agents/analyst.py). An insight may say only what its cited facts say: a sentence about a
# topic it does not cite ("they pressed high" in a width insight) is an uncited claim. Each fact kind has the
# words that make a claim about it, per language; a name is cut first ("Thames United" is no claim).
TOPIC_TERMS = {
    "en": {
        "shape": r"\bformations?\b|\bshape\b|\bsystem\b|\blined up\b",
        "defensive_line": r"\b(?:defensive|back|high|higher|deep|deeper) lines?\b|\bline height\b",
        "compactness": r"\bcompact\w*|\btight\w* block\b|\bspace between (?:the )?lines\b|\bgaps? between\b",
        "width": r"\bwid(?:e|er|est|th)\b|\bnarrow\w*|\bstretch\w*",
        "flanks": r"\bflanks?\b|\bwings?\b|\bdown the (?:left|right)\b|\bthrough the middle\b|\b(?:left|right) side\b",
        "pressing": r"\bpress\w*|\bregain\w*|\b(?:won|win|wins|winning) (?:the ball|it) back\b",
        "directness": r"\blong balls?\b|\bdirect\w*|\b(?:went|go|going) long\b",
        "progression": r"\bprogress\w*|\bforward pass\w*|\bmoved the ball forward\b",
    },
    "tr": {
        "shape": r"diziliş\w*|formasyon\w*|\bsistem\w*",
        "defensive_line": r"savunma hatt\w*|\bhat yüksekli\w*|(?:önde|geride) savun\w*",
        "compactness": r"kompakt\w*|derli toplu|hatlar arası",
        "width": r"genişli\w*|\bgeniş\w*|\bdar\b",
        "flanks": r"kanat\w*|\bsol\b|\bsağ\b|merkez\w*|\bortadan\b",
        "pressing": r"\bpres\b|\bpres\w*|top kazan\w*|geri kazan\w*",
        "directness": r"uzun top\w*|direkt\w*",
        "progression": r"ileri pas\w*|topu ileri\w*|ilerlet\w*",
    },
    "es": {
        "shape": r"\bdibujo\b|\bsistema\b|\bformaci\w+|\bform[oó]\b",
        "defensive_line": r"l[ií]nea defensiva|l[ií]nea (?:m[aá]s )?(?:adelantada|alta|baja|retrasada)|altura de la l[ií]nea|\bzaga\b",
        "compactness": r"compact\w*|entre l[ií]neas",
        "width": r"\bamplitud\b|\bancho\b|estrech\w*|abri\w* (?:m[aá]s )?el campo",
        "flanks": r"\bbandas?\b|\bcostados?\b|\bizquierda\b|\bderecha\b|por el centro|\bcarril\w*",
        "pressing": r"presi[oó]n\w*|presion\w*|recuper\w*",
        "directness": r"bal[oó]n(?:es)? largos?|direct\w*|en largo",
        "progression": r"progres\w*|hacia (?:a)?delante",
    },
}
TOPIC_RE = {lang: {t: re.compile(rx, re.I) for t, rx in terms.items()} for lang, terms in TOPIC_TERMS.items()}
# A hedged insight (coverage below the threshold) must say so in its own words.
HEDGE_RE = {"en": re.compile(r"\b(?:seem\w*|appear\w*|suggest\w*|likely|limited|partial|tentative\w*)\b", re.I),
            "tr": re.compile(r"görün\w*|\bgibi\b|sınırlı|muhtemelen|olası", re.I),
            "es": re.compile(r"parec\w*|apunt\w*|limitad\w*|probablemente|sugier\w*|indic\w*", re.I)}


def uncited_claims(s: str, cited: set[str], lang: str, team_names: set[str]) -> list[str]:
    """Claims about a fact kind (TOPIC_TERMS) that the text does not cite."""
    for name in team_names:
        s = s.replace(name, " ")
    terms = TOPIC_RE.get(lang, TOPIC_RE["en"])
    allowed = ", ".join(sorted(cited)) or "none"
    return [f"'{m.group(0)}' is a claim about {topic}, which this text does not cite: keep to {allowed}"
            for topic, rx in terms.items() if topic not in cited and (m := rx.search(s))]


# Every number reads with its noun (#79): not a share and a count joined by a bare "and" ("with 91% and 10
# there"), nor a count followed only by "there". Same-kind pairs ("22 m and 14 m") read fine.
PAIR_RE = re.compile(r"\{(\w+)\}\s*(?:and|ve|y|e|,)\s+\{(\w+)\}", re.I)
COUNT_THERE_RE = re.compile(r"\{(\w+)\}\s+(?:there|here|allí|ahí|aquí|burada|orada)\w*\b", re.I)


def bare_numbers(raw: str, values: dict) -> list[str]:
    """Placeholders that do not read with their noun: a share and a count of different kinds joined by
    only a conjunction or comma, or a plain count followed by "there"."""
    def count(key):
        return kind_of(key) == "number" and isinstance(values.get(key), (int, float))

    problems = [f"{{{a}}} and {{{b}}} are joined with no noun: give each number its own noun "
                f"('{{{a}}} of their passes into the final third, {{{b}}} passes')"
                for a, b in PAIR_RE.findall(raw) if a in values and b in values and kind_of(a) != kind_of(b)]
    return problems + [f"{{{k}}} is a count with no noun ('{{{k}}} there'): say what it counts ('{{{k}}} passes')"
                       for k in COUNT_THERE_RE.findall(raw) if count(k)]


# The same headline or insight must mean the same in every language (#79): the same teams, the same numbers.
# A "both teams" phrase names both; a headline's score line ("<home> {score} <away>:") names nobody.
BOTH_RE = {"en": re.compile(r"\b(?:both|neither)\b|\beach (?:side|team)\b", re.I),
           "tr": re.compile(r"\btakımlar\w*|\bher (?:iki )?takım\w*|\bikisi\w*|\bhiçbir takım\w*", re.I),
           "es": re.compile(r"\bamb[oa]s\b|\b(?:cada|ningún) equipo\b|\bninguno\b|\blos dos\b", re.I)}
SCORE_LINE_RE = re.compile(r"^[^:]*\{score\}[^:]*:")


def teams_named(s: str, lang: str, names: dict[str, str]) -> frozenset[str]:
    """The sides `s` speaks of: those named (in full or by the name's first word), or both for a "both teams"
    phrase. Empty when it names no team."""
    s = SCORE_LINE_RE.sub(" ", s)
    if BOTH_RE.get(lang, BOTH_RE["en"]).search(s):
        return frozenset(names)
    return frozenset(side for side, name in names.items()
                     if re.search(rf"(?<!\w)(?:{re.escape(name)}|{re.escape(name.split()[0])})(?!\w)", s))


def language_mismatch(texts: dict[str, str], names: dict[str, str]) -> list[str]:
    """One part (a headline, or an insight's title and text) in every language, raw: problems when the
    languages name different teams or use different placeholders. A language that names no team agrees
    with any."""
    teams = {lang: teams_named(t, lang, names) for lang, t in texts.items()}
    keys = {lang: frozenset(PLACEHOLDER_RE.findall(t)) for lang, t in texts.items()}

    def say(sides):
        return "both teams" if len(sides) == 2 else names[next(iter(sides))] + " only" if sides else "no team"

    problems = []
    if len({t for t in teams.values() if t}) > 1:
        problems.append("the languages speak of different teams (" + ", ".join(f"{l}: {say(t)}" for l, t in teams.items())
                        + "): say the same thing of the same teams in every language")
    if len(set(keys.values())) > 1:
        problems.append("the languages use different placeholders (" + ", ".join(
            f"{l}: " + (" ".join(f"{{{k}}}" for k in sorted(k_)) or "none") for l, k_ in keys.items())
            + "): use the same numbers in every language")
    return problems


def missing_hedge(text: str, lang: str) -> list[str]:
    """A hedged insight's text that does not hedge."""
    if HEDGE_RE.get(lang, HEDGE_RE["en"]).search(text):
        return []
    return ["this insight rests on little of the clip (coverage below the threshold): say so, e.g. "
            "'seems', 'on limited evidence' (tr 'görünüyor', 'sınırlı veriye göre'; es 'parece', 'con datos limitados')"]
