#!/usr/bin/env python3
"""Plans, limits and what each purchase gives. Prices are in paise (₹1 = 100 paise)."""

DAY = 86400

PLANS = {
    #          monthly minutes  longest video (s)  watermark on export
    "free":    {"name": "Free",    "minutes": 10,   "max_seconds": 120,   "watermark": True,  "price": 0},
    "creator": {"name": "Creator", "minutes": 120,  "max_seconds": 300,   "watermark": False, "price": 29900},
    "pro":     {"name": "Pro",     "minutes": 400,  "max_seconds": 1800,  "watermark": False, "price": 79900},
    # LOCAL MODE: your own machine, no limits.
    "local":   {"name": "Local",   "minutes": None, "max_seconds": None,  "watermark": False, "price": 0},
}

# What can be bought. Plans are sold as 30-day passes: UPI one-off payments work for
# everyone, while UPI autopay mandates add friction and fail more often.
PRODUCTS = {
    "creator_30d": {"label": "Creator · 30 days", "amount": 29900, "plan": "creator", "days": 30},
    "pro_30d":     {"label": "Pro · 30 days",     "amount": 79900, "plan": "pro",     "days": 30},
    "topup_30":    {"label": "30 extra minutes",   "amount": 9900,  "minutes": 30},
}
