#!/usr/bin/env python3
"""Projects: everything the editor makes, saved on the server so it can be reopened.

A project is one JSON document:

  canvas   {w, h}: the size of the finished video
  assets   the media files (video/audio) with their duration and size
  tracks   in drawing order:
    video     clips [{id, asset, in, out, at, speed?, zoom?, px?, py?, trans?}]: a slice of an asset placed
              on the timeline; lasts (out-in)/speed; trans = how it comes in from the clip before it
    subtitle  style (the look for the whole track) and groups: one caption line each,
              {id, asset, t0, t1, words: [{id, t0, t1, text, o}], o, place, anim, orig, source}
              Words keep their time in their *asset*, so cutting or moving a clip moves its
              captions with it (see visible_groups).
    super     free text on screen: supers [{id, t0, t1, words: [{id, text, o}], o, place, anim}]

Style overrides ("o") are layered: track style -> group o -> word o, each storing only what
it changes. Keys: font, size, scale, bold, italic, upper, color, stroke, strokeW, shadow, box,
dy (move up/down, in text heights), rotate (degrees), in (entrance animation).

Saved as DATA_DIR/projects/<uid>/<pid>.json; media in DATA_DIR/media/<uid>/. A project and its
media are deleted 30 days after it was last edited.
"""
import json, os, re, shutil, threading, time, uuid

import config
import looks
import typefaces

PROJECTS = os.path.join(config.DATA_DIR, "projects")
MEDIA = os.path.join(config.DATA_DIR, "media")
KEEP_DAYS = 30
VERSION = 1
MAX_GROUPS, MAX_WORDS, MAX_SUPERS = 20000, 80000, 500
_lock = threading.Lock()
_HEX = re.compile(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?")
ENTRANCES = ("none", "pop", "scale", "fade", "slide-up", "slide-down")
ACTIVE = ("none", "color", "box", "scale")


def _uid_dir(root, uid):
    d = os.path.join(root, re.sub(r"[^\w-]", "_", str(uid)))
    os.makedirs(d, exist_ok=True)
    return d


def _path(uid, pid):
    if not re.fullmatch(r"[0-9a-f]{12}", pid or ""):
        raise KeyError(pid)
    return os.path.join(_uid_dir(PROJECTS, uid), pid + ".json")


def media_path(uid, name):
    return os.path.join(_uid_dir(MEDIA, uid), os.path.basename(name))


# ---------------------------------------------------------------- building

def _words_of(cue, ids):
    """Word objects for a caption line, using Whisper's word times when they line up."""
    texts = cue["text"].split()
    wt = cue.get("wt")
    if not (wt and len(wt) == len(texts)):
        total, t, span = sum(len(w) for w in texts) or 1, cue["start"], cue["end"] - cue["start"]
        wt = []
        for w in texts:
            d = span * len(w) / total
            wt.append((t, t + d)); t += d
    return [{"id": next(ids), "t0": round(max(s, cue["start"]), 3), "t1": round(min(max(e, s + .05), cue["end"]), 3),
             "text": w} for w, (s, e) in zip(texts, wt)]


def create(uid, name, media_file, info, cues, language=None, mode="hinglish", style=None):
    """A new project for a freshly captioned video (or audio) file."""
    pid = uuid.uuid4().hex[:12]
    w, h, dur = info.get("w") or 1080, info.get("h") or 1920, info.get("duration") or 0.0
    counter = iter(range(1, 10 ** 9))
    ids = (f"w{n}" for n in counter)
    groups = [{"id": f"g{i}", "asset": "a1", "t0": round(c["start"], 3), "t1": round(c["end"], 3),
               "words": _words_of(c, ids), "orig": c["text"], "source": c.get("source", "")}
              for i, c in enumerate(cues)]
    now = time.time()
    p = {"id": pid, "name": name, "version": VERSION, "rev": 1, "created": now, "updated": now,
         "language": language, "mode": mode,
         "canvas": {"w": w, "h": h},
         "assets": [{"id": "a1", "kind": "video" if info.get("w") else "audio", "file": os.path.basename(media_file),
                     "duration": dur, "w": info.get("w"), "h": info.get("h"), "audio": info.get("audio", True),
                     "name": name}],
         "tracks": [{"id": "v1", "kind": "video", "name": "Video 1",
                     "clips": [{"id": "c1", "asset": "a1", "in": 0.0, "out": dur, "at": 0.0}]},
                    {"id": "s1", "kind": "subtitle", "name": "Captions", "style": clean_track_style(style or {}),
                     "groups": groups},
                    {"id": "x1", "kind": "super", "name": "Text", "supers": []}],
         "nextId": len(cues) + sum(len(g["words"]) for g in groups) + 10}
    save(uid, p, new=True)
    return p


# ---------------------------------------------------------------- validation

def _num(v, lo, hi, default=None):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi) if v == v else default


