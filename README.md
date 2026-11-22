# Subtitle Generator

Hindi / Hinglish captions for short videos. Runs locally on **macOS and Windows**.

- Transcribes speech with Whisper (large-v3-turbo).
- Hinglish mode rewrites the text in Roman Hindi with Claude and learns from your edits.
- Exports SRT / VTT, or an MP4 with captions burned in using one of 11 premium templates
  (Hustle, Notebook, Bubble, Punch, Tag, Luxe, Beast, Mumbai, Podcast, Highlight, Classic):
  word-by-word highlights, boxes, glows and pop-ins, with your own colour and any of 74 fonts.

## Start it

| | |
| --- | --- |
| **Mac** | Double-click `start-mac.command` (first time: right-click → Open) |
| **Windows** | Double-click `start-windows.bat` |

The first run installs everything into `.venv` and downloads the speech model (about 1.6 GB), so it takes a few minutes.
The browser opens at http://localhost:7860.

Needs Python 3.9 or newer ([python.org](https://www.python.org/downloads/); on Windows tick "Add python.exe to PATH").
ffmpeg is bundled, so nothing else to install.

## Which speech engine runs

| Machine | Engine | Speed |
| --- | --- | --- |
| Mac with Apple Silicon (M1–M4) | MLX on the GPU | Fast |
| Windows / Linux with an NVIDIA GPU | faster-whisper on CUDA | Fast |
| Any other PC or Intel Mac | faster-whisper on CPU (int8) | Slower: roughly real time or a bit faster |

The engine in use is shown at the top of the page. NVIDIA CUDA libraries are installed automatically on Windows
when `nvidia-smi` is found; if CUDA fails to load the app falls back to CPU.

Overrides (environment variables): `SUBGEN_BACKEND=mlx|faster-whisper`, `SUBGEN_DEVICE=cuda|cpu`,
`SUBGEN_MODEL=<model>`, `SUBGEN_NO_BROWSER=1`.

## Fast and free: Groq (recommended)

With a free Groq API key, both heavy steps run on Groq's servers: speech-to-text (the same Whisper
large-v3-turbo model) and the Hinglish AI correction (`openai/gpt-oss-120b`). A 4-minute video takes well
under a minute and this computer does almost nothing, so any laptop or a small server works.

1. Sign up at [console.groq.com](https://console.groq.com) (free, no card) and create a key under **API Keys**.
2. Set it before starting the app:
   - Mac: `export GROQ_API_KEY=gsk_...`
   - Windows: `setx GROQ_API_KEY gsk_...` (then open a new window)

The free plan has daily limits (about 8 hours of audio a day, at the time of writing), shared by everyone using
your key. If Groq is unreachable or the limit is used up, speech-to-text falls back to this computer.

## Match a font from a picture

In the font picker, **Match from image** takes a screenshot of a caption or design (drop, paste or choose
it, then drag a box around one line of text) and finds the font:

1. The AI vision model on Groq reads the text and names the font if it can.
2. The text is compared, letter shapes against letter shapes, with every font in the library **and all of
   Google Fonts** (about 5,800 styles), then the closest ones are checked exactly. Any free Google Font
   that matches can be added with one click and works in the preview and the export.
3. If the font is a paid one (the AI names it, nothing free matches closely), the app says so, shows the
   closest free fonts, and you can **Upload font** (.ttf/.otf) if you own it. Uploaded fonts are private to
   the account that uploaded them.

The Google Fonts search needs a one-time index: about 11 MB, built in the background on first start (a few
minutes), kept in `data/fontindex.pkl.gz`. Build it ahead with `python fontindex.py`. Until it's ready,
matching uses the library and the AI's suggestions. Without a Groq key, type the text that's in the picture.
Added and uploaded fonts are kept in `data/fonts`.

## Hinglish AI correction

Whisper's raw Hindi is cleaned into natural Hinglish by an AI pass. The app picks the engine itself:

| Engine | Cost | When it is used |
|---|---|---|
| **Claude** (API) | Paid per use, best quality | `ANTHROPIC_API_KEY` is set |
| **Groq** (API) | Free plan | `GROQ_API_KEY` is set |
| None | Free | Basic rule-based transliteration only |

Overrides: `SUBGEN_AI=claude|groq|off`, `SUBGEN_GROQ_MODEL=<model>`,
`SUBGEN_STT=local` (keep speech-to-text on this computer even with a Groq key).
Only subtitle text is sent to the AI, never audio or video (Groq speech-to-text receives the audio).

## The editor and projects

Every video you caption becomes a **project**, saved on the server as you work (look for "Saved"
in the editor's top bar) and listed under **Your projects** on the upload screen. A project and its
video are deleted 30 days after it was last edited.

- **Words, not just lines.** Click a word in the caption list or on the video to pick it (Shift for
  a range, ⌘/Ctrl to add more). The Style panel then edits only that: font, size, colour, outline,
  shadow, a box behind it, bold/italic/capitals, lift, tilt, scale and its entrance. Pick a line to
  style the whole line, or press Esc to style all captions. Save a look under **My looks** and put
  it on anything.
- **Text on screen (supers).** **T** or "Add text" puts free text at the playhead (Bold, Label, Hook,
  Name tag, Neon). It has its own "Text" lane on the timeline, its own place and animation, and
  never clashes with the captions.
- **Place anything anywhere.** Drag captions or text on the video and pull a corner to resize
  (Shift-drag moves one line only). On vertical videos, text under the Reels/Shorts buttons gets a
  "Safe zone" warning.
- **Editing text keeps timing.** Changed words keep their time; new words share the time of the
  words they replace. Split, merge, retime lines or single words (Word view) on the timeline.
- **Preview = export.** The preview runs libass, the subtitle engine ffmpeg burns with, in the browser
  (`static/vendor/jassub`, WebAssembly), and draws the very ASS file the export uses.
- **Finish the video here (timeline editing).** "Import" (or drop files on the timeline) adds more
  video, music or a voice-over. Add video tracks (b-roll / overlays: upper tracks cover lower ones)
  and audio tracks; mute, turn down or lock a track. Drag clips to move them (also onto another
  track), pull their edges to trim, **S** to cut at the playhead, **Delete** to remove a clip and
  close the gap (Alt+Delete leaves the gap). Each clip has its own volume and fade in/out.
  "Caption this clip's speech" adds captions for an imported clip.
- **Captions stay in sync through every cut.** Captions belong to their footage, not to a time on
  the timeline: cut, trim, move or reorder a clip and its captions go with it; a line that would
  sit across a cut is split there.
- **Frame:** 9:16, 1:1, 4:5, 16:9 or the original size, with the picture fitted (whole picture) or
  filled (cropped to the frame). Exports are rendered at that size.
- **Undo everything** with ⌘Z / ⇧⌘Z: text, timing, styles, supers, clips, tracks and the frame.

Tests: `.venv/bin/python -m unittest discover tests` and `node tests/test_rewords.js`.

## Run it as a public website

Without settings the app runs in **local mode**: no sign-in, no limits, nothing to pay. Setting a Google
client ID switches it to **website mode**: a landing page with pricing, Google sign-in, monthly minutes
per plan, a watermark on free exports, Razorpay payments, and a separate learned-fixes dictionary per user.

1. Copy `.env.example` to `.env` and fill it in. Each setting says where to get it:
   Google OAuth client ID, Razorpay keys and webhook secret, Anthropic API key, your `BASE_URL`.
2. Start with Razorpay **Test Mode** keys and pay with a test UPI ID or card to check the flow.
3. Run on a cloud GPU server (any provider with NVIDIA GPUs and Docker):

   ```
   docker build -t hinglish-captions .
   docker run -d --gpus all -p 7860:7860 --env-file .env -v captions-data:/app/data hinglish-captions
   ```

   Put nginx or the provider's load balancer in front for https, and keep `TRUST_PROXY=1`.
4. In the Razorpay dashboard, add the webhook `https://<your domain>/billing/webhook`
   (events `payment.captured` and `order.paid`).

Plans, prices and limits live in `plans.py`. Users, usage and payments are in `data/app.db` (SQLite);
dictionaries in `data/feedback/`. Back up `data/`.

The server runs one process (jobs are held in memory) with many threads, and transcribes one video at a time
per GPU. For more traffic, run more GPU servers behind a queue: that's the next step in the plan.

## Files

| File | What it does |
| --- | --- |
| `app.py` | Web server and job pipeline |
| `transcriber.py` | Picks MLX or faster-whisper and runs speech-to-text |
| `looks.py` | The caption templates, and the page/line/key-word rules shared with the preview |
| `render.py` | Lays out every word (HarfBuzz) and burns the template into the video (ffmpeg + libass) |
| `project.py` | Projects: the saved document (captions as words, supers, styles), storage and 30-day cleanup |
| `assgen.py` | A project → the ASS file both the preview and the export draw, plus where each word lands |
| `compose.py` | Exports a whole timeline with ffmpeg: clips cut and fitted to the frame, video tracks stacked, audio mixed with volumes and fades, captions burned in |
| `static/editor/` | The editor: `app.js` (list, timeline, player), `model.js` (project, saving, text edits that keep timing), `player.js` (the timeline clock and clip playback), `timeline.js` (ruler, caption, text and clip lanes), `clips.js` (import, cut, trim, tracks, frame), `preview.js` (libass preview and on-video dragging), `inspector.js` (selection and Style panel), `supers.js` (text on screen) |
| `static/vendor/jassub/` | libass compiled to WebAssembly (JASSUB 1.8.8, LGPL; licences inside) |
| `static/captions.js` | Template thumbnails, and the preview when WebAssembly isn't available |
| `fontmatch.py`, `fontindex.py` | Match from image: read the picture, compare it with every font and all of Google Fonts |
| `hinglish.py`, `hinglish_words.py`, `ai_correct.py` | Devanagari → Hinglish (rules + word lists), then AI cleanup (Claude or Groq) |
| `feedback.py` | Learns word fixes from each user's edits (`data/feedback/`) |
| `config.py`, `.env.example` | Settings; local mode vs website mode |
| `db.py`, `plans.py` | Users, monthly usage, payments (SQLite); plan limits and prices |
| `auth.py`, `billing.py` | Google sign-in; Razorpay orders, verification and webhook |
| `templates/landing.html` | Public home page with pricing (website mode) |
| `Dockerfile` | Cloud GPU image (CUDA) |
| `typefaces.py` | The caption font library: names, groups, size corrections, Hindi support |
| `fonts/` | The 74 caption fonts from Google Fonts (SIL Open Font License or Apache 2.0, both fine for commercial use); each licence is in `fonts/licenses/` |

Uploaded videos and exports are kept for 6 hours so you can re-export, then deleted.
