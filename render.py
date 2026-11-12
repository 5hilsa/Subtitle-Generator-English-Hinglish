#!/usr/bin/env python3
"""Burns template captions into a video with ffmpeg + libass (works on Mac and Windows).

Every word is laid out here: measured with HarfBuzz using the same font files
libass draws with, then placed with its own ASS event. That is what makes the
premium looks possible: boxes and highlighters behind exact words, per-word
colours, glows and pop-ins. libass shapes Devanagari, so Hindi renders too.

Templates are defined in looks.py; the browser preview follows the same rules.
"""
import os, re, struct, subprocess
from functools import lru_cache

import uharfbuzz as hb

import looks
import typefaces
from transcriber import FFMPEG

BASE = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE, "fonts")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

POSITIONS = ("bottom", "middle", "top")
SIZES = {"small": 0.8, "medium": 1.0, "large": 1.25}
DEVANAGARI = looks.DEVANAGARI
LIGHT_FONTS = {"poppins", "lora_medium", "inter_semibold", "kaushan"}


def probe(path):
    """(width, height, duration_seconds) as displayed, honouring phone rotation."""
    run = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, creationflags=_NO_WINDOW)
    info = run.stderr.decode(errors="ignore")
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    if not m:
        raise ValueError("This file has no video track to put captions on")
    w, h = int(m.group(1)), int(m.group(2))
    rot = re.search(r"rotation of (-?\d+(?:\.\d+)?)", info)
    if rot and abs(round(float(rot.group(1)))) % 180 == 90:
        w, h = h, w
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    return w, h, dur


# ---------------------------------------------------------------- fonts

class Font:
    """One font file: HarfBuzz for widths, plus the metrics libass sizes by.
    libass maps \\fs to the font's usWinAscent + usWinDescent, so a text size of
    `em` pixels needs \\fs = em * (winAscent + winDescent) / unitsPerEm."""

    def __init__(self, key):
        info = typefaces.get(key)
        self.key, self.name, self.hindi = key, info["name"], info["hindi"]
        blob = hb.Blob.from_file_path(os.path.join(FONTS_DIR, info["file"]))
        face = hb.Face(blob)
        self.upem = face.upem
        self.font = hb.Font(face)
        os2 = face.reference_table("OS/2").data
        self.win_ascent, self.win_descent = struct.unpack(">HH", os2[74:78])
        cap = struct.unpack(">h", os2[88:90])[0] if len(os2) >= 90 else 0
        self.cap = cap / self.upem if cap > 0 else 0.7

    def width(self, text, em, spacing=0.0):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.font, buf, {})
        adv = sum(p.x_advance for p in buf.glyph_positions)
        return adv * em / self.upem + spacing * em * len(buf.glyph_positions)

    def fs(self, em):
        return em * (self.win_ascent + self.win_descent) / self.upem

    def center_offset(self, em):
        """Baseline to the middle of libass's line box (what \\an5 centres on)."""
        return (self.win_ascent - self.win_descent) / 2 * em / self.upem


@lru_cache(maxsize=None)
def font(key):
    return Font(key)


def _font_for(word, key):
    """Words in Hindi script need a font that has Devanagari."""
    if DEVANAGARI.search(word) and not typefaces.get(key)["hindi"]:
        return font("poppins" if key in LIGHT_FONTS else "poppins_xb")
    return font(key)


# ---------------------------------------------------------------- ASS helpers

