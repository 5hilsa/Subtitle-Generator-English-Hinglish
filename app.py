#!/usr/bin/env python3
"""Web app for the subtitle generator. Runs on macOS, Windows and cloud servers.

Mac:      .venv/bin/python app.py
Windows:  .venv\\Scripts\\python app.py
then open http://localhost:7860

With no GOOGLE_CLIENT_ID set it runs in local mode (no sign-in, no limits).
See config.py and .env.example to run it as a public website.
"""
import mimetypes, os, threading, time, uuid
import numpy as np
from datetime import timedelta
from flask import (Flask, request, jsonify, render_template, send_file, send_from_directory, abort,
                   redirect, Response)
from werkzeug.utils import secure_filename

import config
import db
import auth
import billing
from auth import current_uid, login_required
from plans import PLANS, PRODUCTS

import transcriber
from transcriber import Cancelled, load_audio
import render
import looks
import typefaces
import fontmatch
import fontindex
import compose
from hinglish import to_hinglish
import ai_correct
from ai_correct import correct_hinglish
import feedback
import project as projects
import assgen

mimetypes.add_type("application/wasm", ".wasm")   # the in-browser subtitle engine

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(BASE, "uploads")
OUTPUTS = os.path.join(BASE, "outputs")
RENDERS = os.path.join(BASE, "renders")
for d in (UPLOADS, OUTPUTS, RENDERS):
    os.makedirs(d, exist_ok=True)

PAUSE_BREAK = 0.45      # seconds of silence that always starts a new subtitle
KEEP_HOURS = 6          # uploaded videos and exports are deleted after this

# output mode -> (whisper language override, whisper task)
MODES = {
    "hinglish": ("hi", "transcribe"),   # Hindi speech, Roman letters
    "hindi":    ("hi", "transcribe"),   # Hindi speech, Devanagari
    "english":  (None, "translate"),    # any speech, translated to English
    "original": (None, "transcribe"),   # same language as spoken
}
MODE_SUFFIX = {"hinglish": "hinglish", "hindi": "hi", "english": "en", "original": "orig"}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",                       # blocks cross-site form posts
    SESSION_COOKIE_SECURE=config.BASE_URL.startswith("https://"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=2 * 1024 ** 3,                    # 2 GB upload cap
)
if os.environ.get("TRUST_PROXY") == "1":
    # Behind nginx / a cloud load balancer: trust its X-Forwarded-* headers (https, client IP).
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.register_blueprint(auth.bp)
app.register_blueprint(billing.bp)
db.init()
jobs = {}
gpu_lock = threading.Lock()   # one transcription at a time


def cleanup_old_files():
    """Videos are kept so captions can be burned in later; drop ones from old sessions."""
    cutoff = time.time() - KEEP_HOURS * 3600
    for job_id in [k for k, j in jobs.items() if j["created"] < cutoff and j["status"] != "running"]:
        jobs.pop(job_id, None)
    try:
        projects.cleanup()
    except Exception as e:
        print(f"Project cleanup failed: {e}")
    for d in (UPLOADS, RENDERS):
        for name in os.listdir(d):
            p = os.path.join(d, name)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass


def warm_up():
    """Load the main model before the first upload, and the Google Fonts index for Match from image."""
    with gpu_lock:
        transcriber.warm_up()
    fontindex.load()            # builds it in the background the first time


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
                    "text": " ".join(w["word"] for w in c),
                    "wt": [[round(w["start"], 3), round(w["end"], 3)] for w in c]})
    return out


