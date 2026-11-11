#!/usr/bin/env python3
"""Razorpay payments: UPI, cards and netbanking.

Flow: the browser asks for an order (/billing/order), opens Razorpay Checkout,
and posts the signed result back (/billing/verify). Razorpay also calls the
webhook (/billing/webhook), so a payment still counts if the browser closes
before it reports back. Either path fulfils the order exactly once.
"""
import hashlib, hmac, json, time, uuid

import requests
from flask import Blueprint, jsonify, request

import config
import db
from auth import current_uid, login_required
from plans import PLANS, PRODUCTS

bp = Blueprint("billing", __name__)
API = "https://api.razorpay.com/v1"


def _sign(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


@bp.route("/billing/plans")
def plans():
    return jsonify(
        payments=config.PAYMENTS_ENABLED,
        plans={k: v for k, v in PLANS.items() if k != "local"},
        products=PRODUCTS,
    )


@bp.route("/billing/order", methods=["POST"])
@login_required
def create_order():
    if not config.PAYMENTS_ENABLED:
        return jsonify(error="Payments are not set up on this server yet."), 503
    product_key = (request.get_json(silent=True) or {}).get("product")
    product = PRODUCTS.get(product_key)
    if not product:
        return jsonify(error="Unknown product"), 400
    uid = current_uid()
    if config.DEMO_MODE:
        # Simulated checkout: no Razorpay call, no money. Paid via /billing/demo-pay.
        order_id = f"demo_{uuid.uuid4().hex[:14]}"
        db.create_payment(order_id, uid, product_key, product["amount"])
        return jsonify(demo=True, order_id=order_id, amount=product["amount"], description=product["label"])
    try:
        r = requests.post(f"{API}/orders", auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET), timeout=20,
                          json={"amount": product["amount"], "currency": "INR",
                                "receipt": f"{uid[:12]}-{int(time.time())}",
                                "notes": {"user_id": uid, "product": product_key}})
        r.raise_for_status()
        order = r.json()
    except Exception:
        return jsonify(error="Could not start the payment. Please try again in a minute."), 502
    db.create_payment(order["id"], uid, product_key, product["amount"])
    user = db.get_user(uid)
    return jsonify(order_id=order["id"], amount=product["amount"], currency="INR", key_id=config.RAZORPAY_KEY_ID,
                   name=config.APP_NAME, description=product["label"],
                   prefill={"email": user["email"], "name": user["name"]})


@bp.route("/billing/demo-pay", methods=["POST"])
@login_required
def demo_pay():
    """DEMO MODE only: mark a simulated order as paid, exactly as a real payment would be."""
    if not config.DEMO_MODE:
        return jsonify(error="Not available"), 404
    order_id = (request.get_json(silent=True) or {}).get("order_id", "")
    pay = db.payment(order_id)
    if not pay or pay["user_id"] != current_uid() or not order_id.startswith("demo_"):
        return jsonify(error="Unknown order"), 404
    db.fulfil(order_id, "demo_payment")
    return jsonify(ok=True)


@bp.route("/billing/verify", methods=["POST"])
@login_required
def verify():
    d = request.get_json(silent=True) or {}
    order_id, payment_id = d.get("razorpay_order_id", ""), d.get("razorpay_payment_id", "")
    expected = _sign(config.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode())
    if not hmac.compare_digest(expected, d.get("razorpay_signature", "")):
        return jsonify(error="Payment could not be verified. If money was taken, it will be credited shortly."), 400
    pay = db.payment(order_id)
    if not pay or pay["user_id"] != current_uid():
        return jsonify(error="Unknown order"), 404
    db.fulfil(order_id, payment_id)
    return jsonify(ok=True)


@bp.route("/billing/webhook", methods=["POST"])
def webhook():
    """Set this URL in the Razorpay dashboard with events payment.captured and order.paid."""
    if not config.RAZORPAY_WEBHOOK_SECRET:
        return jsonify(error="Webhook not configured"), 503
    body = request.get_data()
    if not hmac.compare_digest(_sign(config.RAZORPAY_WEBHOOK_SECRET, body),
                               request.headers.get("X-Razorpay-Signature", "")):
        return jsonify(error="Bad signature"), 400
    event = json.loads(body or b"{}")
    if event.get("event") in ("payment.captured", "order.paid"):
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        if payment.get("order_id"):
            db.fulfil(payment["order_id"], payment.get("id"))
    return jsonify(ok=True)
