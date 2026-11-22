#!/usr/bin/env python3
"""Export a whole project with ffmpeg: every clip on every track, cut, sped up or slowed down,
placed and fitted to the chosen frame (9:16, 1:1, 4:5, 16:9), zoomed, joined with crossfades or
dips to black, upper video tracks over lower ones, all audio mixed with
its volume and fades, and the project's captions and text burned in from the same ASS file the
editor previews with libass.
"""
import os, re, subprocess

import project as projects
from render import FFMPEG, BASE, _NO_WINDOW

FPS = 30


def probe_media(path):
    """{w, h, duration, audio} for a video or audio file (w/h None for audio)."""
    run = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, creationflags=_NO_WINDOW)
    info = run.stderr.decode(errors="ignore")
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    m = re.search(r"Stream #\S+.*Video: (?!mjpeg|png).*?(\d{2,5})x(\d{2,5})", info)
    w = h = None
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        rot = re.search(r"rotation of (-?\d+(?:\.\d+)?)", info)
        if rot and abs(round(float(rot.group(1)))) % 180 == 90:
            w, h = h, w
    if not dur and not m:
        raise ValueError("This file has no video or audio we can read")
    return {"w": w, "h": h, "duration": round(dur, 3), "audio": bool(re.search(r"Stream #\S+.*Audio:", info))}


def _fit(W, H, mode):
    if mode == "fill":
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    # fit: letterbox with transparent bars, so a lower track shows through around an overlay
    return (f"scale={W}:{H}:force_original_aspect_ratio=decrease,format=yuva420p,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black@0")


def _atempo(s):
    """ffmpeg's atempo takes 0.5-2 per step: chain steps for other speeds."""
    steps = []
    while s > 2 + 1e-6:
        steps.append(2.0); s /= 2
    while s < .5 - 1e-6:
        steps.append(.5); s /= .5
    if abs(s - 1) > 1e-6:
        steps.append(s)
    return "".join(f",atempo={x:.4f}" for x in steps)


def _zoom(W, H, c):
    """Zoom into the framed picture around (px, py): the same as the editor's CSS scale."""
    z = c.get("zoom") or 1
    if z <= 1.001:
        return ""
    px, py = c.get("px", .5), c.get("py", .5)
    return (f",scale=trunc(iw*{z:.4f}/2)*2:trunc(ih*{z:.4f}/2)*2,"
            f"crop={W}:{H}:(iw-{W})*{px:.4f}:(ih-{H})*{py:.4f}")


def transitions(clips):
    """{clip id: (kind, d, prev clip)} for clips that come in with a transition from the clip
    right before them on the same track; d is capped by both clips' length."""
    out = {}
    clips = sorted(clips, key=lambda c: c["at"])
    for a, b in zip(clips, clips[1:]):
        tr = b.get("trans")
        if not tr or abs(projects.clip_end(a) - b["at"]) > .05:
            continue
        d = min(tr.get("d", .5), projects.clip_len(a) * (.5 if tr["type"] == "cross" else 1),
                projects.clip_len(b) * .5)
        if d >= .04:
            out[b["id"]] = (tr["type"], d, a)
    return out