def _colour(v):
    return v if isinstance(v, str) and _HEX.fullmatch(v) else None


def clean_override(o):
    """Only known keys with sensible values; anything else is dropped."""
    if not isinstance(o, dict):
        return {}
    out = {}
    if typefaces.get(o.get("font")):
        out["font"] = o["font"]
    for k, lo, hi in (("size", .2, 5), ("scale", .2, 5), ("strokeW", 0, .4), ("dy", -6, 6), ("rotate", -180, 180)):
        v = _num(o.get(k), lo, hi)
        if v is not None:
            out[k] = round(v, 4)
    for k in ("bold", "italic", "upper"):
        if isinstance(o.get(k), bool):
            out[k] = o[k]
    for k in ("color", "stroke", "shadow", "box"):
        c = _colour(o.get(k))
        if c:
            out[k] = c
    if o.get("in") in ENTRANCES:
        out["in"] = o["in"]
    return out


def _place(p):
    if isinstance(p, dict):
        x, y = _num(p.get("x"), 0, 1), _num(p.get("y"), 0, 1)
        if x is not None and y is not None:
            return {"x": round(x, 4), "y": round(y, 4)}
    return None


def _anim(a):
    if not isinstance(a, dict):
        return {}
    out = {}
    if a.get("in") in ENTRANCES:
        out["in"] = a["in"]
    if a.get("active") in ACTIVE:
        out["active"] = a["active"]
    c = _colour(a.get("color"))
    if c:
        out["color"] = c
    return out


def clean_track_style(st):
    """The whole track's look: a template plus the editor's choices."""
    st = st if isinstance(st, dict) else {}
    out = {"template": st.get("template") if st.get("template") in looks.TEMPLATES else looks.DEFAULT}
    if typefaces.get(st.get("font")):
        out["font"] = st["font"]
    if _colour(st.get("accent")):
        out["accent"] = st["accent"]
    if st.get("position") in ("top", "middle", "bottom"):
        out["position"] = st["position"]
    if st.get("size") in ("small", "medium", "large"):
        out["size"] = st["size"]
    sc = _num(st.get("scale"), .3, 3)
    if sc is not None:
        out["scale"] = round(sc, 3)
    x, y = _num(st.get("x"), 0, 1), _num(st.get("y"), 0, 1)
    if x is not None and y is not None:
        out["x"], out["y"] = round(x, 4), round(y, 4)
    a = _anim(st.get("anim"))
    if a:
        out["anim"] = a
    return out


def _text(v, n=200):
    return str(v or "").replace("\n", " ").strip()[:n]


