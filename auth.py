#!/usr/bin/env python3
"""Google sign-in. The browser gets an ID token from Google's button and posts it
here; we verify it with Google's public keys and start a session cookie.

In LOCAL MODE everyone is the built-in local user and no sign-in is shown.
"""
from functools import wraps

from flask import Blueprint, jsonify, request, session

import config
import db

bp = Blueprint("auth", __name__)


def current_uid():
    if config.LOCAL_MODE:
        return "local"
    uid = session.get("uid")
    return uid if uid and db.get_user(uid) else None


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not current_uid():
            return jsonify(error="Please sign in again.", signin=True), 401
        return view(*a, **kw)
    return wrapper


@bp.route("/auth/google", methods=["POST"])
def google_signin():
    if config.LOCAL_MODE:
        return jsonify(ok=True)
    token = (request.get_json(silent=True) or {}).get("credential", "")
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        info = id_token.verify_oauth2_token(token, google_requests.Request(), config.GOOGLE_CLIENT_ID)
    except Exception:
        return jsonify(error="Google sign-in could not be verified. Please try again."), 401
    if not info.get("email_verified"):
        return jsonify(error="Please use a Google account with a verified email."), 401
    uid = db.upsert_google_user(info["sub"], info.get("email", ""), info.get("name", ""), info.get("picture", ""))
    session.clear()
    session["uid"] = uid
    session.permanent = True
    return jsonify(ok=True)


@bp.route("/auth/demo", methods=["POST"])
def demo_signin():
    """DEMO MODE only: sign in as a named test user, no Google needed."""
    if not config.DEMO_MODE:
        return jsonify(error="Not available"), 404
    name = ((request.get_json(silent=True) or {}).get("name") or "Test user").strip()[:40] or "Test user"
    slug = "".join(ch for ch in name.lower() if ch.isalnum()) or "test"
    uid = db.upsert_google_user(f"demo-{slug}", f"{slug}@demo.local", name, "")
    session.clear()
    session["uid"] = uid
    return jsonify(ok=True)


@bp.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(ok=True)
