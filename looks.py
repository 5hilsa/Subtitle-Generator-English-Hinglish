#!/usr/bin/env python3
"""Caption templates: the premium Reels looks users pick from.

One definition drives both the live preview in the browser (templates/index.html
reads TEMPLATES as JSON) and the burned-in export (render.py), so what you see
is what you export. The page/line/emphasis rules below are mirrored in the
browser; keep the two in step.

Template fields
  font, font2      typefaces keys for the text (font2 = second line, if different)
  size             text size relative to the standard caption size
  upper            ALL CAPS (Hindi script is left as is)
  words            most words on screen at once (0 = the whole subtitle)
  lines            most lines; chars = rough characters per line before wrapping
  split            "half": always break into two lines (line 2 styled as line2)
  align            "center" or "left"
  color            text colour; upcoming = colour of words not spoken yet,
                   "hide" = words appear as they are spoken
  active           colour of the word being spoken
  active_scale     how much the spoken word grows
  active_box       rounded box behind the spoken word
  spoken_box       highlighter behind every word spoken so far (per line)
  page_box         rounded box behind the whole caption
  box_text         text colour inside page_box/active_box/spoken_box when it differs
  outline          outline width (fraction of the text size), outline_color
  shadow           "hard", "soft" or None
  glow             colour of a soft glow around the text
  line2            overrides for the second line: color, font, upper, size, glow
  emphasis         {"key": colour, "num": colour}: one key word and every number per page
  pop              captions pop in; fade = fade in
  spacing          letter spacing (fraction of the text size)
  accent           which field the user's accent colour replaces, or None
"""
import math, re

WHITE, BLACK = "#FFFFFF", "#000000"

TEMPLATES = {
    "hustle": {
        "name": "Hustle", "desc": "Huge punchy caps, three words at a time",
        "font": "anton", "size": 1.25, "upper": True, "words": 3, "lines": 1, "chars": 16,
        "color": "#A6F24D", "outline": 0.075, "outline_color": BLACK, "shadow": "hard",
        "pop": True, "accent": "color",
    },
    "notebook": {
        "name": "Notebook", "desc": "Clean card that fills in as you speak",
        "font": "poppins", "size": 0.62, "words": 6, "lines": 1, "chars": 34,
        "color": "#151515", "upcoming": "#9A9A9A", "page_box": "#FFFFFFF0",
        "accent": "page_box",
    },
    "bubble": {
        "name": "Bubble", "desc": "Elegant serif, the spoken word in a bubble",
        "font": "lora_medium", "size": 0.9, "words": 6, "lines": 2, "chars": 18,
        "color": WHITE, "shadow": "soft", "active_box": "#000000E6", "box_text": WHITE,
        "accent": "active_box",
    },
    "punch": {
        "name": "Punch", "desc": "Bold italic, the second line in colour",
        "font": "montserrat_italic", "size": 0.95, "upper": True, "words": 4, "lines": 2, "chars": 14,
        "split": "half", "color": WHITE, "shadow": "soft", "outline": 0.02, "outline_color": BLACK,
        "line2": {"color": "#5B6CFF"}, "pop": True, "accent": "line2.color",
    },
    "tag": {
        "name": "Tag", "desc": "One word at a time on a colour tag",
        "font": "montserrat_black", "size": 0.62, "upper": True, "words": 1, "lines": 1, "chars": 20,
        "color": WHITE, "page_box": "#F7931E", "pop": True, "accent": "page_box",
    },
    "luxe": {
        "name": "Luxe", "desc": "Small, spaced, cinematic",
        "font": "montserrat", "size": 0.5, "upper": True, "words": 4, "lines": 1, "chars": 30,
        "color": WHITE, "shadow": "soft", "spacing": 0.06, "fade": True, "accent": None,
    },
    "beast": {
        "name": "Beast", "desc": "Chunky outline, the spoken word lights up",
        "font": "montserrat_black", "size": 0.78, "words": 4, "lines": 1, "chars": 22,
        "color": WHITE, "active": "#FFE81F", "active_scale": 1.1, "outline": 0.1, "outline_color": BLACK,
        "shadow": "hard", "pop": True, "accent": "active",
    },
    "mumbai": {
        "name": "Mumbai", "desc": "Glowing caps over a handwritten line",
        "font": "bebas", "size": 1.15, "upper": True, "words": 5, "lines": 2, "chars": 16,
        "split": "half", "color": "#FFE45C", "glow": "#FFD000", "upcoming": "hide",
        "line2": {"font": "kaushan", "upper": False, "size": 0.72, "color": WHITE, "glow": None},
        "shadow": "soft", "accent": "color",
    },
    "podcast": {
        "name": "Podcast", "desc": "Lights up as you speak, key words glow",
        "font": "montserrat", "size": 0.62, "upper": True, "words": 6, "lines": 2, "chars": 20,
        "color": WHITE, "upcoming": "#FFFFFF73", "shadow": "soft",
        "emphasis": {"key": "#43FF6E", "num": "#FFE81F"}, "accent": "emphasis.key",
    },
    "highlight": {
        "name": "Highlight", "desc": "A highlighter runs under the words",
        "font": "inter_semibold", "size": 0.62, "words": 7, "lines": 2, "chars": 24, "align": "left",
        "color": WHITE, "spoken_box": "#1E8DEB", "shadow": "soft", "accent": "spoken_box",
    },
    "classic": {
        "name": "Classic", "desc": "Plain and readable, whole sentences",
        "font": "poppins", "size": 1.0, "words": 0, "lines": 2, "chars": 26,
        "color": WHITE, "outline": 0.1, "outline_color": BLACK, "shadow": "hard", "accent": "color",
    },
}
DEFAULT = "hustle"