def clean(p, base):
    """Validated copy of a project sent by the browser. Ids, assets and media come from
    `base` (the saved copy): the browser can't point a project at someone else's files."""
    out = {k: base[k] for k in ("id", "version", "created", "assets", "language", "mode") if k in base}
    out["name"] = _text(p.get("name") or base.get("name"), 120) or base.get("name")
    cv = p.get("canvas") or base["canvas"]
    out["canvas"] = {"w": int(_num(cv.get("w"), 144, 4096, base["canvas"]["w"])) // 2 * 2,
                     "h": int(_num(cv.get("h"), 144, 4096, base["canvas"]["h"])) // 2 * 2,
                     "fit": cv.get("fit") if cv.get("fit") in ("fit", "fill") else "fit"}
    asset_ids = {a["id"] for a in base["assets"]}
    tracks, n_groups, n_words, n_supers = [], 0, 0, 0
    for t in (p.get("tracks") or [])[:40]:
        kind = t.get("kind")
        tr = {"id": _text(t.get("id"), 40), "kind": kind, "name": _text(t.get("name"), 60)}
        if kind == "video" or kind == "audio":
            for k in ("mute", "locked"):
                if t.get(k) is True:
                    tr[k] = True
            vol = _num(t.get("volume"), 0, 2)
            if vol is not None and vol != 1:
                tr["volume"] = round(vol, 3)
            assets = {a["id"]: a for a in base["assets"]}
            clips = []
            for c in (t.get("clips") or [])[:2000]:
                a = assets.get(c.get("asset"))
                if not a or (kind == "video" and not a.get("w")):
                    continue                       # an audio file can't go on a video track
                d = a.get("duration") or 1e6
                cin = _num(c.get("in"), 0, d, 0.0)
                clip = {"id": _text(c.get("id"), 40), "asset": a["id"], "in": round(cin, 3),
                        "out": round(max(_num(c.get("out"), 0, d, d), cin + .05), 3),
                        "at": round(_num(c.get("at"), 0, 1e6, 0.0), 3)}
                for k, lo, hi in (("volume", 0, 2), ("fadeIn", 0, 30), ("fadeOut", 0, 30)):
                    v = _num(c.get(k), lo, hi)
                    if v is not None and v != (1 if k == "volume" else 0):
                        clip[k] = round(v, 3)
                if c.get("mute") is True:
                    clip["mute"] = True
                for k, lo, hi, dflt in (("speed", .25, 4, 1), ("zoom", 1, 4, 1), ("px", 0, 1, .5), ("py", 0, 1, .5)):
                    v = _num(c.get(k), lo, hi)
                    if v is not None and abs(v - dflt) > 1e-6:
                        clip[k] = round(v, 3)
                tr_ = c.get("trans")
                if isinstance(tr_, dict) and tr_.get("type") in TRANSITIONS:
                    clip["trans"] = {"type": tr_["type"], "d": round(_num(tr_.get("d"), .1, 2, .5), 3)}
                clips.append(clip)
            tr["clips"] = clips
        elif kind == "subtitle":
            tr["style"] = clean_track_style(t.get("style"))
            groups = []
            for g in (t.get("groups") or []):
                if n_groups >= MAX_GROUPS:
                    break
                words = []
                for w in (g.get("words") or [])[:200]:
                    text = _text(w.get("text"), 80)
                    if not text or n_words >= MAX_WORDS:
                        continue
                    t0 = _num(w.get("t0"), 0, 1e6, 0.0)
                    word = {"id": _text(w.get("id"), 40), "t0": round(t0, 3),
                            "t1": round(max(_num(w.get("t1"), 0, 1e6, t0), t0 + .02), 3), "text": text.replace(" ", "")}
                    o = clean_override(w.get("o"))
                    if o:
                        word["o"] = o
                    words.append(word); n_words += 1
                if not words:
                    continue
                grp = {"id": _text(g.get("id"), 40), "asset": g.get("asset") if g.get("asset") in asset_ids else "a1",
                       "t0": round(_num(g.get("t0"), 0, 1e6, words[0]["t0"]), 3),
                       "t1": round(_num(g.get("t1"), 0, 1e6, words[-1]["t1"]), 3), "words": words,
                       "orig": _text(g.get("orig"), 2000), "source": _text(g.get("source"), 2000)}
                for k, fn in (("o", clean_override), ("place", _place), ("anim", _anim)):
                    v = fn(g.get(k))
                    if v:
                        grp[k] = v
                groups.append(grp); n_groups += 1
            tr["groups"] = groups
        elif kind == "super":
            sups = []
            for sp in (t.get("supers") or []):
                if n_supers >= MAX_SUPERS:
                    break
                words = [{"id": _text(w.get("id"), 40), "text": _text(w.get("text"), 80).replace(" ", ""),
                          **({"o": clean_override(w.get("o"))} if clean_override(w.get("o")) else {})}
                         for w in (sp.get("words") or [])[:120] if _text(w.get("text"), 80)]
                if not words:
                    continue
                t0 = _num(sp.get("t0"), 0, 1e6, 0.0)
                item = {"id": _text(sp.get("id"), 40), "t0": round(t0, 3),
                        "t1": round(max(_num(sp.get("t1"), 0, 1e6, t0 + 2), t0 + .1), 3), "words": words,
                        "place": _place(sp.get("place")) or {"x": .5, "y": .3},
                        "template": sp.get("template") if sp.get("template") in SUPER_LOOKS else "plain"}
                for k, fn in (("o", clean_override), ("anim", _anim)):
                    v = fn(sp.get(k))
                    if v:
                        item[k] = v
                sups.append(item); n_supers += 1
            tr["supers"] = sups
        else:
            continue
        tracks.append(tr)
    out["tracks"] = tracks
    out["nextId"] = int(_num(p.get("nextId"), 0, 1e9, base.get("nextId", 0)))
    return out


