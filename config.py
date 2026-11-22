#!/usr/bin/env python3
"""Settings, read from environment variables or a `.env` file next to this one.

With no GOOGLE_CLIENT_ID the app runs in LOCAL MODE: one built-in user, no
sign-in, no limits, no payments. That is how it runs on your own Mac or PC.
Set GOOGLE_CLIENT_ID (and the Razorpay keys) to run it as a public website.
See .env.example for every setting.
"""
import os, secrets

BASE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    """Minimal KEY=VALUE reader, so no extra package is needed. Real env vars win."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(BASE, ".env"))
env = os.environ.get

APP_NAME = env("APP_NAME", "Hinglish Captions")
BASE_URL = env("BASE_URL", "http://localhost:7860").rstrip("/")
HOST = env("HOST", "127.0.0.1")
PORT = int(env("PORT", "7860"))

DATA_DIR = env("DATA_DIR", os.path.join(BASE, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", "")

# DEMO MODE: the full website (landing page, accounts, plans, checkout) on your own
# machine with no keys: test-user sign-in instead of Google, simulated payments.
# Refuses to run on anything but localhost so it can't be left on in production.
DEMO_MODE = env("DEMO_MODE") == "1"
if DEMO_MODE and HOST not in ("127.0.0.1", "localhost"):
    raise SystemExit("DEMO_MODE only runs on localhost (HOST=127.0.0.1). Turn it off for a public server.")
LOCAL_MODE = not DEMO_MODE and env("LOCAL_MODE", "1" if not GOOGLE_CLIENT_ID else "0") == "1"

RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", "")
PAYMENTS_ENABLED = DEMO_MODE or bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def _secret_key():
    """Signs session cookies. Generated once and kept in data/ unless SECRET_KEY is set."""
    if env("SECRET_KEY"):
        return env("SECRET_KEY")
    path = os.path.join(DATA_DIR, "secret.key")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
        return key


SECRET_KEY = _secret_key()
