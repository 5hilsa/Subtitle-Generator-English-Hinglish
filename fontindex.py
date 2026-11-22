#!/usr/bin/env python3
"""A fingerprint of every Google Fonts style, so "Match from image" can compare a
picture with the whole Google Fonts library (about 6,000 styles), not only the
fonts already in the app.

For each style it keeps the shape of every letter and digit (drawn small) and how
far each one advances, enough to spell any short English text in that font and
compare it with the picture. Built once in the background (about 70 MB of
downloads, a few minutes); kept in DATA_DIR/fontindex.pkl.gz.

    python fontindex.py      builds it now, showing progress
"""
import gzip, json, os, pickle, re, sys, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import config

PATH = os.path.join(config.DATA_DIR, "fontindex.pkl.gz")
CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,!?'&%-:"
EM = 32                     # letters are kept at this size
_UA = {"User-Agent": "Mozilla/4.0"}    # makes Google serve plain TTF files

state = {"status": "idle", "done": 0, "total": 0}     # for the progress shown in the app
_index, _lock = None, threading.Lock()


def _styles():
    raw = requests.get("https://fonts.google.com/metadata/fonts", timeout=30).text
    out = []
    for f in json.loads(raw[raw.index("{"):])["familyMetadataList"]:
        if "latin" not in f.get("subsets", []):
            continue                                   # e.g. Noto Sans Arabic: no English letters
        for v in f.get("fonts", {}):
            if v[:3].isdigit() and "i" not in v:       # every upright weight
                out.append((f["family"], int(v[:3]), f.get("category", "")))
    return out


def _glyphs(path):
    """{char: (advance, x, y, packed bits, w, h)} at EM pixels; x, y from the pen on the baseline."""
    font = ImageFont.truetype(path, EM)
    out = {}
    for ch in CHARS:
        x0, y0, x1, y1 = font.getbbox(ch, anchor="ls")
        adv = font.getlength(ch)
        if x1 <= x0 or y1 <= y0:
            continue
        img = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(img).text((-x0, -y0), ch, font=font, fill=255, anchor="ls")
        bits = np.asarray(img) > 110
        out[ch] = (round(adv, 2), x0, y0, np.packbits(bits).tobytes(), bits.shape[1], bits.shape[0])
    space = font.getlength(" ")
    return out, round(space, 2)


def _one(style, tmp):
    family, weight, category = style
    for attempt in range(3):
        try:
            css = requests.get("https://fonts.googleapis.com/css?family="
                               + urllib.parse.quote(f"{family}:{weight}")
                               + "&text=" + urllib.parse.quote(CHARS + " "), headers=_UA, timeout=20).text
            url = re.search(r"url\((https://[^)]+)\)", css).group(1)
            data = requests.get(url, timeout=20).content
            path = os.path.join(tmp, f"{threading.get_ident()}.ttf")
            with open(path, "wb") as f:
                f.write(data)
            glyphs, space = _glyphs(path)
            if len(glyphs) < 40:                       # an icon or symbol font
                return None
            return {"family": family, "weight": weight, "category": category, "space": space, "glyphs": glyphs}
        except (requests.RequestException, AttributeError, OSError):
            time.sleep(1 + attempt)
    return None


def build():
    """Download every Google Fonts style's letters and save the index (resumable is not
    needed: a failed build just runs again next start)."""
    if state["status"] == "building":
        return
    state.update(status="building", done=0, total=0)
    tmp = os.path.join(config.DATA_DIR, "fontindex-tmp")
    os.makedirs(tmp, exist_ok=True)
    try:
        styles = _styles()
        state["total"] = len(styles)
        entries = []

        def run(s):
            e = _one(s, tmp)
            state["done"] += 1
            return e
        with ThreadPoolExecutor(max_workers=16) as pool:
            entries = [e for e in pool.map(run, styles) if e]
        with gzip.open(PATH + ".part", "wb") as f:
            pickle.dump({"built": time.time(), "em": EM, "styles": entries}, f, protocol=4)
        os.replace(PATH + ".part", PATH)
        state["status"] = "ready"
    except (requests.RequestException, ValueError, KeyError, OSError) as e:
        print(f"Font index: couldn't build it ({e}); will try again next start")
        state["status"] = "failed"
    finally:
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


def load():
    """The index, or None while it isn't built yet (and starts building it once)."""
    global _index
    with _lock:
        if _index is not None:
            return _index
        if os.path.isfile(PATH):
            with gzip.open(PATH, "rb") as f:
                _index = pickle.load(f)              # letter shapes stay packed (about 40 MB in memory)
            state["status"] = "ready"
            return _index
    if state["status"] in ("idle", "failed"):
        threading.Thread(target=build, daemon=True).start()
    return None


def spell(entry, text):
    """Draw text from a style's letters (no kerning: close enough to compare shapes).
    Returns a cropped True/False mask, or None if the style lacks a letter."""
    g, pen, parts = entry["glyphs"], 0.0, []
    for ch in text:
        if ch == " ":
            pen += entry["space"]
            continue
        if ch not in g:
            return None
        adv, x, y, packed, w, h = g[ch]
        bits = np.unpackbits(np.frombuffer(packed, np.uint8), count=w * h).reshape(h, w).astype(bool)
        parts.append((int(round(pen + x)), y, bits))
        pen += adv
    if not parts:
        return None
    left = min(p[0] for p in parts)
    top = min(p[1] for p in parts)
    right = max(p[0] + p[2].shape[1] for p in parts)
    bottom = max(p[1] + p[2].shape[0] for p in parts)
    canvas = np.zeros((bottom - top, right - left), bool)
    for x, y, bits in parts:
        canvas[y - top:y - top + bits.shape[0], x - left:x - left + bits.shape[1]] |= bits
    return canvas


if __name__ == "__main__":
    t = time.time()
    th = threading.Thread(target=build)
    th.start()
    while th.is_alive():
        time.sleep(5)
        print(f"\r{state['done']}/{state['total']} styles", end="", flush=True)
    print(f"\n{state['status']} in {time.time() - t:.0f}s, {os.path.getsize(PATH) / 1e6:.1f} MB" if os.path.isfile(PATH) else "")
