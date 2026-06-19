#!/usr/bin/env bash
# Scalp Bot calistirici — venv'i kurar ve botu baslatir.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

exec ./.venv/bin/python -m scalpbot.main "$@"
