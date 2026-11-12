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

## Hinglish AI correction

Set an Anthropic API key before starting, or Hinglish mode falls back to the basic transliteration:

- Mac: `export ANTHROPIC_API_KEY=sk-ant-...`
- Windows: `setx ANTHROPIC_API_KEY sk-ant-...` (then open a new window)

Only subtitle text is sent, never audio or video.

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
| `static/captions.js` | The live template preview in the browser, matching the export |
| `hinglish.py`, `ai_correct.py` | Devanagari → Hinglish, then Claude cleanup |
| `feedback.py` | Learns word fixes from each user's edits (`data/feedback/`) |
| `config.py`, `.env.example` | Settings; local mode vs website mode |
| `db.py`, `plans.py` | Users, monthly usage, payments (SQLite); plan limits and prices |
| `auth.py`, `billing.py` | Google sign-in; Razorpay orders, verification and webhook |
| `templates/landing.html` | Public home page with pricing (website mode) |
| `Dockerfile` | Cloud GPU image (CUDA) |
| `typefaces.py` | The caption font library: names, groups, size corrections, Hindi support |
| `fonts/` | The 74 caption fonts from Google Fonts (SIL Open Font License or Apache 2.0, both fine for commercial use); each licence is in `fonts/licenses/` |

Uploaded videos and exports are kept for 6 hours so you can re-export, then deleted.
