#!/usr/bin/env python3
"""AI pass that turns raw Whisper Hindi into clean, natural Hinglish subtitles.

Whisper writes Hindi speech in Devanagari, mishears some words, and spells
English loanwords phonetically (क्लेम, कॉइन्स). The AI rewrites each subtitle
line in everyday Hinglish, fixing those errors from context, while keeping
exactly one output line per input line so the subtitle timings stay valid.

Engines, picked automatically (override with SUBGEN_AI=claude|groq|off):
  claude  when ANTHROPIC_API_KEY is set: best quality, paid per use
  groq    when GROQ_API_KEY is set: free plan, runs on Groq's servers, a few seconds
Only the transcript text is used, never the audio or video.
"""
import json, os, re, time
from concurrent.futures import ThreadPoolExecutor

import requests

CLAUDE_MODEL = "claude-opus-5-5"
GROQ_MODEL = os.environ.get("SUBGEN_GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_EFFORT = os.environ.get("SUBGEN_GROQ_EFFORT", "low")   # "medium" often fails Groq's JSON check
CHUNK = {"claude": 250, "groq": 400}   # subtitle lines per request
CONTEXT = 6     # neighbouring lines shown (read-only) on each side of a chunk
DEVANAGARI = re.compile("[ऀ-ॿ]")

SYSTEM = """You fix subtitles for Indian videos. The audio is Hindi/Hinglish speech, \
transcribed by Whisper speech recognition into Devanagari. Rewrite every subtitle line \
as natural, correct Hinglish: Hindi in Roman letters, the way people type it on \
WhatsApp and YouTube.

Rules:
- Use everyday spellings: hai, hain, mein, main, nahi, kya, kyun, liye, chahiye, \
zaroor, sirf, roz, jeb, hazaar, kaafi, padega, bataunga, karunga, shuru, rupaye, naye.
- English words the speaker says are written in normal English spelling: app, coins, \
claim, task, install, section, minimum, voucher, video, helpful, episode, survey, redeem.
- Brands, product and person names get their proper spelling and capitalization \
(Step Master, Google Play, Amazon, UPI, PubScale).
- Fix words Whisper clearly misheard, using the surrounding lines and the video title. \
Do not add, drop or reorder content, and do not translate or paraphrase.
- Each output line must cover the same speech as its input line: never move words \
between lines, merge lines or split them. Return exactly one line per input id.
- Write numbers and amounts as digits (200 coins, 10 rupaye, 4000 steps).
- Keep punctuation light: commas, full stops and question marks only where they help reading.

Each input line also shows a rough automatic transliteration ("auto"); it often has \
wrong spellings, so use it only as a hint."""

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def _payload(title, lines, auto, lo, hi):
    return json.dumps({
        "video_title": title,
        "context_before": lines[max(0, lo - CONTEXT):lo],
        "lines": [{"id": i, "devanagari": lines[i], "auto": auto[i]} for i in range(lo, hi)],
        "context_after": lines[hi:hi + CONTEXT],
    }, ensure_ascii=False)


# ---------------------------------------------------------------- Claude (paid, best)
def _claude_chunk(system, title, lines, auto, lo, hi):
    import anthropic
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=64000,
        system=system,
        messages=[{"role": "user", "content": _payload(title, lines, auto, lo, hi)}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason != "end_turn":
        raise RuntimeError(f"AI correction stopped early ({msg.stop_reason})")
    text = next(b.text for b in msg.content if b.type == "text")
    fixed = {l["id"]: l["text"].strip() for l in json.loads(text)["lines"]}
    if set(fixed) != set(range(lo, hi)) or not all(fixed.values()):
        raise RuntimeError("AI correction returned a different number of lines")
    return [fixed[i] for i in range(lo, hi)]


# ---------------------------------------------------------------- Groq (free plan, cloud)
GROQ_SYSTEM = """You proofread Hinglish subtitles for Indian videos. The speech was Hindi/Hinglish, \
transcribed by Whisper speech recognition and converted letter by letter into Roman script, so the text \
has clumsy spellings and some misheard words. Reply with a list of fixes, each one "from" text exactly \
as it appears in the transcript and the "to" text it should become, in natural Hinglish (Hindi in Roman \
letters, the way people type it on WhatsApp and YouTube).

Fix:
- Clumsy spellings, to everyday ones: hai, hain, mein, nahi, kya, liye, chahiye, zaroor, sirf, kaafi, \
padega, shuru, rupaye, wale, achha, bahut, zyada, minute.
- English words written phonetically, to normal English spelling (sarve -> survey, minit -> minute).
- Brands and names, to their proper spelling and capitals.
- Words that were clearly misheard, judging from the context and the video title.

Each fix applies everywhere its "from" text appears, so for a word that is only wrong in some places, \
include enough neighbouring words to pick out the right place. List each fix once. Keep the words in \
the same order and do not add, drop, translate or paraphrase anything. Skip text that is already fine.

Be thorough: go through the transcript from start to end and fix every wrong word, not only a few \
examples. Typical fixes: lie -> liye, chalie -> chaliye, klik -> click, chek -> check, \
deetels -> details, veediyo -> video, minimam -> minimum, aagar -> agar, turanth -> turant."""

FIX_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["fixes"], "properties": {
    "fixes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["from", "to"],
                                         "properties": {"from": {"type": "string"}, "to": {"type": "string"}}}}}}