def _ts(t):
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _esc(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _colour(hexcol):
    """'#RRGGBB' or '#RRGGBBAA' -> (ASS colour, ASS alpha)."""
    h = hexcol.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = 255 - int(h[6:8], 16) if len(h) == 8 else 0
    return f"&H{b}{g}{r}&".upper(), f"&H{a:02X}&"


def _rounded_rect(w, h, r):
    w, h = round(w), round(h)
    r = round(max(0, min(r, w / 2, h / 2)))
    k = round(r * 0.45)   # bezier handle for a near-circular corner
    return (f"m {r} 0 l {w - r} 0 b {w - k} 0 {w} {k} {w} {r} l {w} {h - r} b {w} {h - k} {w - k} {h} {w - r} {h} "
            f"l {r} {h} b {k} {h} 0 {h - k} 0 {h - r} l 0 {r} b 0 {k} {k} 0 {r} 0")


def _box(x, y, w, h, r, colour, start, end):
    c, a = _colour(colour)
    return (f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,"
            f"{{\\an7\\pos({x:.1f},{y:.1f})\\p1\\bord0\\shad0\\1c{c}\\1a{a}}}{_rounded_rect(w, h, r)}{{\\p0}}")


def _word_times(cue, words):
    """Start/end per word: Whisper's own timings when they still line up with the
    (possibly edited) text, otherwise spread across the cue by word length."""
    wt = cue.get("wt")
    if wt and len(wt) == len(words):
        out = [(max(s, cue["start"]), min(e, cue["end"])) for s, e in wt]
        return [(s, max(e, s + 0.05)) for s, e in out]
    total = sum(len(w) for w in words) or 1
    out, t, span = [], cue["start"], cue["end"] - cue["start"]
    for w in words:
        d = span * len(w) / total
        out.append((t, t + d))
        t += d
    return out


# ---------------------------------------------------------------- layout

def _layout(page_texts, tpl, W, H, base_em, position, visible=None):
    """Places one page of words. Returns a list of words with x/width/baseline/em/font/line.
    `visible`: only the first n words are on screen yet (reveal templates); lines are
    centred on what is showing, the way the words appear one by one."""
    line2 = tpl.get("line2") or {}
    lines = looks.split_lines(page_texts, tpl)
    two_styled = tpl.get("split") == "half" and len(lines) == 2
    spacing = tpl.get("spacing", 0.0)
    placed, widths, heights = [], [], []
    for li, idx in enumerate(lines):
        styled = two_styled and li == 1
        key = line2.get("font", tpl["font"]) if styled else tpl["font"]
        em = base_em * (line2.get("size", 1.0) if styled else 1.0)
        upper = line2.get("upper", tpl.get("upper")) if styled else tpl.get("upper")
        x, row = 0.0, []
        for j in idx:
            text = page_texts[j].upper() if upper else page_texts[j]
            f = _font_for(text, key)
            sp = 0.0 if DEVANAGARI.search(text) else spacing   # spacing breaks up Hindi letter joins
            w = f.width(text, em, sp)
            if row:
                x += f.width(" ", em) + spacing * em
                # Room for the spoken word to grow without touching its neighbours.
                x += em * (tpl.get("active_scale", 1.0) - 1.0) * 1.2
            row.append({"i": j, "text": text, "font": f, "em": em, "x": x, "w": w, "line": li, "styled": styled, "sp": sp})
            x += w
        widths.append(x)
        heights.append(em * 1.18)
        row_vis = [w for w in row if visible is None or w["i"] < visible]
        for w in row:
            w["vis_w"] = (row_vis[-1]["x"] + row_vis[-1]["w"]) if row_vis else 0.0
        placed.append(row)
    # Shrink to fit the frame.
    pad = base_em * 0.45 if tpl.get("page_box") else 0.0
    max_w = W * 0.84 - 2 * pad
    shrink = min(1.0, max_w / max(widths)) if max(widths) > 0 else 1.0
    if shrink < 1.0:
        for row in placed:
            for w in row:
                w["em"] *= shrink; w["x"] *= shrink; w["w"] *= shrink; w["vis_w"] *= shrink
        widths = [w * shrink for w in widths]
        heights = [h * shrink for h in heights]
    block_h = sum(heights)
    portrait = H > W
    margin = H * (0.2 if portrait else 0.08)
    top = {"bottom": H - margin - block_h, "top": margin, "middle": (H - block_h) / 2}[position]
    align = tpl.get("align", "center")
    words, y = [], top
    for row, lw, lh in zip(placed, widths, heights):
        shown = row[0]["vis_w"] if row and visible is not None else lw
        x0 = W * 0.08 + pad if align == "left" else (W - shown) / 2
        baseline = y + lh * 0.8
        for w in row:
            w["x"] += x0
            w["baseline"] = baseline
            words.append(w)
        y += lh
    return words, block_h, top


def _cap_top(w):
    """Top of a box around word `w` (above capitals/ascenders)."""
    return w["baseline"] - w["em"] * (w["font"].cap + 0.2)


def _box_bottom(w):
    return w["baseline"] + w["em"] * 0.24


def build_ass(cues, width, height, template=looks.DEFAULT, position="bottom", size="medium",
              watermark=None, font=None, accent=None):
    """ASS subtitle file for the given cues, styled with one of looks.TEMPLATES.
    `font` (a typefaces key) replaces the template's font; `accent` its accent colour."""
    tpl = looks.with_accent(looks.TEMPLATES.get(template, looks.TEMPLATES[looks.DEFAULT]), accent)
    chosen = typefaces.get(font)
    scale = 1.0
    if chosen:
        scale = chosen["scale"] / typefaces.get(tpl["font"])["scale"]
        tpl["font"] = font
        if "font" in tpl["line2"]:
            tpl["line2"]["font"] = font
    position = position if position in POSITIONS else "bottom"
    portrait = height > width
    base_em = min(width, height) * (0.075 if portrait else 0.06) * tpl["size"] * SIZES.get(size, 1.0) * scale

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Cap,Poppins SemiBold,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        f"Style: Mark,Poppins SemiBold,{round(min(width, height) * 0.045)},&H90FFFFFF,&H90FFFFFF,&H90000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,1.5,0,9,{round(width * 0.04)},{round(width * 0.04)},{round(height * 0.04)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    stateful = bool(tpl.get("upcoming") or tpl.get("active") or tpl.get("active_box") or tpl.get("spoken_box")
                    or tpl.get("active_scale"))
    for cue in cues:
        texts = cue["text"].split()
        if not texts:
            continue
        times = _word_times(cue, texts)
        words = [{"text": t, "start": s, "end": e} for t, (s, e) in zip(texts, times)]
        groups = looks.pages(words, tpl.get("words", 0))
        for gi, group in enumerate(groups):
            p_start = cue["start"] if gi == 0 else group[0]["start"]
            p_end = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else cue["end"]
            if p_end - p_start < 0.05:
                continue
            page_texts = [w["text"] for w in group]
            placed, block_h, top = _layout(page_texts, tpl, width, height, base_em, position)
            emph = looks.emphasis(page_texts, tpl)
            if stateful:
                starts = [p_start] + [max(p_start, min(w["start"], p_end)) for w in group[1:]]
                slices = [(i, starts[i], starts[i + 1] if i + 1 < len(starts) else p_end) for i in range(len(group))]
            else:
                slices = [(None, p_start, p_end)]
            hide = tpl.get("upcoming") == "hide"
            for si, (active, s, e) in enumerate(slices):
                if e - s < 0.01:
                    continue
                if hide:
                    placed, block_h, top = _layout(page_texts, tpl, width, height, base_em, position, visible=active + 1)
                lines += _page_events(placed, tpl, emph, active, s, e, first=si == 0, block=(top, block_h), W=width)
    if watermark and cues:
        end = max(c["end"] for c in cues) + 3600
        lines.append(f"Dialogue: 9,{_ts(0)},{_ts(end)},Mark,,0,0,0,,{_esc(watermark)}")
    return "\n".join(lines) + "\n"