def format_ts(seconds):
    h, ms = divmod(int(round(seconds * 1000)), 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(cues):
    return "\n".join(f"{i}\n{format_ts(c['start'])} --> {format_ts(c['end'])}\n{c['text']}\n"
                     for i, c in enumerate(cues, 1))


PEAKS_PER_SEC = 50


def waveform_peaks(audio):
    """Loudness of the audio, 50 values a second (0-255), for the editor's waveform."""
    hop = transcriber.SAMPLE_RATE // PEAKS_PER_SEC
    n = len(audio) // hop
    if not n:
        return b""
    peaks = np.abs(audio[:n * hop]).reshape(n, hop).max(axis=1)
    top = float(np.percentile(peaks, 99.5)) or 1.0
    return np.clip(peaks / top * 255, 0, 255).astype(np.uint8).tobytes()


def run_job(job_id, path, mode, spoken, max_words):
    job = jobs[job_id]
    uid = job["uid"]
    try:
        # Pull just the audio track (16 kHz mono) out of the video. The video stays
        # in uploads/ so captions can be burned into it on export.
        job["stage"] = "Extracting audio…"
        audio = load_audio(path)
        if audio.size == 0:
            raise ValueError("No audio track found in this file")
        job["peaks"] = waveform_peaks(audio)
        stem = os.path.splitext(job["name"])[0]
        cues, language = caption_audio(job, audio, mode, spoken, max_words, stem)
        # Save it as a project: the media moves out of the 6-hour uploads folder and is kept
        # for 30 days after the project's last edit.
        try:
            info = compose.probe_media(path)
        except Exception:
            info = {"duration": len(audio) / transcriber.SAMPLE_RATE}
        pid_path = projects.adopt_media(uid, path, job_id)
        path = job["path"] = pid_path
        style = {"template": looks.DEFAULT if not info.get("w") or info["h"] >= info["w"] else "classic"}
        proj = projects.create(uid, stem, pid_path, info, cues, language=language, mode=mode, style=style)
        job["project"] = proj["id"]
        if config.LOCAL_MODE:                                   # keep a copy on your own machine
            srt_path = os.path.join(OUTPUTS, f"{stem}_{MODE_SUFFIX[mode]}.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(to_srt(cues))
        db.charge(uid, len(audio) / transcriber.SAMPLE_RATE)
        job.update(status="done", stage="Done", progress=1.0, cues=cues, language=language)
    except Cancelled:
        job.update(status="cancelled", stage="Cancelled")
        _remove(path)
    except Exception as e:
        job.update(status="error", error=str(e))
        _remove(path)


def caption_audio(job, audio, mode, spoken, max_words, stem):
    """Speech -> caption lines (Whisper, Hinglish AI, this user's learned fixes). Returns (cues, language)."""
    uid = job["uid"]

    def on_progress(frac):
        if job.get("cancel"):
            raise Cancelled()       # unwinds the transcriber at the next window
        job["progress"] = frac

    with gpu_lock:
        if job.get("cancel"):
            raise Cancelled()
        lang, task = MODES[mode]
        lang = lang or (None if spoken == "auto" else spoken)
        if lang == "en":
            task = "transcribe"            # already English: no translation needed
        job["stage"] = "Translating to English…" if task == "translate" else "Transcribing…"
        result = transcriber.transcribe(audio, language=lang, task=task, progress=on_progress)

    job["stage"] = "Building subtitles…"
    words = []
    for seg in result["segments"]:
        seg_words = seg.get("words") or [{"word": seg["text"], "start": seg["start"], "end": seg["end"]}]
        for w in seg_words:
            text = w["word"].replace("\ufffd", "").strip()
            if text:
                words.append({"word": text, "start": w["start"], "end": w["end"]})

    cues = build_cues(words, max_words)
    for c in cues:
        c["source"] = c["text"]           # what Whisper heard, kept for feedback
    # This user's learned fixes ("fix a word once, right on every video after"):
    # see feedback.py for the three places they are applied.
    learned = feedback.rules(uid, mode)
    if mode == "hinglish":
        raw = [feedback.apply_source(uid, c["text"], mode, learned) for c in cues]
        auto = [feedback.apply(uid, to_hinglish(t), mode, learned) for t in raw]
        try:
            job["stage"] = "Fixing Hinglish with AI…"
            fixed = correct_hinglish(raw, auto, title=stem, guidance=feedback.prompt_guidance(uid, mode))
        except Exception as e:
            fixed = auto
            job["warning"] = f"AI correction skipped ({e}). Showing the basic transliteration."
        for c, text in zip(cues, fixed):
            c["text"] = text
    for c in cues:
        c["text"] = feedback.enforce(uid, c["source"], feedback.apply(uid, c["text"], mode, learned), mode, learned)
    return cues, result.get("language")


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def run_render(job_id, cues, template, position, size, watermark, font=None, accent=None):
    job = jobs[job_id]
    r = job["render"]
    out = os.path.join(RENDERS, f"{job_id}_{template}.mp4")
    try:
        render.render(job["path"], cues, out, template=template, position=position, size=size, watermark=watermark,
                      font=font, accent=accent,
                      progress=lambda f: r.update(progress=f), should_stop=lambda: r.get("cancel"))
        r.update(status="done", progress=1.0, file=out)
    except InterruptedError:
        r.update(status="cancelled")
        _remove(out)
    except Exception as e:
        r.update(status="error", error=str(e))
        _remove(out)


def page_context():
    return {"app_name": config.APP_NAME, "local_mode": config.LOCAL_MODE,
            "google_client_id": config.GOOGLE_CLIENT_ID, "payments": config.PAYMENTS_ENABLED,
            "demo_mode": config.DEMO_MODE,
            "plans": PLANS, "products": PRODUCTS, "fonts": typefaces.catalog(current_uid()), "looks": looks.catalog()}


@app.route("/")
def home():
    """The landing page, always. Signed-in visitors see "Open the app" instead of sign-in."""
    return render_template("landing.html", signed_in=bool(current_uid()), **page_context())


@app.route("/app")
def app_page():
    if not current_uid():
        return redirect("/")
    return render_template("index.html", **page_context())


@app.route("/account")
@login_required
def account():
    return jsonify(db.account(current_uid()))


def own_job(job_id):
    """The job, if it belongs to the signed-in user; otherwise 404."""
    job = jobs.get(job_id)
    if not job or job["uid"] != current_uid():
        abort(404)
    return job


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    uid = current_uid()
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="No file uploaded"), 400
    mode = request.form.get("mode", "hinglish")
    if mode not in MODES:
        return jsonify(error=f"Unknown output mode: {mode}"), 400
    cleanup_old_files()
    job_id = uuid.uuid4().hex[:12]
    name = secure_filename(file.filename) or "upload"
    path = os.path.join(UPLOADS, f"{job_id}_{name}")
    file.save(path)
    try:
        seconds = transcriber.media_duration(path)
    except Exception as e:
        _remove(path)
        return jsonify(error=str(e)), 400
    # Minutes of this user's videos still processing count against what's left.
    reserved = sum(j["seconds"] for j in jobs.values() if j["uid"] == uid and j["status"] == "running")
    problem = db.check_allowed(uid, seconds, reserved)
    if problem:
        _remove(path)
        return jsonify(error=problem, upgrade=True), 402
    jobs[job_id] = {"status": "running", "stage": "Waiting for previous job…" if gpu_lock.locked() else "Starting…",
                    "progress": 0.0, "name": name, "path": path, "uid": uid, "seconds": seconds,
                    "created": time.time()}
    args = (job_id, path, mode, request.form.get("spoken", "auto"),
            max(1, int(request.form.get("words") or 6)))
    threading.Thread(target=run_job, args=args, daemon=True).start()
    return jsonify(job=job_id)


@app.route("/status/<job_id>")
@login_required
def status(job_id):
    job = own_job(job_id)
    keys = ("status", "stage", "progress", "error", "warning", "cues", "language", "project")
    return jsonify({k: job.get(k) for k in keys})


@app.route("/peaks/<job_id>")
@login_required
def peaks(job_id):
    data = own_job(job_id).get("peaks")
    if data is None:
        abort(404)
    return Response(data, mimetype="application/octet-stream", headers={"X-Peaks-Per-Sec": str(PEAKS_PER_SEC)})


@app.route("/fonts/<path:name>")
def fonts(name):
    if name.startswith("up-"):                   # someone's own uploaded font: theirs only
        entry = next((f for f in typefaces.catalog(current_uid())["fonts"] if f["file"] == name), None)
        if not entry:
            abort(404)
    return send_from_directory(os.path.join(BASE, "fonts"), name, max_age=86400)


@app.route("/fonts/match", methods=["POST"])
@login_required
def font_match():
    """Match from image: rank fonts by likeness to a picture of some text."""
    d = request.get_json(silent=True) or {}
    try:
        img = fontmatch.read_image(d.get("image") or "")
        return jsonify(fontmatch.match(img, str(d.get("text") or "")[:200], current_uid()))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except OSError:
        return jsonify(error="That file isn't a picture we can read"), 400


@app.route("/fonts/try/<path:name>")
@login_required
def font_try(name):
    """A Google Font downloaded while matching, so the browser can preview it before it's added."""
    return send_from_directory(fontmatch.CACHE, name, max_age=3600)


@app.route("/fonts/upload", methods=["POST"])
@login_required
def font_upload():
    """A font file the user owns (e.g. a paid font): added to their fonts only."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="No file uploaded"), 400
    data = file.read(15 * 1024 * 1024 + 1)
    if len(data) > 15 * 1024 * 1024:
        return jsonify(error="That font file is too big (15 MB at most)"), 400
    path = os.path.join(fontmatch.CACHE, f"upload-{uuid.uuid4().hex}")
    with open(path, "wb") as f:
        f.write(data)
    try:
        return jsonify(font=typefaces.upload(path, current_uid()))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    finally:
        os.remove(path)


@app.route("/fonts/index")
@login_required
def font_index():
    """Progress of the one-time Google Fonts fingerprint download (for Match from image)."""
    return jsonify(fontindex.state)


@app.route("/fonts/add", methods=["POST"])
@login_required
def font_add():
    d = request.get_json(silent=True) or {}
    got = fontmatch.google_file(str(d.get("family") or ""), int(d.get("weight") or 400))
    if not got:
        return jsonify(error="Couldn't get that font from Google Fonts"), 400
    path, weight = got
    return jsonify(font=typefaces.add(path, fontmatch.google_catalog()[d["family"].lower()]["family"], weight))


@app.route("/info")
def info():
    return jsonify(backend=transcriber.BACKEND, device=transcriber.DEVICE)


@app.route("/render/<job_id>", methods=["POST"])
@login_required
def start_render(job_id):
    job = own_job(job_id)
    if job.get("status") != "done":
        return jsonify(error="Generate subtitles first"), 400
    if not os.path.exists(job["path"]):
        return jsonify(error="The original video has expired. Upload it again to export."), 410
    if job.get("render", {}).get("status") == "running":
        return jsonify(error="Already exporting"), 409
    d = request.get_json(silent=True) or {}
    cues = [{"start": float(c["start"]), "end": float(c["end"]), "text": str(c["text"]), "wt": c.get("wt")}
            for c in d.get("cues") or [] if str(c.get("text", "")).strip()]
    if not cues:
        return jsonify(error="No subtitles to burn in"), 400
    template = d.get("template") if d.get("template") in looks.TEMPLATES else looks.DEFAULT
    accent = d.get("accent") if isinstance(d.get("accent"), str) else None   # validated in looks.with_accent
    position = d.get("position") if d.get("position") in render.POSITIONS else "bottom"
    size = d.get("size") if d.get("size") in render.SIZES else "medium"
    num = lambda v, lo, hi: min(max(float(v), lo), hi) if isinstance(v, (int, float)) else None
    x, y, scale = num(d.get("x"), 0, 1), num(d.get("y"), 0, 1), num(d.get("scale"), 0.3, 3)
    if x is not None and y is not None:
        position = (x, y)                     # dragged to a spot on the video in the editor
    if scale is not None:
        size = scale
    font = d.get("font") if d.get("font") in typefaces.FONTS else None   # None = the template's own font
    watermark = f"Made with {config.APP_NAME}" if db.account(current_uid())["watermark"] else None
    job["render"] = {"status": "running", "progress": 0.0, "template": template}
    threading.Thread(target=run_render, args=(job_id, cues, template, position, size, watermark, font, accent),
                     daemon=True).start()
    return jsonify(ok=True)


@app.route("/render/<job_id>/status")
@login_required
def render_status(job_id):
    r = own_job(job_id).get("render")
    if not r:
        return jsonify(status="none")
    return jsonify({k: r.get(k) for k in ("status", "progress", "error")})


@app.route("/render/<job_id>/cancel", methods=["POST"])
@login_required
def cancel_render(job_id):
    r = own_job(job_id).get("render")
    if r and r["status"] == "running":
        r["cancel"] = True
    return jsonify(ok=True)


@app.route("/render/<job_id>/file")
@login_required
def render_file(job_id):
    job = own_job(job_id)
    r = job.get("render") or {}
    if r.get("status") != "done" or not os.path.exists(r.get("file", "")):
        abort(404)
    stem = os.path.splitext(job["name"])[0]
    return send_file(r["file"], as_attachment=True, download_name=f"{stem}_captioned.mp4")


@app.route("/feedback", methods=["POST"])
@login_required
def save_feedback():
    uid = current_uid()
    d = request.get_json(silent=True) or {}
    mode, items = d.get("mode"), d.get("items")
    if mode not in MODES or not isinstance(items, list):
        return jsonify(error="Bad feedback"), 400
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("index"), int):
            feedback.record(uid, str(d.get("video") or "video")[:200], mode, it["index"], str(it.get("before") or ""),
                            str(it.get("after") or ""), str(it.get("source") or ""))
    return jsonify(ok=True, rules=len(feedback.rules(uid, mode)))


@app.route("/feedback/rules")
@login_required
def feedback_rules():
    uid = current_uid()
    return jsonify(rules=feedback.rules(uid), confirm=feedback.CONFIRM, **feedback.stats(uid))


@app.route("/feedback/rules/<path:rule_id>", methods=["POST", "DELETE"])
@login_required
def feedback_rule(rule_id):
    uid = current_uid()
    if request.method == "DELETE":
        feedback.forget(uid, rule_id)
    else:
        feedback.set_disabled(uid, rule_id, bool((request.get_json(silent=True) or {}).get("disabled")))
    return jsonify(ok=True)


@app.route("/cancel/<job_id>", methods=["POST"])
@login_required
def cancel(job_id):
    job = own_job(job_id)
    if job["status"] == "running":
        job["cancel"] = True
    return jsonify(ok=True)


# ---------------------------------------------------------------- projects
peaks_cache = {}


def own_project(pid):
    p = projects.load(current_uid(), pid)
    if not p:
        abort(404)
    return p


@app.route("/projects")
@login_required
def project_list():
    return jsonify(projects=projects.listing(current_uid()))


@app.route("/projects/<pid>", methods=["GET", "PUT", "DELETE"])
@login_required
def project_doc(pid):
    uid = current_uid()
    if request.method == "GET":
        return jsonify(own_project(pid))
    if request.method == "DELETE":
        return jsonify(ok=projects.delete(uid, pid))
    d = request.get_json(silent=True) or {}
    p, conflict = projects.update(uid, pid, d.get("project") or {}, d.get("rev"))
    if p is None:
        abort(404)
    if conflict:
        return jsonify(error="This project was changed in another tab", rev=p["rev"]), 409
    return jsonify(rev=p["rev"], updated=p["updated"])


@app.route("/projects/<pid>/beacon", methods=["POST"])
@login_required
def project_beacon(pid):
    """Last save when the tab closes (sendBeacon can't read replies, so conflicts are just skipped)."""
    d = request.get_json(silent=True, force=True) or {}
    projects.update(current_uid(), pid, d.get("project") or {}, d.get("rev"))
    return ("", 204)


@app.route("/projects/<pid>/assets", methods=["POST"])
@login_required
def project_add_asset(pid):
    """Import another video or audio file into a project (b-roll, music, voice-over...)."""
    uid = current_uid()
    own_project(pid)
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="No file uploaded"), 400
    name = secure_filename(file.filename) or "media"
    path = projects.media_path(uid, f"{pid}_{uuid.uuid4().hex[:6]}_{name}")
    file.save(path)
    try:
        info = compose.probe_media(path)
    except Exception as e:
        _remove(path)
        return jsonify(error=str(e)), 400
    info["name"] = os.path.splitext(file.filename)[0][:80]
    asset, rev = projects.add_asset(uid, pid, path, info)
    return jsonify(asset=asset, rev=rev)


@app.route("/projects/<pid>/assets/<aid>/transcribe", methods=["POST"])
@login_required
def project_transcribe_asset(pid, aid):
    """Captions for the speech in an imported clip. The editor adds them to the project."""
    uid = current_uid()
    p = own_project(pid)
    a = next((a for a in p["assets"] if a["id"] == aid), None)
    if not a:
        abort(404)
    d = request.get_json(silent=True) or {}
    mode = d.get("mode") if d.get("mode") in MODES else p.get("mode", "hinglish")
    reserved = sum(j["seconds"] for j in jobs.values() if j["uid"] == uid and j["status"] == "running")
    problem = db.check_allowed(uid, a["duration"], reserved)
    if problem:
        return jsonify(error=problem, upgrade=True), 402
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "running", "stage": "Starting…", "progress": 0.0, "name": a.get("name") or a["file"],
                    "path": projects.media_path(uid, a["file"]), "uid": uid, "seconds": a["duration"],
                    "created": time.time(), "asset": aid}

    def work():
        job = jobs[job_id]
        try:
            job["stage"] = "Extracting audio…"
            audio = load_audio(job["path"])
            if audio.size == 0:
                raise ValueError("This clip has no sound to caption")
            cues, language = caption_audio(job, audio, mode, d.get("spoken", "auto"),
                                           max(1, min(int(d.get("words") or 6), 12)), p["name"])
            db.charge(uid, len(audio) / transcriber.SAMPLE_RATE)
            job.update(status="done", stage="Done", progress=1.0, cues=cues, language=language)
        except Cancelled:
            job.update(status="cancelled", stage="Cancelled")
        except Exception as e:
            job.update(status="error", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return jsonify(job=job_id)


@app.route("/projects/<pid>/media/<aid>")
@login_required
def project_media(pid, aid):
    p = own_project(pid)
    a = next((a for a in p["assets"] if a["id"] == aid), None)
    path = a and projects.media_path(current_uid(), a["file"])
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, conditional=True)          # supports Range requests, so seeking works


