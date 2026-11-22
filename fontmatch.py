#!/usr/bin/env python3
"""Find the font in a picture: "Match from image" in the font picker.

1. An AI vision model (Groq's free plan) reads the text in the picture and
   guesses which Google Fonts it might be. Optional: without a key the user
   types the text instead.
2. The text is drawn in every font of the library, plus the AI's guesses
   fetched from Google Fonts, and each drawing is compared with the picture
   shape by shape. The AI only suggests names; what decides is how alike the
   letters look, so a wrong guess simply ranks low.
"""
import base64, io, json, os, re, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config
import fontindex
import typefaces

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
VISION_MODEL = os.environ.get("SUBGEN_VISION_MODEL", "qwen/qwen3.8-27b")
CACHE = os.path.join(config.DATA_DIR, "fontcache")     # Google Fonts being tried, not yet added
os.makedirs(CACHE, exist_ok=True)
DEVANAGARI = re.compile("[ऀ-ॿ]")
H = 48                  # every text line is compared at this height
MAX_SIDE = 1600         # pictures are shrunk to this before anything else

def read_image(data_url):
    """data: URL or base64 from the browser -> RGB picture."""
    raw = base64.b64decode(data_url.split(",", 1)[-1])
    img = Image.open(io.BytesIO(raw))
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return img.convert("RGB")


# ---------------------------------------------------------------- 1. read it
def identify(img):
    """{"text": ..., "fonts": [{"name", "weight"}]} from the vision model, or None."""
    if not GROQ_KEY:
        return None
    small = img.copy()
    small.thumbnail((768, 768))             # plenty to read a caption; fewer tokens
    buf = io.BytesIO()
    small.save(buf, "PNG")
    prompt = ("This picture shows some text, often a video caption. Reply with the text exactly as it is "
              "written (same capitals and line breaks, one line per row of text), and up to 8 Google Fonts "
              "families that the lettering could be, most likely first, including less common families "
              "when the letters match them, each with its weight "
              "(100-900, 400 = regular, 700 = bold, 900 = black). Only real Google Fonts names. "
              "Also give \"exact\": your best guess of the actual font used, from any foundry, even a paid "
              "one (empty if you can't tell). "
              'Reply with JSON only, like {"text": "...", "exact": "Gilroy ExtraBold", '
              '"fonts": [{"name": "Anton", "weight": 400}]}')
    body = {
        "model": VISION_MODEL, "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                                                       + base64.b64encode(buf.getvalue()).decode()}}]}],
        "max_tokens": 600,
    }
    # Groq's strict JSON mode often fails with this model, so the reply is read leniently.
    for attempt in range(3):
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=60, json=body,
                              headers={"Authorization": f"Bearer {GROQ_KEY}"})
            if r.status_code == 429:                          # free plan's per-minute limit
                time.sleep(min(float(r.headers.get("retry-after", 5)), 15))
                continue
            r.raise_for_status()
            reply = re.sub(r"<think>.*?</think>", "", r.json()["choices"][0]["message"]["content"] or "", flags=re.S)
            got = json.loads(reply[reply.index("{"):reply.rindex("}") + 1])
            fonts = [{"name": str(f.get("name", "")), "weight": int(f.get("weight") or 400)}
                     for f in got.get("fonts") or [] if isinstance(f, dict)]
            return {"text": str(got.get("text") or ""), "exact": str(got.get("exact") or "").strip(), "fonts": fonts}
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            print(f"Font match: couldn't read the picture with AI ({e})")
            continue
    return None


# ---------------------------------------------------------------- 2. compare shapes
def _otsu(a):
    hist = np.bincount(a.ravel(), minlength=256).astype(float)
    total, levels = hist.sum(), np.arange(256)
    w0 = np.cumsum(hist)
    m0 = np.cumsum(hist * levels)
    w1 = total - w0
    between = (m0[-1] * w0 / total - m0) ** 2 / np.maximum(w0 * w1, 1)
    return int(np.argmax(between))


def _crop(mask):
    rows, cols = np.where(mask.any(1))[0], np.where(mask.any(0))[0]
    if not len(rows) or not len(cols):
        return None
    return mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def _edge(mask):
    return np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]]).mean()


def _kmeans(px, k, rounds=12):
    rng = np.random.default_rng(0)
    centres = px[rng.choice(len(px), k, replace=False)]
    for _ in range(rounds):
        label = ((px[:, None, :] - centres[None]) ** 2).sum(2).argmin(1)
        centres = np.array([px[label == i].mean(0) if (label == i).any() else centres[i] for i in range(k)])
    return centres


