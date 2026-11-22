#!/usr/bin/env python3
"""Correction memory: learns from the subtitle edits you make in the web UI.

Every edited line is saved as a correction (what the app wrote -> what you
changed it to). From those, word-level fix rules are derived ("klem" -> "claim").

"Fix a word once, and it's right on every video after that":
  - A fix applies from the very next video (CONFIRM = 1), in three places:
      1. before the AI: the word as speech recognition heard it (Devanagari,
         e.g. "क्लेम") is swapped for your spelling, so the AI sees "claim";
      2. after the AI: your exact misspelling is replaced wherever it appears;
      3. a final check: if the line came from that same spoken word but your
         spelling is still missing (the AI misspelled it a new way), the
         closest word in the line is replaced with yours.
  - All rules and recent corrected lines also go to Claude as guidance.
  - Short everyday words whose spelling depends on meaning ("main" = I / in)
    are only given to Claude as hints, never forced everywhere.

Rules are recomputed from the saved corrections, so deleting a correction or
switching a rule off takes effect on the next video.

Each user has their own memory (data/feedback/<user id>.json): one creator's
fixes never change another creator's captions.
"""
import json, os, re, shutil, threading, time
from collections import Counter, defaultdict
from difflib import SequenceMatcher

import config
from hinglish import to_hinglish

DIR = os.path.join(config.DATA_DIR, "feedback")
os.makedirs(DIR, exist_ok=True)

# Before accounts existed, everything lived in one shared file: it becomes the local user's.
_OLD = os.path.join(config.BASE, "feedback", "corrections.json")
if os.path.exists(_OLD) and not os.path.exists(os.path.join(DIR, "local.json")):
    shutil.copyfile(_OLD, os.path.join(DIR, "local.json"))
CONFIRM = 1        # times a fix must be made before it is applied automatically
# Everyday words whose right spelling depends on meaning: hints for Claude, never forced.
AMBIGUOUS = {"main", "mein", "me", "mai", "hai", "hain", "he", "se", "ki", "ke", "ka", "ko", "to", "toh",
             "na", "ne", "par", "pe", "ho", "jo", "ye", "yeh", "wo", "woh", "aur", "bhi", "hi", "kya",
             "tha", "thi", "the", "kar", "kare", "karo", "a", "an", "i", "in", "on", "it", "is", "of"}
MAX_PHRASE = 3     # longest phrase (in words) a rule may rewrite
EXAMPLES = 40      # recent corrected lines shown to Claude

_lock = threading.Lock()
_PUNCT = ".,!?;:\"'()[]…-–—।"
# \w misses Devanagari vowel signs, so treat the whole block as word characters.
_WORD = r"[\w\u0900-\u097F]"


def _path(uid):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uid or ""):
        raise ValueError("bad user id")
    return os.path.join(DIR, f"{uid}.json")


