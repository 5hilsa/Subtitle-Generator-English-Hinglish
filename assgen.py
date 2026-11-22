#!/usr/bin/env python3
"""A project -> one ASS subtitle file. The same file is drawn by libass twice: in the
browser for the preview (JASSUB, libass compiled to WebAssembly) and by ffmpeg for the
export, so what you see while editing is exactly what gets burned in.

Also returns where every caption and word lands on the frame ("boxes"), so the editor can
let you click a word on the video, and drag or resize a caption or a super.
"""
import looks
import project as projects
import typefaces
from render import (POSITIONS, SIZES, _esc, _layout, _page_events, _ts, _cap_top, _box_bottom)

SUPER_LAYER = 4      # supers draw above captions (captions use layers 0-2)


def header(W, H):
    return [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Cap,Poppins SemiBold,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        f"Style: Mark,Poppins SemiBold,{round(min(W, H) * 0.045)},&H90FFFFFF,&H90FFFFFF,&H90000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,1.5,0,9,{round(W * 0.04)},{round(W * 0.04)},{round(H * 0.04)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def _with_font(tpl, key):
    """The template drawn in another font, sized so it looks as big as the template's own."""
    chosen = typefaces.get(key)
    if not chosen:
        return tpl, 1.0
    scale = chosen["scale"] / typefaces.get(tpl["font"])["scale"]
    tpl["font"] = key
    if "font" in tpl["line2"]:
        tpl["line2"]["font"] = key
    return tpl, scale


def _apply_anim(tpl, anim, accent):
    """An editor animation choice on top of a template's own behaviour."""
    if not anim:
        return tpl
    tpl = dict(tpl)
    enter = anim.get("in")
    if enter:
        tpl["pop"] = tpl["fade"] = False
        tpl["in"] = None if enter == "none" else enter
    act, col = anim.get("active"), anim.get("color") or accent or "#FFE81F"
    if act:
        for k in ("active", "active_box", "active_scale", "spoken_box"):
            tpl.pop(k, None)
        if act == "color":
            tpl["active"] = col
        elif act == "box":
            tpl["active_box"], tpl["box_text"] = col + ("" if len(col) == 9 else "F0"), tpl.get("box_text") or "#000000"
        elif act == "scale":
            tpl["active_scale"] = 1.18
    return tpl


def _merge(*layers):
    out = {}
    for o in layers:
        if o:
            out.update(o)
    return out


def _page(tpl, texts, ovs, times, p_start, p_end, W, H, base_em, position, layer, boxes, ref):
    """Events for one page of words, plus its on-screen boxes."""
    stateful = bool(tpl.get("upcoming") or tpl.get("active") or tpl.get("active_box") or tpl.get("spoken_box")
                    or tpl.get("active_scale"))
    placed, block_h, top = _layout(texts, tpl, W, H, base_em, position, ov=ovs)
    emph = looks.emphasis(texts, tpl)
    if stateful and len(texts) > 1:
        starts = [p_start] + [max(p_start, min(t0, p_end)) for t0, _ in times[1:]]
        slices = [(i, starts[i], starts[i + 1] if i + 1 < len(starts) else p_end) for i in range(len(texts))]
    elif stateful:
        slices = [(0, p_start, p_end)]
    else:
        slices = [(None, p_start, p_end)]
    hide = tpl.get("upcoming") == "hide"
    out = []
    for si, (active, s, e) in enumerate(slices):
        if e - s < 0.01:
            continue
        if hide:
            placed, block_h, top = _layout(texts, tpl, W, H, base_em, position, visible=active + 1, ov=ovs)
        out += _page_events(placed, tpl, emph, active, s, e, first=si == 0, block=(top, block_h), W=W, layer=layer)
    # where it all is, for clicking and dragging in the editor
    if placed and boxes is not None:
        words = []
        for w in placed:
            o = w.get("ov") or {}
            dy = o.get("dy", 0.0) * w["em"]
            words.append({"i": w["i"], "x": round(w["x"]), "y": round(_cap_top(w) + dy),
                          "w": round(w["w"]), "h": round(_box_bottom(w) - _cap_top(w))})
        x1 = min(b["x"] for b in words); y1 = min(b["y"] for b in words)
        x2 = max(b["x"] + b["w"] for b in words); y2 = max(b["y"] + b["h"] for b in words)
        boxes.append({**ref, "t0": round(p_start, 3), "t1": round(p_end, 3),
                      "box": [x1, y1, x2 - x1, y2 - y1], "words": words})
    return out


def build(p, window=None, watermark=None, with_boxes=False):
    """(ass_text, boxes). `window` = (t0, t1) limits the file to that stretch of the timeline
    (the editor asks for the part around the playhead, which keeps long videos fast)."""
    W, H = p["canvas"]["w"], p["canvas"]["h"]
    portrait = H > W
    unit = min(W, H) * (0.075 if portrait else 0.06)
    lines, boxes = header(W, H), ([] if with_boxes else None)
    inside = (lambda a, b: True) if not window else (lambda a, b: b >= window[0] and a <= window[1])

    # ---- captions
    tracks = {t["id"]: t for t in p["tracks"]}
    track_tpl = {}
    for t in p["tracks"]:
        if t["kind"] == "subtitle":
            st = t.get("style") or {}
            tpl = looks.with_accent(looks.TEMPLATES.get(st.get("template"), looks.TEMPLATES[looks.DEFAULT]), st.get("accent"))
            tpl, fscale = _with_font(tpl, st.get("font"))
            tpl = _apply_anim(tpl, st.get("anim"), st.get("accent"))
            mult = st.get("scale") or SIZES.get(st.get("size"), 1.0)
            pos = (st["x"], st["y"]) if "x" in st and "y" in st else (st.get("position") if st.get("position") in POSITIONS else "bottom")
            track_tpl[t["id"]] = (tpl, unit * tpl["size"] * mult * fscale, pos)
    for t, g, mapped, g0, g1 in projects.visible_groups(p):
        if not inside(g0, g1):
            continue
        tpl, base_em, pos = track_tpl[t["id"]]
        if g.get("anim"):
            tpl = _apply_anim(tpl, g["anim"], (t.get("style") or {}).get("accent"))
        if g.get("place"):
            pos = (g["place"]["x"], g["place"]["y"])
        words = [{"text": w["text"], "start": a, "end": b, "w": w} for w, a, b in mapped]
        pages = looks.pages(words, tpl.get("words", 0))
        for pi, page in enumerate(pages):
            p_start = g0 if pi == 0 else page[0]["start"]
            p_end = pages[pi + 1][0]["start"] if pi + 1 < len(pages) else g1
            if p_end - p_start < 0.05:
                continue
            texts = [w["text"] for w in page]
            ovs = [_merge(g.get("o"), w["w"].get("o")) for w in page]
            times = [(w["start"], w["end"]) for w in page]
            ref = {"kind": "group", "track": t["id"], "id": g["id"], "wids": [w["w"]["id"] for w in page]}
            lines += _page(tpl, texts, ovs, times, p_start, p_end, W, H, base_em, pos, 0, boxes, ref)

    # ---- supers
    for t in p["tracks"]:
        if t["kind"] != "super":
            continue
        for sp in t["supers"]:
            if not inside(sp["t0"], sp["t1"]):
                continue
            tpl = dict(projects.SUPER_LOOKS.get(sp.get("template"), projects.SUPER_LOOKS["plain"]))
            tpl["line2"], tpl["emphasis"] = dict(tpl["line2"]), dict(tpl["emphasis"])
            o = sp.get("o") or {}
            tpl, fscale = _with_font(tpl, o.get("font"))
            tpl = _apply_anim(tpl, sp.get("anim"), None)
            base_em = unit * tpl["size"] * o.get("size", 1.0) * fscale
            texts = [w["text"] for w in sp["words"]]
            ovs = [_merge({k: v for k, v in o.items() if k not in ("font", "size")}, w.get("o")) for w in sp["words"]]
            span = (sp["t1"] - sp["t0"]) / len(texts)
            times = [(sp["t0"] + i * span, sp["t0"] + (i + 1) * span) for i in range(len(texts))]
            ref = {"kind": "super", "track": t["id"], "id": sp["id"], "wids": [w["id"] for w in sp["words"]]}
            lines += _page(tpl, texts, ovs, times, sp["t0"], sp["t1"], W, H, base_em,
                           (sp["place"]["x"], sp["place"]["y"]), SUPER_LAYER, boxes, ref)

    if watermark:
        lines.append(f"Dialogue: 9,{_ts(0)},{_ts(projects.duration(p) + 3600)},Mark,,0,0,0,,{_esc(watermark)}")
    return "\n".join(lines) + "\n", boxes


def srt(p, vtt=False):
    """Plain subtitle file of the captions (text only, in timeline time)."""
    def ts(t, sep):
        ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"
    rows = sorted(((g0, g1, " ".join(w["text"] for w, _, _ in mapped))
                   for _, _, mapped, g0, g1 in projects.visible_groups(p)), key=lambda r: r[0])
    if vtt:
        return "WEBVTT\n\n" + "\n".join(f"{ts(a, '.')} --> {ts(b, '.')}\n{t}\n" for a, b, t in rows)
    return "\n".join(f"{i}\n{ts(a, ',')} --> {ts(b, ',')}\n{t}\n" for i, (a, b, t) in enumerate(rows, 1))
