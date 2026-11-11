#!/bin/bash
# Double-click to start on macOS. First run sets everything up (a few minutes).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up for the first time..."
  python3 -m venv .venv || { echo "Python 3.9+ is required: https://www.python.org/downloads/"; read -r; exit 1; }
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt || { echo "Install failed."; read -r; exit 1; }
.venv/bin/python app.py
