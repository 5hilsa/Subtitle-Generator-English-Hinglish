#!/usr/bin/env python3
"""Local web UI for the subtitle generator.

Run: .venv/bin/python app.py   then open http://localhost:7860
"""
import os, sys, threading, types, uuid
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

import mlx.core as mx
import numpy as np
import mlx_whisper
from mlx_whisper.audio import load_audio
from mlx_whisper.whisper import AudioEncoder
from hinglish import to_hinglish
from ai_correct import correct_hinglish

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(BASE, "uploads")
OUTPUTS = os.path.join(BASE, "outputs")
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(OUTPUTS, exist_ok=True)

PAUSE_BREAK = 0.45  # seconds of silence that always starts a new subtitle

# Runs on the Apple GPU via MLX. Turbo is the most accurate for Hindi/Hinglish
# but cannot translate; small translates to English cleanly and fast.
TRANSCRIBE_MODEL = "mlx-community/whisper-large-v3-turbo"
TRANSLATE_MODEL = "mlx-community/whisper-small-mlx"

# output mode -> (whisper language override, whisper task)
MODES = {
    "hinglish": ("hi", "transcribe"),   # Hindi speech, Roman letters
    "hindi":    ("hi", "transcribe"),   # Hindi speech, Devanagari
    "english":  (None, "translate"),    # any speech, translated to English
    "original": (None, "transcribe"),   # same language as spoken
}
MODE_SUFFIX = {"hinglish": "hinglish", "hindi": "hi", "english": "en", "original": "orig"}

app = Flask(__name__)
jobs = {}
gpu_lock = threading.Lock()   # one transcription at a time
current = {"job": None}       # job receiving progress updates


class Cancelled(Exception):
    pass


class _Progress:
    """Stand-in for whisper's tqdm bar that reports into the running job."""
    def __init__(self, total=0, **_):
        self.total, self.n = total or 1, 0
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def update(self, n=1):
        self.n += n
        job = current["job"]
        if job:
            if job.get("cancel"):
                raise Cancelled()   # unwinds mlx_whisper.transcribe at the next window
            job["progress"] = min(self.n / self.total, 1.0)

# `import mlx_whisper.transcribe` resolves to the function the package re-exports,
# so patch the module itself.
sys.modules["mlx_whisper.transcribe"].tqdm = types.SimpleNamespace(tqdm=_Progress)


# mlx_whisper runs the audio encoder twice per 30 s window when word timestamps
# are on (once to decode, again to align words) and again on every temperature
# fallback. Reusing the last result for an identical window cuts ~1/3 of the time.
_encode = AudioEncoder.__call__
_last_encoded = {}

def _cached_encode(self, mel):
    prev = _last_encoded.get(id(self))
    if prev is not None and prev[0].shape == mel.shape and mx.array_equal(prev[0], mel).item():
        return prev[1]
    out = _encode(self, mel)
    _last_encoded[id(self)] = (mel, out)
    return out

AudioEncoder.__call__ = _cached_encode


def warm_up():
    """Load the main model and compile its GPU kernels before the first upload."""
    with gpu_lock:
        mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=TRANSCRIBE_MODEL,
                               language="hi", word_timestamps=True, verbose=None)


def build_cues(words, max_words):
    cues, cur = [], []
    for i, w in enumerate(words):
        gap = w["start"] - words[i - 1]["end"] if i else 0
        if cur and (gap >= PAUSE_BREAK or len(cur) >= max_words):
            cues.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    out = []
    for i, c in enumerate(cues):
        start, end = c[0]["start"], c[-1]["end"]
        end = max(end, start + 0.7)                      # keep short cues readable
        if i + 1 < len(cues):
            end = min(end, cues[i + 1][0]["start"] - 0.02)  # never overlap the next one
        out.append({"start": round(start, 3), "end": round(max(end, start + 0.3), 3),
                    "text": " ".join(w["word"] for w in c)})
    return out


