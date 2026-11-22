#!/usr/bin/env python3
"""Users, usage and payments in one SQLite file (data/app.db).

SQLite ships with Python on Mac and Windows, so there is nothing to install.
For one server this is plenty; move to Postgres when you run several.
"""
import os, sqlite3, threading, time, uuid
from contextlib import contextmanager

import config
from plans import PLANS, PRODUCTS, DAY

PATH = os.path.join(config.DATA_DIR, "app.db")
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    google_sub TEXT UNIQUE,
    email TEXT,
    name TEXT,
    picture TEXT,
    plan TEXT NOT NULL DEFAULT 'free',
    plan_until REAL NOT NULL DEFAULT 0,
    bonus_seconds REAL NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    user_id TEXT NOT NULL,
    period TEXT NOT NULL,              -- calendar month, 'YYYY-MM' (UTC)
    seconds REAL NOT NULL DEFAULT 0,
    videos INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, period)
);
CREATE TABLE IF NOT EXISTS payments (
    order_id TEXT PRIMARY KEY,         -- Razorpay order id
    user_id TEXT NOT NULL,
    product TEXT NOT NULL,
    amount INTEGER NOT NULL,           -- paise
    status TEXT NOT NULL DEFAULT 'created',
    payment_id TEXT,
    created REAL NOT NULL,
    paid REAL
);
"""


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(PATH, timeout=30, isolation_level=None)   # autocommit; explicit BEGIN below
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


@contextmanager
def tx():
    """Write transaction that takes the lock up front, so read-then-write is atomic."""
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def init():
    conn().executescript(SCHEMA)
    if config.LOCAL_MODE and not get_user("local"):
        with tx() as c:
            c.execute("INSERT INTO users (id, email, name, plan, created) VALUES ('local', '', 'You', 'local', ?)",
                      (time.time(),))


def get_user(uid):
    row = conn().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def upsert_google_user(sub, email, name, picture):
    with tx() as c:
        row = c.execute("SELECT id FROM users WHERE google_sub = ?", (sub,)).fetchone()
        if row:
            c.execute("UPDATE users SET email = ?, name = ?, picture = ? WHERE id = ?",
                      (email, name, picture, row["id"]))
            return row["id"]
        uid = uuid.uuid4().hex
        c.execute("INSERT INTO users (id, google_sub, email, name, picture, created) VALUES (?, ?, ?, ?, ?, ?)",
                  (uid, sub, email, name, picture, time.time()))
        return uid


def _period():
    return time.strftime("%Y-%m", time.gmtime())


def _active_plan(user):
    if user["plan"] == "local":
        return "local"
    return user["plan"] if user["plan_until"] > time.time() else "free"


def account(uid):
    """Everything the UI needs about the user's plan and minutes left."""
    user = get_user(uid)
    if not user:
        return None
    plan_key = _active_plan(user)
    plan = PLANS[plan_key]
    row = conn().execute("SELECT seconds, videos FROM usage WHERE user_id = ? AND period = ?",
                         (uid, _period())).fetchone()
    used = row["seconds"] if row else 0.0
    if plan["minutes"] is None:
        remaining = None
    else:
        remaining = max(0.0, plan["minutes"] * 60 - used) + user["bonus_seconds"]
    return {
        "id": uid, "email": user["email"], "name": user["name"], "picture": user["picture"],
        "plan": plan_key, "plan_name": plan["name"],
        "plan_until": user["plan_until"] if plan_key not in ("free", "local") else None,
        "monthly_minutes": plan["minutes"], "max_seconds": plan["max_seconds"], "watermark": plan["watermark"],
        "used_seconds": round(used, 1), "bonus_seconds": round(user["bonus_seconds"], 1),
        "remaining_seconds": None if remaining is None else round(remaining, 1),
        "videos_this_month": row["videos"] if row else 0,
    }


def check_allowed(uid, seconds, reserved=0.0):
    """None if this video may be processed, otherwise a message for the user.
    `reserved` = seconds of this user's videos still processing (not charged yet)."""
    acc = account(uid)
    if acc["max_seconds"] and seconds > acc["max_seconds"] + 1:
        return (f"Videos on the {acc['plan_name']} plan can be up to {acc['max_seconds'] // 60} minutes long. "
                f"This one is {seconds / 60:.1f} minutes.")
    if acc["remaining_seconds"] is not None and seconds > acc["remaining_seconds"] - reserved + 1:
        left = max(0.0, acc["remaining_seconds"] - reserved)
        return (f"This video is {seconds / 60:.1f} minutes but you have {left / 60:.1f} minutes left "
                f"this month. Upgrade or add a top-up to continue.")
    return None


def charge(uid, seconds):
    """Record a processed video. Monthly allowance is used first, then top-up minutes."""
    period = _period()
    with tx() as c:
        user = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        plan = PLANS[_active_plan(dict(user))]
        row = c.execute("SELECT seconds FROM usage WHERE user_id = ? AND period = ?", (uid, period)).fetchone()
        before = row["seconds"] if row else 0.0
        c.execute("INSERT INTO usage (user_id, period, seconds, videos) VALUES (?, ?, ?, 1) "
                  "ON CONFLICT(user_id, period) DO UPDATE SET seconds = seconds + excluded.seconds, videos = videos + 1",
                  (uid, period, seconds))
        if plan["minutes"] is not None:
            allowance = plan["minutes"] * 60
            overflow = max(0.0, before + seconds - allowance) - max(0.0, before - allowance)
            if overflow > 0:
                c.execute("UPDATE users SET bonus_seconds = MAX(0, bonus_seconds - ?) WHERE id = ?", (overflow, uid))


# ---------------------------------------------------------------- payments

def create_payment(order_id, uid, product, amount):
    with tx() as c:
        c.execute("INSERT INTO payments (order_id, user_id, product, amount, created) VALUES (?, ?, ?, ?, ?)",
                  (order_id, uid, product, amount, time.time()))


def fulfil(order_id, payment_id):
    """Apply a paid order exactly once (the browser and the webhook may both report it).
    Returns the user id, or None for an unknown order."""
    with tx() as c:
        pay = c.execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
        if not pay:
            return None
        if pay["status"] == "paid":
            return pay["user_id"]
        product = PRODUCTS[pay["product"]]
        user = c.execute("SELECT * FROM users WHERE id = ?", (pay["user_id"],)).fetchone()
        now = time.time()
        if "plan" in product:
            # Same plan bought again extends it; a different plan starts today.
            start = user["plan_until"] if user["plan"] == product["plan"] and user["plan_until"] > now else now
            c.execute("UPDATE users SET plan = ?, plan_until = ? WHERE id = ?",
                      (product["plan"], start + product["days"] * DAY, user["id"]))
        if "minutes" in product:
            c.execute("UPDATE users SET bonus_seconds = bonus_seconds + ? WHERE id = ?",
                      (product["minutes"] * 60, user["id"]))
        c.execute("UPDATE payments SET status = 'paid', payment_id = ?, paid = ? WHERE order_id = ?",
                  (payment_id, now, order_id))
        return pay["user_id"]


def payment(order_id):
    row = conn().execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
    return dict(row) if row else None