@app.route("/projects/<pid>/peaks/<aid>")
@login_required
def project_peaks(pid, aid):
    p = own_project(pid)
    a = next((a for a in p["assets"] if a["id"] == aid), None)
    path = a and projects.media_path(current_uid(), a["file"])
    if not path or not os.path.exists(path):
        abort(404)
    key = (path, os.path.getmtime(path))
    if key not in peaks_cache:
        try:
            peaks_cache[key] = waveform_peaks(load_audio(path))
        except Exception:
            peaks_cache[key] = b""                      # no sound in this file
    return Response(peaks_cache[key], mimetype="application/octet-stream",
                    headers={"X-Peaks-Per-Sec": str(PEAKS_PER_SEC)})


@app.route("/projects/<pid>/ass", methods=["POST"])
@login_required
def project_ass(pid):
    """The preview's subtitle file, built from the editor's current (maybe unsaved) state.
    The editor sends just the part around the playhead."""
    base = own_project(pid)
    d = request.get_json(silent=True) or {}
    p = projects.clean(d.get("project") or {}, base)
    win = d.get("window")
    window = (float(win[0]), float(win[1])) if isinstance(win, list) and len(win) == 2 else None
    # the free plan's watermark shows in the preview too: what you see is what you export
    watermark = f"Made with {config.APP_NAME}" if db.account(current_uid())["watermark"] else None
    ass, boxes = assgen.build(p, window=window, with_boxes=True, watermark=watermark)
    return jsonify(ass=ass, boxes=boxes)


