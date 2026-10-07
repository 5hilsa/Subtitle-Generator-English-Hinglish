#!/usr/bin/env python3
"""Claude pass that turns raw Whisper Hindi into clean, natural Hinglish subtitles.

Whisper writes Hindi speech in Devanagari, mishears some words, and spells
English loanwords phonetically (क्लेम, कॉइन्स). Claude rewrites each subtitle
line in everyday Hinglish, fixing those errors from context, while keeping
exactly one output line per input line so the subtitle timings stay valid.

Needs ANTHROPIC_API_KEY (or an `ant auth login` profile). Only the transcript
text is sent — never the audio or video.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import anthropic

MODEL = "claude-opus-5-5"
CHUNK = 250     # subtitle lines per request; long videos run as parallel chunks
CONTEXT = 6     # neighbouring lines shown (read-only) on each side of a chunk

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


def _fix_chunk(client, title, lines, auto, lo, hi):
    payload = {
        "video_title": title,
        "context_before": lines[max(0, lo - CONTEXT):lo],
        "lines": [{"id": i, "devanagari": lines[i], "auto": auto[i]} for i in range(lo, hi)],
        "context_after": lines[hi:hi + CONTEXT],
    }
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
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


def correct_hinglish(lines, auto, title=""):
    """lines: Devanagari text per subtitle; auto: rule-based Hinglish per subtitle.
    Returns corrected Hinglish, one string per subtitle, in the same order."""
    client = anthropic.Anthropic()
    spans = [(lo, min(lo + CHUNK, len(lines))) for lo in range(0, len(lines), CHUNK)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = pool.map(lambda s: _fix_chunk(client, title, lines, auto, *s), spans)
        return [t for part in parts for t in part]