# Ready-made looks for supers (on-screen text that isn't a caption).
SUPER_LOOKS = {
    "plain":   {"name": "Bold", "font": "poppins_xb", "size": .85, "words": 0, "lines": 2, "chars": 22,
                "color": "#FFFFFF", "outline": .06, "outline_color": "#000000", "shadow": "soft"},
    "label":   {"name": "Label", "font": "montserrat_black", "size": .6, "upper": True, "words": 0, "lines": 2, "chars": 26,
                "color": "#111111", "page_box": "#FFFFFFF2"},
    "hook":    {"name": "Hook", "font": "anton", "size": 1.3, "upper": True, "words": 0, "lines": 2, "chars": 14,
                "color": "#FFE81F", "outline": .07, "outline_color": "#000000", "shadow": "hard", "pop": True},
    "lower":   {"name": "Name tag", "font": "inter", "size": .55, "words": 0, "lines": 2, "chars": 30, "align": "left",
                "color": "#FFFFFF", "page_box": "#000000B8"},
    "neon":    {"name": "Neon", "font": "bebas", "size": 1.1, "upper": True, "words": 0, "lines": 2, "chars": 18,
                "color": "#FFFFFF", "glow": "#43FF6E", "shadow": "soft"},
}
for _k, _v in SUPER_LOOKS.items():
    _v.setdefault("line2", {}); _v.setdefault("emphasis", {})


# ---------------------------------------------------------------- the timeline

TRANSITIONS = ("cross", "dip")


def speed(c):
    return c.get("speed") or 1.0


def clip_len(c):
    """How long a clip lasts on the timeline (its stretch of the file, sped up or slowed down)."""
    return (c["out"] - c["in"]) / speed(c)


def clip_end(c):
    return c["at"] + clip_len(c)


def to_tl(c, m):
    """A moment in the clip's file -> the timeline."""
    return c["at"] + (m - c["in"]) / speed(c)