def inks(img):
    """Possible readings of which pixels are the letters, as cropped True/False masks.
    Captions are coloured text with outlines, shadows and boxes over video, so one rule
    can't always find the letters: this tries light/dark and colour groups, and the
    comparison keeps whichever reading matches a font best."""
    rgb = np.asarray(img, float)
    grey = np.asarray(img.convert("L"))
    out = []
    mask = grey > _otsu(grey)
    out.append(~mask if _edge(mask) > 0.5 else mask)     # the background is what touches the edges
    px = rgb.reshape(-1, 3)[:: max(1, rgb.shape[0] * rgb.shape[1] // 6000)]
    for k in (3, 4):
        centres = _kmeans(px, k)
        label = ((rgb[:, :, None, :] - centres[None, None]) ** 2).sum(3).argmin(2)
        groups = [label == i for i in range(k)]
        inner = [g for g in groups if _edge(g) < 0.25 and 0.03 < g.mean() < 0.7]
        out += inner
        if len(inner) >= 2:                              # fill + outline together
            out.append(np.logical_or.reduce(inner))
    masks, seen = [], set()
    for m in out:
        m = _crop(m)
        if m is not None and m.shape[0] > 6 and m.shape[1] > 6:
            sig = (m.shape, int(m.sum()))
            if sig not in seen:
                seen.add(sig)
                masks.append(m)
    return masks[:6]


def ink(img):
    """The most likely reading of the letters (see inks)."""
    masks = inks(img)
    return masks[0] if masks else None


def _rows(mask):
    """Split a mask into its lines of text (a gap of empty rows between them)."""
    filled = mask.mean(1) > 0.002
    lines, start = [], None
    for y, f in enumerate(list(filled) + [False]):
        if f and start is None:
            start = y
        elif not f and start is not None:
            if y - start > mask.shape[0] * 0.08:
                lines.append(_crop(mask[start:y]))
            start = None
    return [l for l in lines if l is not None]


def _draw(path, text, stroke):
    font = ImageFont.truetype(path, 120)
    box = font.getbbox(text, stroke_width=stroke)
    img = Image.new("L", (box[2] - box[0] + 20, box[3] - box[1] + 20), 0)
    ImageDraw.Draw(img).text((10 - box[0], 10 - box[1]), text, font=font, fill=255,
                             stroke_width=stroke, stroke_fill=255)
    return _crop(np.asarray(img) > 127)


def _fit(mask, width):
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((max(width, 1), H), Image.BILINEAR)
                      .filter(ImageFilter.GaussianBlur(1.2)), float) / 255


def prepare(readings):
    """Each reading's lines fitted to the comparison height once: [[(width_px, fitted, cols)]]."""
    out = []
    for lines in readings:
        widths = [max(1, round(m.shape[1] * H / m.shape[0])) for m in lines]
        out.append([(w, _fit(m, w), m.shape[1]) for w, m in zip(widths, lines)])
    return out


def _alike(prep, cand):
    """0..1: how alike a picture line (prepared) and a drawn line look: shape overlap, then proportions."""
    wr, a, _ = prep
    wc = max(1, round(cand.shape[1] * H / cand.shape[0]))
    b = _fit(cand, wr)
    overlap = np.minimum(a, b).sum() / max(np.maximum(a, b).sum(), 1e-6)
    return overlap * (min(wr, wc) / max(wr, wc)) ** 1.5


def _compare(cands, prepared):
    """Likeness of drawn lines to each reading of the picture."""
    out = []
    for lines in prepared:
        if len(cands) == len(lines):
            pairs = list(zip(lines, cands))
        else:                                    # lines didn't split cleanly: compare the widest
            pairs = [(max(lines, key=lambda p: p[2]), max(cands, key=lambda m: m.shape[1]))]
        weight = sum(p[2] for p, _ in pairs)
        out.append(sum(_alike(p, c) * p[2] for p, c in pairs) / weight)
    return out


def score(path, prepared, text_lines, per_reading=False):
    """Best likeness of one font file to the picture: over every reading of the letters
    (see inks) and a few outline widths, since captions often have a thick outline
    that makes letters look heavier. per_reading=True gives the best for each reading."""
    best = [0.0] * len(prepared)
    for stroke in (0, 4, 9):
        try:
            cands = [_draw(path, t, stroke) for t in text_lines]
        except OSError:
            break
        if any(c is None for c in cands):
            break
        best = [max(a, b) for a, b in zip(best, _compare(cands, prepared))]
    return best if per_reading else max(best)


def _thicken(mask):
    out = mask.copy()
    out[1:] |= mask[:-1]; out[:-1] |= mask[1:]; out[:, 1:] |= mask[:, :-1]; out[:, :-1] |= mask[:, 1:]
    return out


def search_index(prepared, text_lines, skip, limit=12):
    """Quick pass over every Google Fonts style (fontindex): the `limit` most alike families,
    each with its two best weights, as (score, family, weight). None while the index is
    still being built."""
    index = fontindex.load()
    if index is None:
        return None
    catalog = google_catalog()
    scored = []
    for e in index["styles"]:
        if ((e["family"].lower(), e["weight"]) in skip or catalog.get(e["family"].lower(), {}).get("copy")
                or _NOT_TEXT.search(e["family"])):
            continue
        cands = [fontindex.spell(e, t) for t in text_lines]
        if any(c is None for c in cands):
            continue
        best = max(_compare(cands, prepared))
        thick = [_thicken(c) for c in cands]                 # outlined captions
        best = max(best, max(_compare(thick, prepared)))
        scored.append((best, e["family"], e["weight"]))
    scored.sort(reverse=True)
    out, weights = [], {}
    for sc, fam, wt in scored:
        if fam not in weights and len(weights) == limit:
            continue
        got = weights.setdefault(fam, [])
        if len(got) < 2:          # the drawing is rough, so the top weight isn't always the right one
            got.append(wt)
            out.append((sc, fam, wt))
    return out


# ---------------------------------------------------------------- Google Fonts
_catalog, _catalog_lock = None, threading.Lock()


def google_catalog():
    """{lowercase family: {"family", "weights", "hindi"}} for every Google Fonts family (cached a week)."""
    global _catalog
    with _catalog_lock:
        if _catalog is not None:
            return _catalog
        path = os.path.join(CACHE, "catalog.json")
        if os.path.isfile(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
            _catalog = json.load(open(path, encoding="utf-8"))
            return _catalog
        try:
            raw = requests.get("https://fonts.google.com/metadata/fonts", timeout=30).text
            fams = json.loads(raw[raw.index("{"):])["familyMetadataList"]
            _catalog = {f["family"].lower(): {
                "family": f["family"],
                "weights": sorted({int(v[:3]) for v in f.get("fonts", {}) if v[:3].isdigit() and "i" not in v}),
                "hindi": "devanagari" in f.get("subsets", []),
                # Noto fonts for other scripts carry a copy of Noto Sans/Serif's English letters.
                "copy": bool(f.get("isNoto") and f.get("primaryScript"))} for f in fams}
            json.dump(_catalog, open(path, "w", encoding="utf-8"))
        except (requests.RequestException, ValueError, KeyError):
            _catalog = {}
        return _catalog


def google_file(family, weight):
    """Download one Google Fonts style as a TTF into the cache; returns (path, weight) or None."""
    info = google_catalog().get(family.lower())
    if not info or not info["weights"]:
        return None
    weight = min(info["weights"], key=lambda w: abs(w - weight))
    path = os.path.join(CACHE, f"{re.sub(r'[^A-Za-z0-9]', '', info['family'])}-{weight}.ttf")
    if not os.path.isfile(path):
        try:
            # An old browser name makes Google serve plain TTF files (what libass and Pillow read).
            css = requests.get("https://fonts.googleapis.com/css?family="
                               + urllib.parse.quote(f"{info['family']}:{weight}")
                               + "&subset=latin,latin-ext,devanagari",
                               headers={"User-Agent": "Mozilla/4.0"}, timeout=20).text
            url = re.search(r"url\((https://[^)]+\.ttf)\)", css).group(1)
            data = requests.get(url, timeout=30).content
        except (requests.RequestException, AttributeError):
            return None
        with open(path, "wb") as f:
            f.write(data)
    return path, weight


_WEIGHT_WORDS = {"thin": 100, "extralight": 200, "light": 300, "regular": 400, "medium": 500,
                 "semibold": 600, "bold": 700, "extrabold": 800, "black": 900}
_STYLE_WORDS = r" (Thin|ExtraLight|Light|Regular|Medium|SemiBold|Bold|ExtraBold|Black)( Italic)?$"
# Not lettering: barcodes and the placeholder blocks used in wireframes.
_NOT_TEXT = re.compile(r"barcode|redacted|^flow (block|circular|rounded)|^blokk|linefont|wavefont", re.I)


def _weight_of(file):
    """Weight from a library file name: Anton-400.ttf, Poppins-ExtraBold.ttf."""
    m = re.search(r"-(\d{3})(?:italic)?\.ttf$", file) or re.search(r"-([A-Za-z]+)\.ttf$", file)
    if not m:
        return 400
    return int(m.group(1)) if m.group(1).isdigit() else _WEIGHT_WORDS.get(m.group(1).lower(), 400)


# ---------------------------------------------------------------- all together
def match(img, text="", uid=None):
    """Find the font in the picture among the user's fonts and all of Google Fonts.
    Returns {"text", "ai", "exact", "indexing", "results": [...]}: library results have a
    "key"; Google Fonts ones a "family" and "weight" (and can be added with one click)."""
    guess = identify(img) or {}
    text = (text or "").strip() or guess.get("text", "").strip()
    if not text:
        raise ValueError("Type the text that's in the picture so the fonts can be compared")
    masks = inks(img)
    if not masks:
        raise ValueError("Couldn't find any text in that picture")
    text_lines = [l.strip() for l in text.splitlines() if l.strip()]
    prepared = prepare([_rows(m) or [m] for m in masks])
    hindi = bool(DEVANAGARI.search(text))
    library = typefaces.catalog(uid)["fonts"]

    results, by_reading = [], [0.0] * len(prepared)
    for f in library:
        if hindi and not f["hindi"]:
            continue
        each = score(os.path.join(typefaces.FONTS_DIR, f["file"]), prepared, text_lines, per_reading=True)
        by_reading = [max(a, b) for a, b in zip(by_reading, each)]
        results.append({"key": f["key"], "label": f["label"], "score": max(each), "source": "library"})
    # The readings of the picture that some font matches well are the ones worth a wide search.
    likely = [prepared[i] for i in sorted(range(len(prepared)), key=lambda i: -by_reading[i])[:3]]

    # Google Fonts styles the library already has (same family and weight) aren't offered again.
    skip = {(re.sub(_STYLE_WORDS, "", f["label"]).lower(), _weight_of(f["file"])) for f in library}
    picks = []

    def want(family, weight):
        info = google_catalog().get(family.strip().lower())
        if not info or (hindi and not info["hindi"]) or not info["weights"]:
            return
        weight = min(info["weights"], key=lambda w: abs(w - weight))
        if (info["family"].lower(), weight) not in skip and (info["family"], weight) not in picks:
            picks.append((info["family"], weight))

    for g in guess.get("fonts", [])[:8]:                      # the AI's guesses
        want(g["name"], g.get("weight") or 400)
    found = None if hindi else search_index(likely, text_lines, skip)
    for _, family, weight in found or []:                    # look-alikes from all of Google Fonts
        want(family, weight)

    def try_google(pick):
        got = google_file(*pick)
        if not got:
            return None
        path, weight = got
        return {"family": pick[0], "weight": weight,
                "label": pick[0] + ("" if weight == 400 else f" {typefaces.WEIGHT_NAMES.get(weight, weight)}"),
                "file": os.path.basename(path), "score": score(path, prepared, text_lines), "source": "google"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results += [r for r in pool.map(try_google, picks) if r]

    # Likeness of the right font runs 0.5-0.95 depending on outlines, shadows and the video
    # behind the text, so only the ranking means something: keep the ones near the best.
    results.sort(key=lambda r: -r["score"])
    # One weight of each Google Fonts family, and only when it beats the weight the library has.
    have = {}
    for r in results:
        if r["source"] == "library":
            have.setdefault(re.sub(_STYLE_WORDS, "", r["label"]).lower(), r["score"])
    seen = set()
    results = [r for r in results if r["source"] == "library" or (
        r["family"] not in seen and not seen.add(r["family"])
        and r["score"] > have.get(r["family"].lower(), -1) + 0.02)]
    best = results[0]["score"] if results else 0
    results = [r for r in results if r["score"] >= best - 0.15][:8]
    for r in results:
        r["score"] = round(r["score"], 3)

    # The AI's name for the exact font, when it isn't free to download (or it's the top result anyway).
    exact = guess.get("exact", "")
    exact_family = re.sub(r" (Thin|ExtraLight|Light|Regular|Medium|SemiBold|Bold|ExtraBold|Black|Heavy)$", "",
                          exact, flags=re.I).strip()
    free = bool(exact_family) and (exact_family.lower() in google_catalog()
                                   or any(f["label"].lower().startswith(exact_family.lower()) for f in library))
    near_perfect = bool(results) and results[0]["score"] >= 0.92    # then the free one is the font
    return {"text": text, "ai": bool(guess), "results": results,
            "exact": exact if exact and not free and not near_perfect else "",
            "indexing": None if hindi or found is not None else fontindex.state}