# Words that are never the "key word" of a caption.
STOP = set("""a an the and or but if so to of in on at by for with from as is are was were be been am i you he she it
we they me my your our their this that these those there here what when where who why how not no yes do does did
have has had will would can could should just very really like then than also about into over more most some
any all aur ki ka ke ko hai hain tha thi the se me mein main hum tum aap ye yeh wo woh kya bhi to na nahi ek koi
kuch jo par pe ho hoga raha rahe rahi""".split())
PUNCT_END = tuple(",.?!;:।")
DEVANAGARI = re.compile("[ऀ-ॿ]")


def pages(words, max_words):
    """Split a subtitle's words into the groups shown together on screen.
    `words` are dicts with text/start/end. Breaks early after punctuation and at pauses."""
    if not max_words:
        return [words] if words else []
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and w["start"] - cur[-1]["end"] > 0.6:
            out.append(cur); cur = []
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 2 and w["text"].endswith(PUNCT_END)):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def split_lines(texts, tpl):
    """Index lists, one per line, for the words of one page."""
    n = len(texts)
    if n < 2 or tpl.get("lines", 1) < 2:
        return [list(range(n))]
    if tpl.get("split") == "half":
        k = math.ceil(n / 2)
        return [list(range(k)), list(range(k, n))]
    total = sum(len(t) for t in texts) + n - 1
    if total <= tpl.get("chars", 24):
        return [list(range(n))]
    # Two lines, as even as possible.
    best, best_k = None, 1
    for k in range(1, n):
        a = sum(len(t) for t in texts[:k]) + k - 1
        b = sum(len(t) for t in texts[k:]) + n - k - 1
        if best is None or max(a, b) < best:
            best, best_k = max(a, b), k
    return [list(range(best_k)), list(range(best_k, n))]


def emphasis(texts, tpl):
    """{word index: colour} for the template's emphasised words on one page."""
    emph = tpl.get("emphasis")
    if not emph:
        return {}
    out, key, key_len = {}, None, 4
    for i, t in enumerate(texts):
        bare = re.sub(r"[^\w%]", "", t.lower())
        if any(ch.isdigit() for ch in bare):
            out[i] = emph["num"]
        elif bare not in STOP and len(bare) > key_len:
            key, key_len = i, len(bare)
    if key is not None:
        out[key] = emph["key"]
    return out


def with_accent(tpl, accent):
    """Copy of the template with the user's accent colour applied."""
    tpl = {**tpl, "line2": dict(tpl.get("line2") or {}), "emphasis": dict(tpl.get("emphasis") or {})}
    field = tpl.get("accent")
    if field and accent and re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
        if "." in field:
            a, b = field.split(".")
            tpl[a][b] = accent
        else:
            old = tpl.get(field) or ""
            tpl[field] = accent + (old[7:9] if len(old) == 9 else "")   # keep the box's transparency
    return tpl


def catalog():
    # "order" because JSON from Flask sorts object keys.
    return {"templates": TEMPLATES, "order": list(TEMPLATES), "default": DEFAULT, "stop": sorted(STOP)}