def graph(p, media_path, ass_rel):
    """(input files, filter graph text, duration) for the project."""
    W, H = p["canvas"]["w"], p["canvas"]["h"]
    fit = p["canvas"].get("fit", "fit")
    D = max(projects.duration(p), 0.1)
    assets = {a["id"]: a for a in p["assets"]}
    inputs, index = [], {}

    def inp(aid):
        if aid not in index:
            index[aid] = len(inputs)
            inputs.append(media_path(assets[aid]["file"]))
        return index[aid]

    parts = [f"color=c=black:s={W}x{H}:r={FPS}:d={D:.3f},format=yuv420p[base]"]
    last, k = "base", 0
    audio = []
    for t in p["tracks"]:
        if t["kind"] not in ("video", "audio"):
            continue
        trans = transitions(t["clips"])
        # what the clip after each clip asks of it: a crossfade plays this clip on under the next
        tail = {v[2]["id"]: (v[0], v[1]) for v in trans.values()}
        for c in sorted(t["clips"], key=lambda c: c["at"]):
            a = assets.get(c["asset"])
            ln = projects.clip_len(c)
            if not a or ln <= 0.01:
                continue
            i, s = inp(c["asset"]), projects.speed(c)
            t_in, t_out = trans.get(c["id"]), tail.get(c["id"])
            # a crossfade out: play `d` more of the file (as far as it goes, then hold the last frame)
            extra = t_out[1] if t_out and t_out[0] == "cross" else 0.0
            src_out = c["out"]
            hold = 0.0
            if extra:
                more = min(extra * s, max((a.get("duration") or c["out"]) - c["out"], 0))
                src_out = c["out"] + more
                hold = extra - more / s
            end = c["at"] + ln
            if t["kind"] == "video" and a.get("w"):
                fades = []
                if t_in:
                    kind, d, _ = t_in
                    fades.append(f"fade=t=in:st={c['at']:.3f}:d={d if kind == 'cross' else d / 2:.3f}:alpha=1")
                if t_out and t_out[0] == "dip":
                    h = t_out[1] / 2
                    fades.append(f"fade=t=out:st={end - h:.3f}:d={h:.3f}:alpha=1")
                v = (f"[{i}:v]trim=start={c['in']:.3f}:end={src_out:.3f},"
                     f"setpts=(PTS-STARTPTS)/{s:.4f}+{c['at']:.3f}/TB" if abs(s - 1) > 1e-6 else
                     f"[{i}:v]trim=start={c['in']:.3f}:end={src_out:.3f},setpts=PTS-STARTPTS+{c['at']:.3f}/TB")
                if hold > .01:
                    v += f",tpad=stop_mode=clone:stop_duration={hold:.3f}"
                v += f",fps={FPS},{_fit(W, H, fit)}{_zoom(W, H, c)}"
                if fades:
                    v += ",format=yuva420p," + ",".join(fades)
                parts.append(v + f",setsar=1[v{k}]")
                parts.append(f"[{last}][v{k}]overlay=eof_action=pass:repeatlast=0:format=auto[o{k}]")
                last = f"o{k}"
            if a.get("audio", True) and not t.get("mute") and not c.get("mute"):
                vol = c.get("volume", 1.0) * t.get("volume", 1.0)
                chain = (f"[{i}:a]atrim=start={c['in']:.3f}:end={src_out:.3f},asetpts=PTS-STARTPTS"
                         f"{_atempo(s)},volume={vol:.3f}")
                if hold > .01:
                    chain += f",apad=pad_dur={hold:.3f}"
                full = ln + extra
                fi, fo = min(c.get("fadeIn", 0), ln / 2), min(c.get("fadeOut", 0), ln / 2)
                if t_in:
                    fi = max(fi, t_in[1] if t_in[0] == "cross" else t_in[1] / 2)
                if t_out:
                    fo = max(fo, t_out[1] if t_out[0] == "cross" else t_out[1] / 2)
                if fi > 0:
                    chain += f",afade=t=in:st=0:d={fi:.3f}"
                if fo > 0:
                    chain += f",afade=t=out:st={full - fo:.3f}:d={fo:.3f}"
                ms = int(round(c["at"] * 1000))
                chain += f",adelay={ms}:all=1[a{k}]"
                parts.append(chain)
                audio.append(f"[a{k}]")
            k += 1
    parts.append(f"[{last}]ass=filename={ass_rel}:fontsdir=fonts,format=yuv420p[vout]")
    if audio:
        parts.append(f"{''.join(audio)}amix=inputs={len(audio)}:normalize=0:dropout_transition=0,"
                     f"aresample=48000,apad,atrim=0:{D:.3f}[aout]")
    else:
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{D:.3f}[aout]")
    return inputs, ";\n".join(parts), D


def export(p, media_path, ass_text, out_path, progress=None, should_stop=None):
    """Render the project to an MP4. `media_path(file)` gives an asset's location on disk."""
    stem = os.path.splitext(out_path)[0]
    ass_path, graph_path = stem + ".ass", stem + ".graph"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)
    rel = lambda path: os.path.relpath(path, BASE).replace(os.sep, "/")
    inputs, text, D = graph(p, media_path, rel(ass_path))
    with open(graph_path, "w", encoding="utf-8") as f:
        f.write(text)
    cmd = [FFMPEG, "-nostdin", "-y"]
    for path in inputs:
        cmd += ["-i", path]
    cmd += ["-filter_complex_script", rel(graph_path), "-map", "[vout]", "-map", "[aout]", "-t", f"{D:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", "-loglevel", "error", out_path]
    proc = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW, text=True, errors="ignore")
    try:
        for line in proc.stdout:
            if should_stop and should_stop():
                proc.kill()
                break
            if line.startswith("out_time_us=") and progress:
                try:
                    progress(min(int(line.split("=", 1)[1]) / 1e6 / D, 1.0))
                except ValueError:
                    pass
        err = proc.stderr.read()
        code = proc.wait()
    finally:
        for path in (ass_path, graph_path):
            try:
                os.remove(path)
            except OSError:
                pass
    if should_stop and should_stop():
        raise InterruptedError()
    if code != 0:
        raise RuntimeError(f"Video export failed: {err.strip().splitlines()[-1] if err.strip() else code}")