def format_ts(seconds):
    h, ms = divmod(int(round(seconds * 1000)), 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(cues):
    return "\n".join(f"{i}\n{format_ts(c['start'])} --> {format_ts(c['end'])}\n{c['text']}\n"
                     for i, c in enumerate(cues, 1))


def run_job(job_id, path, mode, spoken, max_words):
    job = jobs[job_id]
    try:
        # Pull just the audio track (16 kHz mono) out of the video, then drop the
        # video file: everything after this works on the audio alone.
        job["stage"] = "Extracting audio…"
        try:
            audio = load_audio(path)
        finally:
            os.remove(path)
        if audio.size == 0:
            raise ValueError("No audio track found in this file")

        with gpu_lock:
            current["job"] = job
            if job.get("cancel"):
                raise Cancelled()
            lang, task = MODES[mode]
            lang = lang or (None if spoken == "auto" else spoken)
            if lang == "en":
                task = "transcribe"            # already English: no translation needed
            model = TRANSLATE_MODEL if task == "translate" else TRANSCRIBE_MODEL
            job["stage"] = "Translating to English…" if task == "translate" else "Transcribing…"
            result = mlx_whisper.transcribe(
                audio, path_or_hf_repo=model, language=lang, task=task, word_timestamps=True,
                condition_on_previous_text=False, verbose=False)
            current["job"] = None

        job["stage"] = "Building subtitles…"
        words = []
        for seg in result["segments"]:
            seg_words = seg.get("words") or [{"word": seg["text"], "start": seg["start"], "end": seg["end"]}]
            for w in seg_words:
                text = w["word"].replace("\ufffd", "").strip()
                if text:
                    words.append({"word": text, "start": w["start"], "end": w["end"]})

        cues = build_cues(words, max_words)
        stem = os.path.splitext(job["name"])[0]
        if mode == "hinglish":
            raw = [c["text"] for c in cues]
            auto = [to_hinglish(t) for t in raw]
            try:
                job["stage"] = "Fixing Hinglish with AI…"
                fixed = correct_hinglish(raw, auto, title=stem)
            except Exception as e:
                fixed = auto
                job["warning"] = f"AI correction skipped ({e}). Showing the basic transliteration."
            for c, text in zip(cues, fixed):
                c["text"] = text
        srt_path = os.path.join(OUTPUTS, f"{stem}_{MODE_SUFFIX[mode]}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(to_srt(cues))
        job.update(status="done", stage="Done", progress=1.0, cues=cues,
                   language=result.get("language"))
    except Cancelled:
        job.update(status="cancelled", stage="Cancelled")
    except Exception as e:
        job.update(status="error", error=str(e))
    finally:
        if current["job"] is job:
            current["job"] = None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="No file uploaded"), 400
    mode = request.form.get("mode", "hinglish")
    if mode not in MODES:
        return jsonify(error=f"Unknown output mode: {mode}"), 400
    job_id = uuid.uuid4().hex[:8]
    name = secure_filename(file.filename) or "upload"
    path = os.path.join(UPLOADS, f"{job_id}_{name}")
    file.save(path)
    jobs[job_id] = {"status": "running", "stage": "Waiting for previous job…" if gpu_lock.locked() else "Starting…",
                    "progress": 0.0, "name": name}
    args = (job_id, path, mode, request.form.get("spoken", "auto"),
            max(1, int(request.form.get("words") or 6)))
    threading.Thread(target=run_job, args=args, daemon=True).start()
    return jsonify(job=job_id)


@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(status="error", error="Unknown job"), 404
    keys = ("status", "stage", "progress", "error", "warning", "cues", "language")
    return jsonify({k: job.get(k) for k in keys})


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    job = jobs.get(job_id)
    if job and job["status"] == "running":
        job["cancel"] = True
    return jsonify(ok=True)


if __name__ == "__main__":
    threading.Thread(target=warm_up, daemon=True).start()
    print("Open http://localhost:7860")
    app.run(host="127.0.0.1", port=7860, debug=False, threaded=True)