def _load(uid):
    try:
        with open(_path(uid), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("corrections", {})
    data.setdefault("disabled", [])
    return data


def _save(uid, data):
    path = _path(uid)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def record(uid, video, mode, index, before, after, source=""):
    """Save (or update) the correction for one subtitle line. Editing a line back
    to what the app wrote removes it."""
    key = f"{mode}|{video}|{index}"
    with _lock:
        data = _load(uid)
        if before.strip() == after.strip():
            data["corrections"].pop(key, None)
        else:
            data["corrections"][key] = {
                "mode": mode, "video": video, "index": index, "source": source,
                "before": before, "after": after, "time": time.time()}
        _save(uid, data)


def _words(text):
    return [w.strip(_PUNCT) for w in text.split() if w.strip(_PUNCT)]


def _pairs(before, after):
    """Word-level replacements between two versions of a line."""
    a, b = _words(before), _words(after)
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        if i2 - i1 == j2 - j1:
            # Same number of words: each word is its own fix, so "koins klem" ->
            # "coins claim" teaches klem -> claim on its own, not only as a pair.
            out += [(w, r) for w, r in zip(a[i1:i2], b[j1:j2]) if w != r]
        elif i2 - i1 <= MAX_PHRASE and j2 - j1 <= MAX_PHRASE + 1:
            # Word count changed ("stepmaster" -> "Step Master"): keep it as a phrase.
            out.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return out


_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _source_span(source, wrong):
    """The Devanagari word(s) in what Whisper heard that became `wrong` in the
    caption, e.g. "क्लेम" for "klem". None if no span transliterates close enough."""
    words = _words(source)
    n = len(wrong.split())
    best, best_score = None, 0.6
    for size in range(max(1, n - 1), min(MAX_PHRASE, n + 1) + 1):
        for i in range(len(words) - size + 1):
            span = words[i:i + size]
            if not any(_DEVANAGARI.search(w) for w in span):
                continue
            # Compare with the listed spelling (क्लेम -> claim) and the letter-by-letter one
            # (klem): the misspelling the user fixed can come from either.
            score = max(SequenceMatcher(None, to_hinglish(" ".join(span), lists).lower(), wrong.lower()).ratio()
                        for lists in (True, False))
            if score > best_score:
                best, best_score = " ".join(span), score
    return best


def _ambiguous(wrong):
    return len(wrong.split()) == 1 and (wrong.lower() in AMBIGUOUS or len(wrong) <= 2)


def rules(uid, mode=None):
    """Learned rules, most-used first: [{wrong, right, count, mode, auto, disabled, source}]."""
    with _lock:
        data = _load(uid)
    votes = defaultdict(Counter)          # (mode, wrong.lower()) -> Counter(right)
    sources = defaultdict(Counter)        # (mode, wrong.lower()) -> Counter(Devanagari span)
    spelled = {}
    for c in data["corrections"].values():
        if mode and c["mode"] != mode:
            continue
        for wrong, right in _pairs(c["before"], c["after"]):
            k = (c["mode"], wrong.lower())
            votes[k][right] += 1
            spelled.setdefault(k, wrong)
            if c["mode"] == "hinglish" and c.get("source"):
                span = _source_span(c["source"], wrong)
                if span:
                    sources[k][span] += 1
    disabled = set(data["disabled"])
    out = []
    for (m, low), counter in votes.items():
        right, count = counter.most_common(1)[0]
        rid = f"{m}|{low}"
        amb = _ambiguous(spelled[(m, low)])
        src = sources[(m, low)].most_common(1)[0][0] if sources[(m, low)] else None
        out.append({"id": rid, "mode": m, "wrong": spelled[(m, low)], "right": right,
                    "count": count, "disabled": rid in disabled, "ambiguous": amb, "source": src,
                    "auto": count >= CONFIRM and rid not in disabled and not amb})
    out.sort(key=lambda r: (-r["count"], r["wrong"].lower()))
    return out


def set_disabled(uid, rule_id, disabled):
    with _lock:
        data = _load(uid)
        s = set(data["disabled"])
        s.add(rule_id) if disabled else s.discard(rule_id)
        data["disabled"] = sorted(s)
        _save(uid, data)


def forget(uid, rule_id):
    """Delete every saved correction that produced this rule."""
    mode, low = rule_id.split("|", 1)
    with _lock:
        data = _load(uid)
        data["corrections"] = {
            k: c for k, c in data["corrections"].items()
            if not (c["mode"] == mode and any(w.lower() == low for w, _ in _pairs(c["before"], c["after"])))}
        data["disabled"] = [d for d in data["disabled"] if d != rule_id]
        _save(uid, data)


def stats(uid):
    with _lock:
        data = _load(uid)
    return {"corrections": len(data["corrections"]),
            "videos": len({c["video"] for c in data["corrections"].values()})}


def _match_case(found, right):
    """Keep a sentence-initial capital: 'Klem' -> 'Claim', but 'klem' -> 'claim'."""
    if found[:1].isupper() and right[:1].islower() and found[1:2].islower():
        return right[:1].upper() + right[1:]
    return right


def _pattern(phrase):
    return rf"(?<!{_WORD})" + re.escape(phrase).replace(r"\ ", r"\s+") + rf"(?!{_WORD})"


def apply(uid, text, mode, _rules=None):
    """Replace your exact misspellings, whole-word and case-insensitive."""
    for r in _rules if _rules is not None else rules(uid, mode):
        if r["auto"]:
            text = re.sub(_pattern(r["wrong"]), lambda m, s=r["right"]: _match_case(m.group(), s),
                          text, flags=re.IGNORECASE)
    return text


def apply_source(uid, source, mode, _rules=None):
    """Before the AI: swap the Devanagari word Whisper heard for your spelling,
    so "रोज़ 200 coins क्लेम करो" reaches the AI as "रोज़ 200 coins claim करो"."""
    for r in _rules if _rules is not None else rules(uid, mode):
        if r["auto"] and r["source"]:
            source = re.sub(_pattern(r["source"]), lambda m, s=r["right"]: s, source)
    return source


def enforce(uid, source, text, mode, _rules=None):
    """Final check: when the line came from a word you fixed but your spelling is
    still missing (the AI misspelled it a new way), replace the closest word."""
    for r in _rules if _rules is not None else rules(uid, mode):
        if not (r["auto"] and r["source"] and re.search(_pattern(r["source"]), source)):
            continue
        if re.search(_pattern(r["right"]), text, flags=re.IGNORECASE):
            continue
        tokens = text.split()
        size = len(r["right"].split())
        targets = (r["wrong"].lower(), to_hinglish(r["source"]).lower(), to_hinglish(r["source"], False).lower())
        best, best_score = None, 0.5
        for n in {max(1, size - 1), size, size + 1}:
            for i in range(len(tokens) - n + 1):
                cand = " ".join(t.strip(_PUNCT) for t in tokens[i:i + n]).lower()
                score = max(SequenceMatcher(None, cand, t).ratio() for t in targets)
                if score > best_score:
                    best, best_score = (i, n), score
        if best:
            i, n = best
            tail = tokens[i + n - 1][len(tokens[i + n - 1].rstrip(_PUNCT)):]   # keep trailing , . ?
            head = tokens[i][:len(tokens[i]) - len(tokens[i].lstrip(_PUNCT))]
            tokens[i:i + n] = [head + _match_case(tokens[i].strip(_PUNCT), r["right"]) + tail]
            text = " ".join(tokens)
    return text


def prompt_guidance(uid, mode):
    """Extra instructions for Claude built from your past corrections ('' if none)."""
    active = [r for r in rules(uid, mode) if not r["disabled"]]
    with _lock:
        data = _load(uid)
    examples = sorted((c for c in data["corrections"].values() if c["mode"] == mode),
                      key=lambda c: c["time"], reverse=True)[:EXAMPLES]
    if not active and not examples:
        return ""
    parts = ["The user has corrected earlier subtitles by hand. Follow their preferences: "
             "they override the general rules above whenever they apply. Words already written in "
             "Roman letters inside the Devanagari input are the user's confirmed spellings: copy them "
             "exactly, with the same capitals."]
    if active:
        parts.append("Word fixes the user has made (times made in brackets). Use the right-hand "
                     "spelling wherever the left-hand word or its misheard form appears:\n" +
                     "\n".join(f"- {r['wrong']} -> {r['right']} ({r['count']})" for r in active[:200]))
    if examples:
        parts.append("Recent lines the user corrected (app output -> user's version):\n" +
                     "\n".join(f"- {c['before']} -> {c['after']}" for c in examples))
    return "\n\n".join(parts)