@app.route("/projects/<pid>/subtitles.<fmt>")
@login_required
def project_subtitles(pid, fmt):
    p = own_project(pid)
    if fmt == "ass":
        body, mime = assgen.build(p)[0], "text/x-ssa"
    elif fmt in ("srt", "vtt"):
        body, mime = assgen.srt(p, vtt=fmt == "vtt"), "text/plain"
    else:
        abort(404)
    return Response(body, mimetype=f"{mime}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{p["name"]}.{fmt}"'})


project_renders = {}


@app.route("/projects/<pid>/export", methods=["POST"])
@login_required
def project_export(pid):
    uid = current_uid()
    p = own_project(pid)
    if not any(t["kind"] in ("video", "audio") and t["clips"] for t in p["tracks"]):
        return jsonify(error="The timeline is empty: add a clip first"), 400
    key = (uid, pid)
    if project_renders.get(key, {}).get("status") == "running":
        return jsonify(error="Already exporting"), 409
    missing = [a["id"] for a in p["assets"] if not os.path.exists(projects.media_path(uid, a["file"]))]
    if missing:
        return jsonify(error="Some media in this project has expired. Import it again to export."), 410
    watermark = f"Made with {config.APP_NAME}" if db.account(uid)["watermark"] else None
    ass, _ = assgen.build(p, watermark=watermark)
    r = project_renders[key] = {"status": "running", "progress": 0.0}
    out = os.path.join(RENDERS, f"{pid}_{int(time.time())}.mp4")

    def work():
        try:
            compose.export(p, lambda f: projects.media_path(uid, f), ass, out,
                           progress=lambda f: r.update(progress=f), should_stop=lambda: r.get("cancel"))
            r.update(status="done", progress=1.0, file=out)
        except InterruptedError:
            r.update(status="cancelled"); _remove(out)
        except Exception as e:
            r.update(status="error", error=str(e)); _remove(out)
    threading.Thread(target=work, daemon=True).start()
    return jsonify(ok=True)


@app.route("/projects/<pid>/export/status")
@login_required
def project_export_status(pid):
    r = project_renders.get((current_uid(), pid))
    return jsonify({k: r.get(k) for k in ("status", "progress", "error")} if r else {"status": "none"})


@app.route("/projects/<pid>/export/cancel", methods=["POST"])
@login_required
def project_export_cancel(pid):
    r = project_renders.get((current_uid(), pid))
    if r and r["status"] == "running":
        r["cancel"] = True
    return jsonify(ok=True)


@app.route("/projects/<pid>/export/file")
@login_required
def project_export_file(pid):
    p = own_project(pid)
    r = project_renders.get((current_uid(), pid)) or {}
    if r.get("status") != "done" or not os.path.exists(r.get("file", "")):
        abort(404)
    return send_file(r["file"], as_attachment=True, download_name=f"{p['name']}_captioned.mp4")


@app.route("/fontmap")
def fontmap():
    """Font names -> files, for the in-browser subtitle engine (same files libass uses on export)."""
    return jsonify({f["name"].lower(): f"/fonts/{f['file']}" for f in typefaces.catalog(current_uid())["fonts"]})


# Under gunicorn (cloud), set SUBGEN_WARMUP=1 to load the model when the server starts.
if os.environ.get("SUBGEN_WARMUP") == "1":
    threading.Thread(target=warm_up, daemon=True).start()

if __name__ == "__main__":
    if os.environ.get("SUBGEN_WARMUP") != "1":
        threading.Thread(target=warm_up, daemon=True).start()
    print(f"Speech-to-text: {transcriber.DEVICE if transcriber.CLOUD else transcriber.BACKEND + ' on ' + transcriber.DEVICE}")
    print(f"Hinglish AI correction: {ai_correct.describe()}")
    print("Mode: " + ("local (no sign-in)" if config.LOCAL_MODE else
                      "DEMO website (test sign-in, simulated payments)" if config.DEMO_MODE else
                      "website (Google sign-in)"))
    url = f"http://localhost:{config.PORT}"
    if (config.LOCAL_MODE or config.DEMO_MODE) and not os.environ.get("SUBGEN_NO_BROWSER"):
        import webbrowser
        threading.Timer(1.5, webbrowser.open, [url]).start()
    print(f"Open {url}")
    app.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)
