#!/usr/bin/env python3
"""
Subtitle generator using OpenAI Whisper (local, offline).
Install: pip install openai-whisper
Run: python generate_subtitles.py <video_file> [model_size] [max_chars]
"""

import sys, os, datetime

MAX_WORDS = 4  # max words per subtitle segment

def format_ts(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_ms = int(td.total_seconds() * 1000)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def split_into_lines(words, max_words=MAX_WORDS):
    """Split words into chunks of max_words each, preserving timestamps."""
    return [words[i:i + max_words] for i in range(0, len(words), max_words)]

def generate_srt(video_path, model_size="base", max_words=MAX_WORDS):
    import whisper
    print(f"Loading Whisper '{model_size}' model...")
    model = whisper.load_model(model_size)
    print(f"Transcribing: {video_path}")
    result = model.transcribe(video_path, task="transcribe", verbose=False, word_timestamps=True)

    srt_lines = []
    idx = 1

    for seg in result["segments"]:
        words = seg.get("words", [])
        if not words:
            # fallback: no word timestamps
            srt_lines += [str(idx), f"{format_ts(seg['start'])} --> {format_ts(seg['end'])}", seg["text"].strip(), ""]
            idx += 1
            continue

        for line_words in split_into_lines(words, max_words):
            start = line_words[0]["start"]
            end = line_words[-1]["end"]
            text = " ".join(w["word"].strip() for w in line_words)
            srt_lines += [str(idx), f"{format_ts(start)} --> {format_ts(end)}", text, ""]
            idx += 1

    srt_content = "\n".join(srt_lines)
    out_path = os.path.splitext(video_path)[0] + ".srt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"\n✓ Saved: {out_path}")
    print(f"  {idx - 1} subtitle segments")
    print(f"  Language: {result.get('language', 'unknown')}")
    return out_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_subtitles.py <video_file> [model_size] [max_chars]")
        print("Model sizes: tiny, base, small, medium, large (bigger = more accurate)")
        print(f"max_chars: max characters per line (default {MAX_CHARS})")
        sys.exit(1)
    video = sys.argv[1]
    size = sys.argv[2] if len(sys.argv) > 2 else "base"
    words = int(sys.argv[3]) if len(sys.argv) > 3 else MAX_WORDS
    generate_srt(video, size, words)
