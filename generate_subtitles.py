#!/usr/bin/env python3
"""
Subtitle generator using OpenAI Whisper (fully offline, no API key needed).

Install:
    pip install openai-whisper

Run:
    python generate_subtitles.py <video_file> [model_size] [max_words] [mode]

Arguments:
    model_size  : tiny | base | small | medium | large  (default: small)
    max_words   : words per subtitle block              (default: 4)
    mode        : english | hinglish | both             (default: both)

Output:
    video_en.srt        — English subtitles
    video_hinglish.srt  — Hinglish subtitles (Roman-script Hindi/English mix)
"""

import sys, os, datetime

MAX_WORDS = 4

# Primes Whisper's decoder to output Roman-script Hinglish instead of Devanagari
HINGLISH_PROMPT = (
    "Transcribe Hindi speech in Roman/Latin letters as natural Hinglish. "
    "Write Hindi words phonetically: main, hoon, kya, nahi, yeh, toh, hai, "
    "tha, the, bhi, aur, lekin, abhi, karo, raha, gaya, bahut, accha, "
    "iska, uska, hum, tum, aap, woh, yahan, wahan, kab, kyun, kuch, sab, "
    "bilkul, theek, zyada, bohot, phir, matlab, samjhe, dekho, suno, bolo"
)


def format_ts(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_ms = int(td.total_seconds() * 1000)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms  = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def split_into_lines(words, max_words):
    return [words[i:i + max_words] for i in range(0, len(words), max_words)]


def extract_segments(whisper_result, max_words):
    segments = []
    for seg in whisper_result["segments"]:
        words = seg.get("words", [])
        if not words:
            segments.append({"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()})
            continue
        for chunk in split_into_lines(words, max_words):
            segments.append({
                "start": chunk[0]["start"],
                "end":   chunk[-1]["end"],
                "text":  " ".join(w["word"].strip() for w in chunk),
            })
    return segments


def write_srt(segments, out_path):
    lines = []
    for idx, seg in enumerate(segments, 1):
        lines += [str(idx), f"{format_ts(seg['start'])} --> {format_ts(seg['end'])}", seg["text"], ""]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  ✓ {out_path}  ({len(segments)} segments)")


# ── Main ───────────────────────────────────────────────────────────────────────

def generate_srt(video_path, model_size="small", max_words=MAX_WORDS, mode="both"):
    import whisper

    if not os.path.isfile(video_path):
        print(f"Error: file not found — {video_path}")
        sys.exit(1)

    base = os.path.splitext(video_path)[0]

    print(f"\nLoading Whisper '{model_size}' model…")
    model = whisper.load_model(model_size)

    # ── English SRT ──────────────────────────────────────────────────────────
    if mode in ("english", "both"):
        print(f"\nTranscribing (English)…")
        result_en = model.transcribe(
            video_path,
            task="transcribe",
            verbose=False,
            word_timestamps=True,
        )
        segs_en = extract_segments(result_en, max_words)
        write_srt(segs_en, base + "_en.srt")
        print(f"  Language detected: {result_en.get('language', 'unknown')}")

    # ── Hinglish SRT ─────────────────────────────────────────────────────────
    if mode in ("hinglish", "both"):
        print(f"\nTranscribing (Hinglish)…")
        result_hi = model.transcribe(
            video_path,
            task="transcribe",
            language="hi",
            initial_prompt=HINGLISH_PROMPT,   # biases decoder to Roman script
            verbose=False,
            word_timestamps=True,
        )
        segs_hi = extract_segments(result_hi, max_words)
        write_srt(segs_hi, base + "_hinglish.srt")

    print("\nDone.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    video    = sys.argv[1]
    size     = sys.argv[2] if len(sys.argv) > 2 else "small"
    words    = int(sys.argv[3]) if len(sys.argv) > 3 else MAX_WORDS
    mode     = sys.argv[4] if len(sys.argv) > 4 else "both"

    if mode not in ("english", "hinglish", "both"):
        print(f"Invalid mode '{mode}'. Use: english | hinglish | both")
        sys.exit(1)

    generate_srt(video, size, words, mode)
