#!/usr/bin/env python3
"""Speech-to-text that runs on Mac and Windows.

Picks a backend at start-up:
  mlx            Apple Silicon Macs, on the GPU via MLX (mlx-whisper)
  faster-whisper Windows/Linux/Intel Macs; NVIDIA GPU when CUDA works, else CPU

Override with SUBGEN_BACKEND=mlx|faster-whisper and SUBGEN_DEVICE=cuda|cpu.
Both backends use the same Whisper weights, so accuracy matches across machines.

With GROQ_API_KEY set, speech-to-text runs on Groq's servers instead (free plan,
same Whisper turbo model, a few seconds per video, almost no load on this computer).
The local engine stays as the fallback. SUBGEN_STT=local keeps it all on this computer.
"""
import os, platform, re, subprocess, sys, time, types

import numpy as np
import imageio_ffmpeg

SAMPLE_RATE = 16000
FFMPEG = os.environ.get("SUBGEN_FFMPEG") or imageio_ffmpeg.get_ffmpeg_exe()


class Cancelled(Exception):
    pass


_hook = {"progress": None}   # called with 0..1; may raise Cancelled


def _report(frac):
    cb = _hook["progress"]
    if cb:
        cb(min(max(frac, 0.0), 1.0))


def load_audio(path):
    """Decode any audio/video file to 16 kHz mono float32 with the bundled ffmpeg."""
    cmd = [FFMPEG, "-nostdin", "-threads", "0", "-i", path, "-vn", "-f", "s16le",
           "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-"]
    run = subprocess.run(cmd, capture_output=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if run.returncode != 0:
        err = run.stderr.decode(errors="ignore").strip().splitlines()
        raise RuntimeError(f"Could not read the file: {err[-1] if err else 'ffmpeg failed'}")
    return np.frombuffer(run.stdout, np.int16).flatten().astype(np.float32) / 32768.0


def media_duration(path):
    """Length in seconds, read from the file header (fast; nothing is decoded)."""
    run = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", run.stderr.decode(errors="ignore"))
    if not m:
        raise ValueError("This file doesn't look like a video or audio file")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _pick_backend():
    forced = os.environ.get("SUBGEN_BACKEND")
    if forced:
        return forced
    if sys.platform == "darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401
            return "mlx"
        except ImportError:
            pass
    return "faster-whisper"


BACKEND = _pick_backend()


# ---------------------------------------------------------------- MLX (Apple Silicon)
if BACKEND == "mlx":
    import mlx.core as mx
    import mlx_whisper
    from mlx_whisper.whisper import AudioEncoder

    TRANSCRIBE_MODEL = os.environ.get("SUBGEN_MODEL", "mlx-community/whisper-large-v3-turbo")
    TRANSLATE_MODEL = os.environ.get("SUBGEN_TRANSLATE_MODEL", "mlx-community/whisper-small-mlx")
    DEVICE = "Apple GPU (MLX)"

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
            _report(self.n / self.total)

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

    def _run(audio, model, language, task):
        return mlx_whisper.transcribe(
            audio, path_or_hf_repo=model, language=language, task=task, word_timestamps=True,
            condition_on_previous_text=False, verbose=False if _hook["progress"] else None)


# ---------------------------------------------------------------- faster-whisper (Windows, Linux, Intel Mac)
else:
    if sys.platform == "win32":
        # CUDA libraries installed from pip (nvidia-cublas-cu12, nvidia-cudnn-cu12)
        # live inside site-packages; Windows only finds DLLs on registered paths.
        import site
        for root in site.getsitepackages() + [site.getusersitepackages()]:
            nv = os.path.join(root, "nvidia")
            if os.path.isdir(nv):
                for pkg in os.listdir(nv):
                    dll_dir = os.path.join(nv, pkg, "bin")
                    if os.path.isdir(dll_dir):
                        os.add_dll_directory(dll_dir)
                        os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
    from faster_whisper import WhisperModel
    import ctranslate2

    TRANSCRIBE_MODEL = os.environ.get("SUBGEN_MODEL", "large-v3-turbo")
    TRANSLATE_MODEL = os.environ.get("SUBGEN_TRANSLATE_MODEL", "small")
    _device = os.environ.get("SUBGEN_DEVICE") or ("cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu")
    DEVICE = "NVIDIA GPU (CUDA)" if _device == "cuda" else "CPU"
    _models = {}

    def _model(name):
        global _device, DEVICE
        if name not in _models:
            try:
                _models[name] = WhisperModel(name, device=_device,
                                             compute_type="float16" if _device == "cuda" else "int8")
            except Exception:
                if _device != "cuda":
                    raise
                # CUDA present but its libraries are missing or broken: fall back to CPU.
                _device, DEVICE = "cpu", "CPU"
                _models[name] = WhisperModel(name, device="cpu", compute_type="int8")
        return _models[name]

    def _run(audio, model, language, task):
        segments, info = _model(model).transcribe(
            audio, language=language, task=task, word_timestamps=True,
            condition_on_previous_text=False, beam_size=5)
        total = info.duration or 1
        out = []
        for s in segments:                      # generator: decoding happens as we iterate
            out.append({"start": s.start, "end": s.end, "text": s.text,
                        "words": [{"word": w.word, "start": w.start, "end": w.end} for w in (s.words or [])]})
            _report(s.end / total)
        return {"segments": out, "language": info.language}


# ---------------------------------------------------------------- Groq (cloud, free plan)
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
CLOUD = bool(GROQ_KEY) and os.environ.get("SUBGEN_STT") != "local"
GROQ_URL = "https://api.groq.com/openai/v1/audio/"
GROQ_PIECE = float(os.environ.get("SUBGEN_GROQ_PIECE", 30))   # seconds of audio per request
if CLOUD:
    LOCAL_DEVICE, DEVICE = DEVICE, "Groq cloud (Whisper large-v3-turbo)"


def _opus(audio):
    """16 kHz mono float audio -> small Ogg/Opus file (speech stays clear at 32 kbps)."""
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    run = subprocess.run([FFMPEG, "-nostdin", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
                          "-c:a", "libopus", "-b:a", "32k", "-application", "voip", "-f", "ogg", "-"],
                         input=pcm, capture_output=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if run.returncode != 0:
        raise RuntimeError("Could not compress the audio for upload")
    return run.stdout


def _pieces(audio, target):
    """Cut points about `target` seconds apart, each at the quietest moment of the last
    few seconds before it, so no word is cut in half."""
    frame = SAMPLE_RATE // 50                                          # 20 ms
    n = len(audio) // frame
    rms = np.sqrt((audio[:n * frame].reshape(n, frame) ** 2).mean(axis=1))
    rms = np.convolve(rms, np.ones(15) / 15, mode="same")              # ~300 ms smoothing
    cuts, lo = [], 0
    while (len(audio) - lo) / SAMPLE_RATE > target * 1.3:
        a, b = (lo // frame) + int((target - 8) * 50), (lo // frame) + int(target * 50)
        cut = (a + int(np.argmin(rms[a:b]))) * frame
        cuts.append((lo, cut))
        lo = cut
    cuts.append((lo, len(audio)))
    return cuts


def _groq_piece(audio, lo, hi, language, translate):
    import requests
    data = [("model", "whisper-large-v3" if translate else "whisper-large-v3-turbo"),
            ("response_format", "verbose_json"), ("temperature", "0"),
            ("timestamp_granularities[]", "segment"), ("timestamp_granularities[]", "word")]
    if language and not translate:
        data.append(("language", language))
    clip = _opus(audio[lo:hi])
    for attempt in range(4):
        r = requests.post(GROQ_URL + ("translations" if translate else "transcriptions"),
                          headers={"Authorization": f"Bearer {GROQ_KEY}"}, data=data,
                          files={"file": ("audio.ogg", clip, "audio/ogg")}, timeout=120)
        if r.status_code == 429 and attempt < 3:                # free-plan rate limit: wait as told
            time.sleep(min(float(r.headers.get("retry-after", 5)), 30))
            continue
        r.raise_for_status()
        break
    body, offset = r.json(), lo / SAMPLE_RATE
    segs = [{"start": s["start"] + offset, "end": s["end"] + offset, "text": s["text"], "words": []}
            for s in body.get("segments") or []]
    for w in body.get("words") or []:   # each word goes to the last segment starting before it
        w = {"word": w["word"], "start": w["start"] + offset, "end": w["end"] + offset}
        owner = next((g for g in reversed(segs) if g["start"] <= w["start"] + 0.01), segs[0] if segs else None)
        if owner:
            owner["words"].append(w)
    return segs


def _groq(audio, language, task):
    # Whisper on long audio carries each window's text into the next and can drift into
    # skipping speech; short independent pieces avoid that and run in parallel.
    from concurrent.futures import ThreadPoolExecutor
    pieces = _pieces(audio, GROQ_PIECE)
    done, out = 0, [None] * len(pieces)
    _report(0.02)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_groq_piece, audio, lo, hi, language, task == "translate"): i
                   for i, (lo, hi) in enumerate(pieces)}
        from concurrent.futures import as_completed
        for f in as_completed(futures):
            out[futures[f]] = f.result()
            done += 1
            _report(done / len(pieces))
    return {"segments": [s for part in out for s in part], "language": language}


def transcribe(audio, language=None, task="transcribe", progress=None):
    """Returns {"segments": [{start, end, text, words: [{word, start, end}]}], "language"}.
    `progress(frac)` is called as decoding advances and may raise Cancelled to stop."""
    model = TRANSLATE_MODEL if task == "translate" else TRANSCRIBE_MODEL
    _hook["progress"] = progress
    try:
        if CLOUD:
            try:
                return _groq(audio, language, task)
            except Cancelled:
                raise
            except Exception as e:                               # offline, limit used up…: do it here
                print(f"Groq speech-to-text failed ({e}); using this computer instead")
        return _run(audio, model, language, task)
    finally:
        _hook["progress"] = None


def warm_up():
    """Load the main model (and compile GPU kernels) before the first upload."""
    if CLOUD:
        return                  # loaded only if the cloud ever fails, to keep memory free
    transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language="hi")