def visible_groups(p):
    """(group, [(word, t0, t1)], g_t0, g_t1) for every caption line, in timeline time.
    Words are mapped through the video clips showing their asset; words that fall outside
    every clip (cut away) are dropped, so captions always follow the video."""
    clips = [c for t in p["tracks"] if t["kind"] in ("video", "audio") for c in t["clips"]]
    for t in p["tracks"]:
        if t["kind"] != "subtitle":
            continue
        for g in t["groups"]:
            mine = [c for c in clips if c["asset"] == g.get("asset", "a1")] or [{"in": 0, "out": 1e9, "at": 0}]
            for c in mine:
                inside = [w for w in g["words"] if w["t0"] < c["out"] and w["t1"] > c["in"]]
                if not inside:
                    continue
                mapped = [(w, to_tl(c, max(w["t0"], c["in"])), to_tl(c, min(w["t1"], c["out"]))) for w in inside]
                g0 = to_tl(c, max(g["t0"], c["in"]))
                g1 = to_tl(c, min(g["t1"], c["out"]))
                yield t, g, mapped, min(g0, mapped[0][1]), max(g1, mapped[-1][2])


def duration(p):
    ends = [clip_end(c) for t in p["tracks"] if t["kind"] in ("video", "audio") for c in t["clips"]]
    return max(ends) if ends else max((a.get("duration") or 0) for a in p["assets"])


# ---------------------------------------------------------------- storage

def save(uid, p, new=False):
    p["updated"] = time.time()
    path = _path(uid, p["id"])
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    return p


def load(uid, pid):
    try:
        with open(_path(uid, pid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, KeyError):
        return None


def update(uid, pid, data, rev):
    """Save the browser's copy if it was based on the latest revision. Returns (project, conflict)."""
    with _lock:
        base = load(uid, pid)
        if base is None:
            return None, False
        if rev is not None and int(rev) != base["rev"]:
            return base, True
        p = clean(data, base)
        p["rev"] = base["rev"] + 1
    return save(uid, p), False


def listing(uid):
    d = _uid_dir(PROJECTS, uid)
    out = []
    for name in os.listdir(d):
        if name.endswith(".json"):
            p = load(uid, name[:-5])
            if p:
                subs = sum(len(t.get("groups", [])) for t in p["tracks"])
                out.append({"id": p["id"], "name": p["name"], "updated": p["updated"], "duration": duration(p),
                            "captions": subs, "canvas": p["canvas"],
                            "expires": p["updated"] + KEEP_DAYS * 86400})
    return sorted(out, key=lambda x: -x["updated"])


def delete(uid, pid):
    p = load(uid, pid)
    if not p:
        return False
    for a in p["assets"]:
        try:
            os.remove(media_path(uid, a["file"]))
        except OSError:
            pass
    os.remove(_path(uid, pid))
    return True


def cleanup():
    """Delete projects (and their media) nobody has edited for KEEP_DAYS."""
    cutoff = time.time() - KEEP_DAYS * 86400
    if not os.path.isdir(PROJECTS):
        return
    for uid in os.listdir(PROJECTS):
        for name in os.listdir(os.path.join(PROJECTS, uid)):
            if name.endswith(".json"):
                p = load(uid, name[:-5])
                if p and p["updated"] < cutoff:
                    delete(uid, p["id"])


def add_asset(uid, pid, path, info):
    """A new media file in an existing project. Returns (asset, new revision)."""
    with _lock:
        p = load(uid, pid)
        if p is None:
            raise KeyError(pid)
        n = 1 + max((int(a["id"][1:]) for a in p["assets"] if a["id"][1:].isdigit()), default=0)
        asset = {"id": f"a{n}", "kind": "video" if info.get("w") else "audio", "file": os.path.basename(path),
                 "duration": info["duration"], "w": info.get("w"), "h": info.get("h"), "audio": info.get("audio", True),
                 "name": info.get("name", "")}
        p["assets"].append(asset)
        p["rev"] += 1
    save(uid, p)
    return asset, p["rev"]


def adopt_media(uid, path, pid):
    """Move an uploaded file into the user's media folder for this project."""
    dest = media_path(uid, f"{pid}_{os.path.basename(path).split('_', 1)[-1]}")
    shutil.move(path, dest)
    return dest
