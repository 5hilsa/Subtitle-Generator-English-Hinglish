"""Projects, linked captions and the ASS file the preview and the export both draw.

    .venv/bin/python -m unittest discover tests
"""
import copy, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="subgen-test-"))
os.chdir(ROOT)

import assgen, compose, looks, render   # noqa: E402
import project as P                     # noqa: E402

CUES = [{"start": 0.0, "end": 2.6, "text": "namaste dosto, aaj hum step master",
         "wt": [[0, .4], [.4, .9], [.9, 1.2], [1.2, 1.5], [1.5, 2.0], [2.0, 2.6]]},
        {"start": 2.6, "end": 4.8, "text": "et se 25 kyaamna seekh hain,"},
        {"start": 5.0, "end": 6.0, "text": "क्षमा श्रद्धा"}]
INFO = {"w": 1080, "h": 1920, "duration": 8.0}


def make(style=None):
    p = P.create("tester", "test", "f.mp4", INFO, CUES, style=style or {"template": "hustle"})
    return p


def events(ass):
    return [l for l in ass.splitlines() if l.startswith("Dialogue")]


class ProjectModel(unittest.TestCase):
    def test_create_from_cues_keeps_word_times(self):
        p = make()
        g = p["tracks"][1]["groups"][0]
        self.assertEqual([w["text"] for w in g["words"]], CUES[0]["text"].split())
        self.assertEqual((g["words"][1]["t0"], g["words"][1]["t1"]), (.4, .9))
        self.assertEqual(P.load("tester", p["id"])["id"], p["id"])

    def test_clean_rejects_bad_values(self):
        p = make()
        bad = copy.deepcopy(p)
        w = bad["tracks"][1]["groups"][0]["words"][0]
        w["o"] = {"color": "red; drop", "size": 99, "font": "../../etc/passwd", "rotate": "45", "evil": 1}
        bad["assets"] = [{"id": "a1", "file": "/etc/passwd"}]
        out = P.clean(bad, p)
        self.assertEqual(out["tracks"][1]["groups"][0]["words"][0].get("o"), {"size": 5.0, "rotate": 45.0})
        self.assertEqual(out["assets"], p["assets"])            # media always comes from the saved copy

    def test_update_detects_conflicts(self):
        p = make()
        _, conflict = P.update("tester", p["id"], p, p["rev"])
        self.assertFalse(conflict)
        _, conflict = P.update("tester", p["id"], p, p["rev"])  # stale revision
        self.assertTrue(conflict)


class LinkedCaptions(unittest.TestCase):
    def test_captions_follow_a_trimmed_and_moved_clip(self):
        p = make()
        clip = p["tracks"][0]["clips"][0]
        clip.update({"in": 2.6, "out": 6.0, "at": 10.0})        # keep 2.6-6.0 s, placed at 10 s
        rows = [(g["id"], round(a, 2), round(b, 2)) for _, g, _, a, b in P.visible_groups(p)]
        self.assertEqual(rows, [("g1", 10.0, 12.2), ("g2", 12.4, 13.4)])   # line 1 was cut away

    def test_cut_through_a_line_drops_only_the_cut_words(self):
        p = make()
        p["tracks"][0]["clips"][0].update({"in": 1.2, "out": 8.0, "at": 0.0})
        _, g, mapped, _, _ = next(P.visible_groups(p))
        self.assertEqual([w["text"] for w, _, _ in mapped], ["hum", "step", "master"])


class AssOutput(unittest.TestCase):
    def test_same_as_the_old_exporter_for_every_template(self):
        for tpl in looks.TEMPLATES:
            for pos, size in (("bottom", "medium"), ((0.3, 0.25), 1.6)):
                style = {"template": tpl, "accent": "#FF4D6D", "font": "lobster"}
                style.update({"x": pos[0], "y": pos[1], "scale": size} if isinstance(pos, tuple) else {"position": pos, "size": size})
                a = events(assgen.build(make(style))[0])
                b = events(render.build_ass(CUES, 1080, 1920, tpl, pos, size, font="lobster", accent="#FF4D6D"))
                self.assertEqual(a, b, f"{tpl} {pos}")

    def test_word_overrides_and_supers(self):
        p = make({"template": "podcast"})
        g = p["tracks"][1]["groups"][0]
        g["words"][2]["o"] = {"color": "#FFE81F", "scale": 1.4, "rotate": -8, "dy": -0.3, "box": "#FF4D6DFF", "bold": True}
        p["tracks"][2]["supers"].append({"id": "s1", "t0": 0, "t1": 6, "words": [{"id": "x1", "text": "Day"}],
                                         "place": {"x": .5, "y": .12}, "template": "label"})
        ass, boxes = assgen.build(P.clean(p, p), with_boxes=True)
        word = [l for l in events(ass) if l.endswith("}AAJ")]
        self.assertTrue(word and all("\\frz8.0" in l and "\\b1" in l and "\\fscx140" in l for l in word))
        self.assertTrue(any(l.startswith("Dialogue: 4,") or l.startswith("Dialogue: 6,") for l in events(ass)))   # super layer
        self.assertEqual({b["kind"] for b in boxes}, {"group", "super"})

    def test_window_limits_events(self):
        p = make()
        full = events(assgen.build(p)[0])
        part = events(assgen.build(p, window=(4.9, 6.5))[0])
        self.assertTrue(0 < len(part) < len(full))

    def test_srt(self):
        self.assertIn("00:00:02,600 --> 00:00:04,800\net se 25 kyaamna seekh hain,", assgen.srt(make()))