def _page_events(placed, tpl, emph, active, s, e, first, block, W):
    out = []
    line2 = tpl.get("line2") or {}
    pop = first and tpl.get("pop")
    hide = tpl.get("upcoming") == "hide"

    def state(j):
        if active is None:
            return "spoken"
        return "spoken" if j < active else "active" if j == active else "upcoming"

    # Boxes (layer 0)
    if tpl.get("page_box") and placed:
        em = max(w["em"] for w in placed)
        top, bottom = min(_cap_top(w) for w in placed), max(_box_bottom(w) for w in placed)
        x1 = min(w["x"] for w in placed) - em * 0.45
        x2 = max(w["x"] + w["w"] for w in placed) + em * 0.45
        anim = "\\fscx80\\fscy80\\t(0,90,\\fscx106\\fscy106)\\t(90,160,\\fscx100\\fscy100)" if pop else ""
        if anim:   # scale around the centre: position by centre with \an5 instead
            out.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{{\\an5\\pos({(x1 + x2) / 2:.1f},{(top + bottom) / 2:.1f})"
                       f"\\p1\\bord0\\shad0\\1c{_colour(tpl['page_box'])[0]}\\1a{_colour(tpl['page_box'])[1]}{anim}}}"
                       f"{_rounded_rect(x2 - x1, bottom - top + em * 0.1, em * 0.3)}{{\\p0}}")
        else:
            out.append(_box(x1, top - em * 0.05, x2 - x1, bottom - top + em * 0.1, em * 0.3, tpl["page_box"], s, e))
    if tpl.get("active_box") and active is not None:
        w = next(w for w in placed if w["i"] == active)
        pad = w["em"] * 0.18
        out.append(_box(w["x"] - pad, _cap_top(w), w["w"] + 2 * pad, _box_bottom(w) - _cap_top(w), w["em"] * 0.22,
                        tpl["active_box"], s, e))
    if tpl.get("spoken_box") and active is not None:
        for li in sorted({w["line"] for w in placed}):
            row = [w for w in placed if w["line"] == li and w["i"] <= active]
            if row:
                pad = row[0]["em"] * 0.12
                x1, x2 = row[0]["x"] - pad, row[-1]["x"] + row[-1]["w"] + pad
                out.append(_box(x1, min(_cap_top(w) for w in row) + row[0]["em"] * 0.06, x2 - x1,
                                max(_box_bottom(w) for w in row) - min(_cap_top(w) for w in row) - row[0]["em"] * 0.06,
                                row[0]["em"] * 0.1, tpl["spoken_box"], s, e))

    for w in placed:
        st = state(w["i"])
        if hide and st == "upcoming":
            continue
        styled = w["styled"]
        base = line2.get("color", tpl["color"]) if styled else tpl["color"]
        col = base
        if w["i"] in emph and st != "upcoming":
            col = emph[w["i"]]
        if st == "active" and tpl.get("active"):
            col = tpl["active"]
        if st == "upcoming" and tpl.get("upcoming") and tpl["upcoming"] != "hide":
            col = tpl["upcoming"]
        in_box = (tpl.get("active_box") and st == "active") or (tpl.get("spoken_box") and st != "upcoming")
        if in_box and tpl.get("box_text"):
            col = tpl["box_text"]
        em, f = w["em"], w["font"]
        cx, cy = w["x"] + w["w"] / 2, w["baseline"] - f.center_offset(em)
        c1, a1 = _colour(col)
        tags = f"\\an5\\pos({cx:.1f},{cy:.1f})\\fn{f.name}\\fs{f.fs(em):.1f}"
        if w["sp"]:
            tags += f"\\fsp{w['sp'] * em:.1f}"
        anim = ""
        sc = tpl.get("active_scale") if st == "active" else None
        if pop:
            anim = "\\fscx70\\fscy70\\t(0,90,\\fscx108\\fscy108)\\t(90,170,\\fscx100\\fscy100)"
        elif sc:
            anim = f"\\fscx{sc * 100:.0f}\\fscy{sc * 100:.0f}"
        if hide and st == "active":   # the word being revealed fades and rises in
            anim += "\\alpha&HFF&\\t(0,160,\\alpha&H00&)"
        if first and tpl.get("fade"):
            anim += "\\fad(180,0)"
        glow = line2.get("glow", tpl.get("glow")) if styled else tpl.get("glow")
        if glow and not (hide and st == "active"):
            gc, _ = _colour(glow)
            out.append(f"Dialogue: 1,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{{{tags}\\1c{gc}\\3c{gc}\\1a&H70&\\3a&H70&"
                       f"\\bord{em * 0.14:.1f}\\blur{em * 0.35:.1f}\\shad0{anim}}}{_esc(w['text'])}")
        if tpl.get("shadow") == "soft" and not in_box:
            off = em * 0.06
            sh_tags = tags.replace(f"\\pos({cx:.1f},{cy:.1f})", f"\\pos({cx:.1f},{cy + off:.1f})")
            out.append(f"Dialogue: 1,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{{{sh_tags}\\1c&H000000&\\3c&H000000&\\1a&H90&\\3a&H90&"
                       f"\\bord{em * 0.06:.1f}\\blur{em * 0.22:.1f}\\shad0{anim}}}{_esc(w['text'])}")
        bord = tpl.get("outline", 0) * em
        oc = _colour(tpl.get("outline_color", "#000000"))[0]
        shad = em * 0.06 if tpl.get("shadow") == "hard" else 0
        out.append(f"Dialogue: 2,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{{{tags}\\1c{c1}\\1a{a1}\\3c{oc}\\bord{bord:.1f}"
                   f"\\shad{shad:.1f}\\4c&H000000&\\4a&H00&{anim}}}{_esc(w['text'])}")
    return out


def render(video, cues, out_path, template=looks.DEFAULT, position="bottom", size="medium",
           watermark=None, font=None, accent=None, progress=None, should_stop=None):
    """Writes an MP4 with captions burned in. `progress(frac)` gets 0..1 updates."""
    width, height, duration = probe(video)
    ass_path = os.path.splitext(out_path)[0] + ".ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_ass(cues, width, height, template, position, size, watermark, font, accent))
    # Filter paths are relative to BASE: absolute Windows paths ("C:\...") break
    # ffmpeg's filter syntax, and forward slashes work on every OS.
    rel = lambda p: os.path.relpath(p, BASE).replace(os.sep, "/")
    cmd = [FFMPEG, "-nostdin", "-y", "-i", video,
           "-vf", f"ass={rel(ass_path)}:fontsdir=fonts",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
           "-progress", "pipe:1", "-nostats", "-loglevel", "error", out_path]
    proc = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW, text=True, errors="ignore")
    try:
        for line in proc.stdout:
            if should_stop and should_stop():
                proc.kill()
                break
            if line.startswith("out_time_us=") and progress and duration:
                try:
                    progress(min(int(line.split("=", 1)[1]) / 1e6 / duration, 1.0))
                except ValueError:
                    pass
        err = proc.stderr.read()
        code = proc.wait()
    finally:
        try:
            os.remove(ass_path)
        except OSError:
            pass
    if should_stop and should_stop():
        raise InterruptedError()
    if code != 0:
        raise RuntimeError(f"Video export failed: {err.strip().splitlines()[-1] if err.strip() else code}")
    return out_path
