#!/usr/bin/env python3
"""Burns styled captions into a video with ffmpeg + libass (works on Mac and Windows).

Captions are written as an ASS subtitle file, then drawn onto every frame by
ffmpeg's `ass` filter using the fonts shipped in ./fonts, so the result looks
the same on every machine. libass shapes Devanagari correctly, so Hindi output
renders too.
"""
import os, re, subprocess

from transcriber import FFMPEG

BASE = os.path.dirname(os.path.abspath(__file__))
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ASS colours are &HAABBGGRR (alpha 00 = opaque).
WHITE, BLACK, YELLOW = "&H00FFFFFF", "&H00000000", "&H0000E5FF"
STYLES = {
    #            font                 size  text    outline  border back            bold-word  upper
    "clean":    ("Poppins SemiBold",  1.00, WHITE,  BLACK,   1, 3.0, "&H80000000", None,      False),
    "bold_pop": ("Poppins ExtraBold", 1.15, WHITE,  BLACK,   1, 4.0, "&H80000000", YELLOW,    True),
    "boxed":    ("Poppins SemiBold",  0.95, WHITE,  BLACK,   3, 0.0, "&H60000000", None,      False),
    "yellow":   ("Poppins ExtraBold", 1.05, YELLOW, BLACK,   1, 4.5, "&H80000000", None,      False),
    "minimal":  ("Poppins SemiBold",  0.80, WHITE,  BLACK,   1, 1.2, "&HA0000000", None,      False),
}
POSITIONS = {"bottom": 2, "middle": 5, "top": 8}
SIZES = {"small": 0.8, "medium": 1.0, "large": 1.25}


def probe(path):
    """(width, height, duration_seconds) as displayed, honouring phone rotation."""
    run = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, creationflags=_NO_WINDOW)
    info = run.stderr.decode(errors="ignore")
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    if not m:
        raise ValueError("This file has no video track to put captions on")
    w, h = int(m.group(1)), int(m.group(2))
    rot = re.search(r"rotation of (-?\d+(?:\.\d+)?)", info)
    if rot and abs(round(float(rot.group(1)))) % 180 == 90:
        w, h = h, w
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    return w, h, dur


def _ts(t):
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _esc(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _word_times(cue, words):
    """Start/end per word: Whisper's own timings when they still line up with the
    (possibly edited) text, otherwise spread across the cue by word length."""
    wt = cue.get("wt")
    if wt and len(wt) == len(words):
        return [(max(s, cue["start"]), min(e, cue["end"])) for s, e in wt]
    total = sum(len(w) for w in words) or 1
    out, t, span = [], cue["start"], cue["end"] - cue["start"]
    for w in words:
        d = span * len(w) / total
        out.append((t, t + d))
        t += d
    return out


def build_ass(cues, width, height, style="clean", position="bottom", size="medium", watermark=None):
    font, scale, colour, outline_c, border, outline, back, active, upper = STYLES.get(style, STYLES["clean"])
    portrait = height > width
    fs = round(min(width, height) * (0.075 if portrait else 0.06) * scale * SIZES.get(size, 1.0))
    align = POSITIONS.get(position, 2)
    margin_v = round(height * (0.2 if portrait else 0.08)) if align != 5 else 0
    margin_h = round(width * 0.08)
    shadow = 0 if border == 3 else 1
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{fs},{colour},{colour},{outline_c},{back},0,0,0,0,100,100,0,0,"
        f"{border},{outline if border == 1 else round(fs * 0.25)},{shadow},{align},{margin_h},{margin_h},{margin_v},1",
        f"Style: Mark,Poppins SemiBold,{round(fs * 0.45)},&H90FFFFFF,&H90FFFFFF,&H90000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,1.5,0,9,{margin_h // 2},{margin_h // 2},{round(height * 0.04)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for c in cues:
        text = c["text"].upper() if upper else c["text"]
        if not active:
            lines.append(f"Dialogue: 0,{_ts(c['start'])},{_ts(c['end'])},Cap,,0,0,0,,{_esc(text)}")
            continue
        # Word-by-word highlight: one event per word, the spoken word in the accent colour.
        words = text.split()
        times = _word_times(c, words)
        for i, (s, e) in enumerate(times):
            s = c["start"] if i == 0 else s
            e = c["end"] if i == len(words) - 1 else times[i + 1][0]
            body = " ".join(
                (f"{{\\c{active}&\\fscx108\\fscy108}}{_esc(w)}{{\\c{colour}&\\fscx100\\fscy100}}" if j == i else _esc(w))
                for j, w in enumerate(words))
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{body}")
    if watermark and cues:
        end = max(c["end"] for c in cues) + 3600
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(end)},Mark,,0,0,0,,{_esc(watermark)}")
    return "\n".join(lines) + "\n"


def render(video, cues, out_path, style="clean", position="bottom", size="medium",
           watermark=None, progress=None, should_stop=None):
    """Writes an MP4 with captions burned in. `progress(frac)` gets 0..1 updates."""
    width, height, duration = probe(video)
    ass_path = os.path.splitext(out_path)[0] + ".ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_ass(cues, width, height, style, position, size, watermark))
    # Filter paths are relative to BASE: absolute Windows paths ("C:\...") break
    # ffmpeg's filter syntax, and forward slashes work on every OS.
    rel = lambda p: os.path.relpath(p, BASE).replace(os.sep, "/")
    cmd = [FFMPEG, "-nostdin", "-y", "-i", video,
           "-vf", f"ass={rel(ass_path)}:fontsdir=fonts",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
           "-progress", "pipe:1", "-nostats", "-loglevel", "error", out_path]
    proc = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW, text=True, errors="ignore")
    try:
        for line in proc.stdout:
            if should_stop and should_stop():
                proc.kill()
                break
            if line.startswith("out_time_us=") and progress and duration:
                try:
                    progress(min(int(line.split("=", 1)[1]) / 1e6 / duration, 1.0))
                except ValueError:
                    pass
        err = proc.stderr.read()
        code = proc.wait()
    finally:
        try:
            os.remove(ass_path)
        except OSError:
            pass
    if should_stop and should_stop():
        raise InterruptedError()
    if code != 0:
        raise RuntimeError(f"Video export failed: {err.strip().splitlines()[-1] if err.strip() else code}")
    return out_path