class Timeline(unittest.TestCase):
    def two_tracks(self):
        p = make()
        p["assets"].append({"id": "a2", "kind": "audio", "file": "m.m4a", "duration": 12.0, "w": None, "h": None, "audio": True})
        p["tracks"][0]["clips"] = [{"id": "c1", "asset": "a1", "in": 4.0, "out": 8.0, "at": 0.0},
                                   {"id": "c2", "asset": "a1", "in": 0.0, "out": 4.0, "at": 4.0, "volume": 1.5}]
        p["tracks"].append({"id": "m1", "kind": "audio", "name": "Music", "volume": 0.3, "mute": False,
                            "clips": [{"id": "c3", "asset": "a2", "in": 0, "out": 8, "at": 0, "fadeIn": 1.5, "fadeOut": 1}]})
        p["canvas"] = {"w": 1080, "h": 1080, "fit": "fill"}
        return p

    def test_clip_and_track_settings_survive_a_save(self):
        p = self.two_tracks()
        out = P.clean(p, {**p, "assets": p["assets"]})
        self.assertEqual(out["canvas"], {"w": 1080, "h": 1080, "fit": "fill"})
        music = out["tracks"][-1]
        self.assertEqual((music["volume"], music["clips"][0]["fadeIn"]), (0.3, 1.5))
        self.assertEqual(out["tracks"][0]["clips"][1]["volume"], 1.5)

    def test_audio_cannot_go_on_a_video_track_and_clips_stay_inside_the_file(self):
        p = self.two_tracks()
        p["tracks"][0]["clips"].append({"id": "x", "asset": "a2", "in": 0, "out": 5, "at": 9})
        p["tracks"][0]["clips"][0]["out"] = 99
        out = P.clean(p, p)
        self.assertEqual([c["id"] for c in out["tracks"][0]["clips"]], ["c1", "c2"])
        self.assertEqual(out["tracks"][0]["clips"][0]["out"], 8.0)       # the file is 8 s long

    def test_export_graph(self):
        p = self.two_tracks()
        inputs, g, d = compose.graph(p, lambda f: "/m/" + f, "x.ass")
        self.assertEqual(inputs, ["/m/f.mp4", "/m/m.m4a"])
        self.assertEqual(d, 8.0)
        self.assertIn("trim=start=4.000:end=8.000,setpts=PTS-STARTPTS+0.000/TB", g)
        self.assertIn("crop=1080:1080", g)                                # fill
        self.assertIn("volume=0.300,afade=t=in:st=0:d=1.500,afade=t=out:st=7.000:d=1.000", g)
        self.assertIn("amix=inputs=3", g)

    def test_speed_zoom_and_transitions_survive_a_save(self):
        p = self.two_tracks()
        c1, c2 = p["tracks"][0]["clips"]
        c1.update(speed=2, zoom=9, px=.2, py="x")
        c2.update(trans={"type": "cross", "d": 5}, speed=1)
        out = P.clean(p, p)["tracks"][0]["clips"]
        self.assertEqual({k: out[0].get(k) for k in ("speed", "zoom", "px", "py")}, {"speed": 2, "zoom": 4, "px": .2, "py": None})
        self.assertEqual((out[1]["trans"], out[1].get("speed")), ({"type": "cross", "d": 2}, None))
        c2["trans"] = {"type": "wipe-of-doom"}
        self.assertNotIn("trans", P.clean(p, p)["tracks"][0]["clips"][1])

    def test_captions_follow_a_sped_up_clip(self):
        p = make()
        p["tracks"][0]["clips"][0].update({"in": 0.0, "out": 8.0, "at": 1.0, "speed": 2})
        self.assertEqual(P.duration(p), 5.0)
        rows = [(round(a, 2), round(b, 2)) for _, g, _, a, b in P.visible_groups(p)]
        self.assertEqual(rows, [(1.0, 2.3), (2.3, 3.4), (3.5, 4.0)])

    def test_export_graph_speed_zoom_transitions(self):
        p = self.two_tracks()
        c1, c2 = p["tracks"][0]["clips"]
        c1.update(speed=4)                                              # 4-8 s of the file in 1 s
        c2.update(at=1.0, zoom=2, px=0, py=1, trans={"type": "cross", "d": .4})
        _, g, d = compose.graph(p, lambda f: "/m/" + f, "x.ass")
        self.assertEqual((d, P.clip_end(c2)), (8.0, 5.0))           # the music runs to 8 s
        self.assertIn("setpts=(PTS-STARTPTS)/4.0000+0.000/TB", g)
        self.assertIn("atempo=2.0000,atempo=2.0000", g)
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.400", g)   # the file ends at 8 s: hold the last frame
        self.assertIn("crop=1080:1080:(iw-1080)*0.0000:(ih-1080)*1.0000", g)
        self.assertIn("fade=t=in:st=1.000:d=0.400:alpha=1", g)
        self.assertEqual(compose._atempo(.25), ",atempo=0.5000,atempo=0.5000")


if __name__ == "__main__":
    unittest.main()