def _norm(word):
    return re.sub(r"[^\w']", "", word.lower())


def _apply_fixes(texts, fixes):
    """Apply "from -> to" fixes across the subtitle lines, matching whole words and allowing a
    match to run over a line break. Replacement words stay on the lines the old ones were on."""
    stream = [(n, w) for n, t in enumerate(texts) for w in t.split()]
    keys = [_norm(w) for _, w in stream]
    new = [w for _, w in stream]
    owner = [n for n, _ in stream]
    taken = [False] * len(stream)
    for frm, to in sorted(fixes, key=lambda f: -len(f[0].split())):
        pat, rep = [_norm(w) for w in frm.split()], to.split()
        if not pat or not all(pat) or not rep or DEVANAGARI.search(to):
            continue
        k = len(pat)
        for i in range(len(keys) - k + 1):
            if keys[i:i + k] == pat and not any(taken[i:i + k]):
                trail = re.search(r"[,.?!]+$", new[i + k - 1])
                words = list(rep)
                if trail and not re.search(r"[,.?!]$", words[-1]):
                    words[-1] += trail.group()             # keep the line's punctuation
                if len(words) == k:
                    new[i:i + k] = words
                else:                                      # different length: keep it on the first line
                    new[i:i + k] = [" ".join(words)] + [""] * (k - 1)
                taken[i:i + k] = [True] * k
    out = [[] for _ in texts]
    for n, w in zip(owner, new):
        if w:
            out[n].append(w)
    return [" ".join(ws) if ws else texts[n] for n, ws in enumerate(out)]


def _groq_chunk(system, title, lines, auto, lo, hi):
    # The free plan allows 8000 tokens a minute, so this is built to be lean: the transcript goes
    # in Roman letters (Devanagari costs ~3x the tokens) and the reply is only a list of fixes.
    guidance = system[len(SYSTEM):].strip()
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": GROQ_SYSTEM + ("\n\n" + guidance if guidance else "")},
                     {"role": "user", "content": f"Video title: {title}\n\nTranscript:\n" + " ".join(auto[lo:hi])}],
        "temperature": 0,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "fixes", "strict": True, "schema": FIX_SCHEMA}},
    }
    if "gpt-oss" in GROQ_MODEL:
        body["reasoning_effort"] = GROQ_EFFORT
    for attempt in range(6):
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=120,
                          headers={"Authorization": f"Bearer {GROQ_KEY}"})
        if r.status_code == 429 and attempt < 5:      # per-minute limit: wait as told
            time.sleep(min(float(r.headers.get("retry-after", 10)), 60))
            continue
        if r.status_code == 400 and "json_validate_failed" in r.text and attempt < 2:
            continue                                  # reply came out malformed: try again
        r.raise_for_status()
        break
    fixes = json.loads(r.json()["choices"][0]["message"]["content"])["fixes"]
    return _apply_fixes(auto[lo:hi], [(f["from"], f["to"]) for f in fixes])


# ----------------------------------------------------------------
def provider():
    """'claude', 'groq' or None (no AI available: basic transliteration only)."""
    forced = os.environ.get("SUBGEN_AI")
    if forced in ("claude", "groq"):
        return forced
    if forced == "off":
        return None
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if GROQ_KEY:
        return "groq"
    return None


def describe():
    """One line for the start-up message."""
    p = provider()
    if p == "claude":
        return f"Claude ({CLAUDE_MODEL}, paid API)"
    if p == "groq":
        return f"Groq {GROQ_MODEL} (free plan, cloud)"
    return "off (set GROQ_API_KEY for free AI correction: console.groq.com/keys)"


def correct_hinglish(lines, auto, title="", guidance=""):
    """lines: Devanagari text per subtitle; auto: rule-based Hinglish per subtitle;
    guidance: extra instructions learned from the user's past corrections.
    Returns corrected Hinglish, one string per subtitle, in the same order."""
    p = provider()
    if p is None:
        raise RuntimeError("no AI available: set GROQ_API_KEY (free) or ANTHROPIC_API_KEY")
    fix = {"claude": _claude_chunk, "groq": _groq_chunk}[p]
    system = SYSTEM + ("\n\n" + guidance if guidance else "")
    size = CHUNK[p]
    spans = [(lo, min(lo + size, len(lines))) for lo in range(0, len(lines), size)]
    # Claude runs chunks in parallel; Groq's free plan (tokens per minute) one at a time.
    with ThreadPoolExecutor(max_workers=4 if p == "claude" else 1) as pool:
        parts = pool.map(lambda s: fix(system, title, lines, auto, *s), spans)
        return [t for part in parts for t in part]
