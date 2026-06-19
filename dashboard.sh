#!/usr/bin/env bash
# Scalp Bot dashboard'u baslatir (http://127.0.0.1:8000).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

exec ./.venv/bin/python -m scalpbot.dashboard "$@"
