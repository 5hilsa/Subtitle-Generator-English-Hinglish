#!/bin/bash
# Double-click to try the full website on this Mac: test sign-in, simulated payments.
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run start-mac.command once first to set things up."; read -r; exit 1; }
DEMO_MODE=1 .venv/bin/python app.py
